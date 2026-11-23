"""Memo PDF through Microsoft 365 (docs/FEES_PDF_EXPORT.md). Microsoft is never called: ``pdf_graph._urlopen`` is replaced by a
scripted fake, or ``pdf_graph.convert`` by a stub that returns a small PDF."""
import base64
import io
import json
import socket
import tempfile
import urllib.error
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import ROLE_EDITOR, ROLE_READER, Profile, ProfileMembership
from accounts.suite import KEY_FEES
from backups import registry
from fees.exports import pdf_graph
from fees.exports.filenames import content_disposition, pdf_filename
from fees.models import PdfConnection
from fees.services import word_template
from diary.tests.helpers import join_main
from fees.tests import xlsx_support as xs

User = get_user_model()
PASSWORD = "x-Test-Pw-1"
FIXTURE = Path(__file__).parent / "fixtures" / "Template 2-11-2026 (short tags).docx"
PDF = b"%PDF-1.7\n% a tiny test PDF\n%%EOF\n"
DOWNLOAD = "https://public.am.files.1drv.com/y4m-signed-link"
GRAPH_ON = dict(MS_GRAPH_CLIENT_ID="client-id", MS_GRAPH_CLIENT_SECRET="client-secret", MS_GRAPH_TOKEN_KEY="k" * 40,
                MS_GRAPH_TENANT="consumers", MS_GRAPH_REDIRECT_URI="", MS_GRAPH_SECRET_EXPIRES="")


class FakeResponse(io.BytesIO):
    def __init__(self, body=b"", status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}

    def getcode(self):
        return self.status


def answer(status=200, body=b"", headers=None):
    """What the fake returns: a response for 2xx, an ``HTTPError`` (as urllib raises) otherwise."""
    if isinstance(body, (dict, list)):
        body = json.dumps(body).encode()
    if 200 <= status < 300:
        return FakeResponse(body, status, headers)
    return urllib.error.HTTPError("https://x", status, "status", headers or {}, io.BytesIO(body))


class FakeMicrosoft:
    """Answers in order, keyed by (method, start of the address). Records every call."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def __call__(self, request, timeout):
        method, url = request.get_method(), request.full_url
        self.calls.append({"method": method, "url": url, "auth": request.get_header("Authorization"), "data": request.data})
        for i, (want_method, prefix, result) in enumerate(self.script):
            if want_method == method and url.startswith(prefix):
                del self.script[i]
                if isinstance(result, BaseException):
                    raise result
                return result
        raise AssertionError(f"unexpected call {method} {url}")


def connect(access_valid=True, refresh="refresh-1", access="access-1"):
    return PdfConnection.objects.create(
        pk=1, account="owner@hotmail.com", refresh_token=pdf_graph._seal(refresh), access_token=pdf_graph._seal(access),
        access_expires_at=timezone.now() + (timedelta(minutes=30) if access_valid else -timedelta(minutes=1)),
        connected_at=timezone.now(), connected_by="boss",
    )


def happy_path():
    return [
        ("PUT", pdf_graph.GRAPH + "/me/drive/special/approot:/" + pdf_graph.FILE_PREFIX, answer(201, {"id": "ITEM1"})),
        ("GET", pdf_graph.GRAPH + "/me/drive/items/ITEM1/content?format=pdf", answer(302, headers={"Location": DOWNLOAD})),
        ("GET", DOWNLOAD, answer(200, PDF)),
        ("DELETE", pdf_graph.GRAPH + "/me/drive/items/ITEM1", answer(204)),
    ]


@override_settings(**GRAPH_ON)
class ConvertTests(TestCase):
    def run_convert(self, script):
        fake = FakeMicrosoft(script)
        with mock.patch.object(pdf_graph, "_urlopen", fake):
            try:
                return fake, pdf_graph.convert(b"DOCX")
            except pdf_graph.PdfError as err:
                return fake, err

    def test_upload_convert_download_and_delete(self):
        connect()
        fake, pdf = self.run_convert(happy_path())
        self.assertEqual(pdf.read(), PDF)
        self.assertEqual([c["method"] for c in fake.calls], ["PUT", "GET", "GET", "DELETE"])
        self.assertEqual(fake.calls[0]["auth"], "Bearer access-1")
        self.assertEqual(fake.calls[0]["data"], b"DOCX")
        self.assertIsNone(fake.calls[2]["auth"])          # the signed download link never gets our token
        self.assertIsNotNone(PdfConnection.objects.get(pk=1).last_success_at)

    def test_a_download_from_an_untrusted_host_is_refused_and_the_word_file_still_deleted(self):
        connect()
        script = happy_path()
        script[1] = ("GET", script[1][1], answer(302, headers={"Location": "https://evil.example.com/x.pdf"}))
        del script[2]
        fake, err = self.run_convert(script)
        self.assertIn("does not trust", err.message)
        self.assertEqual(fake.calls[-1]["method"], "DELETE")
        self.assertIn("does not trust", PdfConnection.objects.get(pk=1).last_error)

    def test_an_expired_access_token_is_renewed_and_the_new_refresh_token_kept(self):
        connect(access_valid=False)
        token = ("POST", pdf_graph.LOGIN_HOST + "/consumers/oauth2/v2.0/token",
                 answer(200, {"access_token": "access-2", "refresh_token": "refresh-2", "expires_in": 3600}))
        fake, pdf = self.run_convert([token] + happy_path())
        self.assertEqual(pdf.read(), PDF)
        self.assertIn(b"grant_type=refresh_token", fake.calls[0]["data"])
        self.assertEqual(fake.calls[1]["auth"], "Bearer access-2")
        row = PdfConnection.objects.get(pk=1)
        self.assertEqual(pdf_graph._unseal(row.refresh_token), "refresh-2")
        self.assertNotIn("refresh-2", row.refresh_token)    # stored encrypted

    def test_a_dead_sign_in_is_forgotten_and_the_button_goes(self):
        connect(access_valid=False)
        token = ("POST", pdf_graph.LOGIN_HOST, answer(400, {"error": "invalid_grant"}))
        _fake, err = self.run_convert([token])
        self.assertTrue(err.reconnect)
        self.assertEqual(err.message, pdf_graph.RECONNECT)
        self.assertEqual(PdfConnection.objects.get(pk=1).refresh_token, "")
        self.assertFalse(pdf_graph.available())

    def test_a_token_microsoft_dropped_early_is_renewed_once(self):
        connect()
        token = ("POST", pdf_graph.LOGIN_HOST, answer(200, {"access_token": "access-2", "refresh_token": "refresh-2", "expires_in": 3600}))
        fake, pdf = self.run_convert([("PUT", pdf_graph.GRAPH, answer(401, {"error": {"code": "InvalidAuthenticationToken"}})), token]
                                     + happy_path())
        self.assertEqual(pdf.read(), PDF)
        self.assertEqual([c["method"] for c in fake.calls], ["PUT", "POST", "PUT", "GET", "GET", "DELETE"])
        self.assertEqual(fake.calls[2]["auth"], "Bearer access-2")

    def test_a_second_pdf_in_the_same_worker_is_refused_at_once(self):
        connect()
        self.assertTrue(pdf_graph._lock.acquire(blocking=False))
        try:
            fake, err = self.run_convert([])
        finally:
            pdf_graph._lock.release()
        self.assertEqual(err.message, pdf_graph.BUSY)
        self.assertEqual(fake.calls, [])

    def test_a_slow_microsoft_is_a_message(self):
        connect()
        _fake, err = self.run_convert([("PUT", pdf_graph.GRAPH, socket.timeout("slow"))])
        self.assertEqual(err.message, pdf_graph.TIMEOUT)

    def test_busy_microsoft_says_when_to_try_again(self):
        connect()
        _fake, err = self.run_convert([("PUT", pdf_graph.GRAPH, answer(429, {}, {"Retry-After": "12"}))])
        self.assertIn("in 12 seconds", err.message)

    def test_an_oversized_or_non_pdf_answer_is_refused(self):
        connect()
        with mock.patch.object(pdf_graph, "MAX_PDF_BYTES", 10):
            _fake, err = self.run_convert(happy_path())
        self.assertIn("larger than 20 MB", err.message)
        script = happy_path()
        script[2] = ("GET", DOWNLOAD, answer(200, b"<html>not a pdf</html>"))
        _fake, err = self.run_convert(script)
        self.assertEqual(err.message, "Microsoft 365 did not send a PDF.")

    def test_not_connected(self):
        _fake, err = self.run_convert([])
        self.assertEqual(err.message, pdf_graph.NOT_CONNECTED)

    @override_settings(MS_GRAPH_CLIENT_ID="")
    def test_not_set_up(self):
        connect()
        self.assertFalse(pdf_graph.available())
        _fake, err = self.run_convert([])
        self.assertEqual(err.message, pdf_graph.NOT_SET_UP)

    def test_allowed_download_hosts(self):
        self.assertTrue(pdf_graph.allowed_download(DOWNLOAD))
        self.assertTrue(pdf_graph.allowed_download("https://contoso-my.sharepoint.com/x"))
        self.assertFalse(pdf_graph.allowed_download("http://public.am.files.1drv.com/x"))
        self.assertFalse(pdf_graph.allowed_download("https://files.1drv.com.evil.com/x"))
        self.assertFalse(pdf_graph.allowed_download("https://evilsharepoint.com/x"))

    def test_keep_alive_renews_and_removes_only_old_leftovers(self):
        connect()
        old = (timezone.now() - timedelta(hours=3)).isoformat()
        new = timezone.now().isoformat()
        listing = {"value": [{"id": "OLD", "name": pdf_graph.FILE_PREFIX + "a.docx", "createdDateTime": old},
                             {"id": "NEW", "name": pdf_graph.FILE_PREFIX + "b.docx", "createdDateTime": new},
                             {"id": "MINE", "name": "notes.txt", "createdDateTime": old}]}
        fake = FakeMicrosoft([
            ("POST", pdf_graph.LOGIN_HOST, answer(200, {"access_token": "access-3", "refresh_token": "refresh-3", "expires_in": 3600})),
            ("GET", pdf_graph.GRAPH + "/me/drive/special/approot/children", answer(200, listing)),
            ("DELETE", pdf_graph.GRAPH + "/me/drive/items/OLD", answer(204)),
        ])
        with mock.patch.object(pdf_graph, "_urlopen", fake):
            call_command("pdf_keepalive", stdout=io.StringIO())
        self.assertEqual([c["method"] for c in fake.calls], ["POST", "GET", "DELETE"])
        self.assertEqual(pdf_graph._unseal(PdfConnection.objects.get(pk=1).refresh_token), "refresh-3")

    def test_keep_alive_does_nothing_when_not_connected(self):
        out = io.StringIO()
        with mock.patch.object(pdf_graph, "_urlopen", FakeMicrosoft([])):
            call_command("pdf_keepalive", stdout=out)
        self.assertIn("not set up or not connected", out.getvalue())


@override_settings(**GRAPH_ON)
class SignInTests(TestCase):
    def test_start_sends_pkce_and_the_app_folder_scope(self):
        url, state, verifier = pdf_graph.start_sign_in("https://site/fees/settings/pdf/callback/")
        self.assertTrue(url.startswith(pdf_graph.LOGIN_HOST + "/consumers/oauth2/v2.0/authorize?"))
        self.assertIn("code_challenge_method=S256", url)
        self.assertIn("state=" + state, url)
        self.assertIn("Files.ReadWrite.AppFolder", url.replace("+", " ").replace("%2E", "."))
        self.assertNotIn(verifier, url)

    def test_finish_stores_the_account_and_encrypted_tokens(self):
        claims = base64.urlsafe_b64encode(json.dumps({"email": "owner@hotmail.com"}).encode()).decode().rstrip("=")
        fake = FakeMicrosoft([("POST", pdf_graph.LOGIN_HOST, answer(200, {
            "access_token": "a", "refresh_token": "r", "expires_in": 3600, "id_token": f"h.{claims}.s"}))])
        with mock.patch.object(pdf_graph, "_urlopen", fake):
            account = pdf_graph.finish_sign_in("CODE", "VERIFIER", "https://site/cb/", "boss")
        self.assertEqual(account, "owner@hotmail.com")
        self.assertIn(b"code_verifier=VERIFIER", fake.calls[0]["data"])
        row = PdfConnection.objects.get(pk=1)
        self.assertEqual((row.connected_by, pdf_graph._unseal(row.refresh_token)), ("boss", "r"))
        self.assertTrue(pdf_graph.available())

    def test_a_changed_token_key_means_reconnect(self):
        connect()
        with override_settings(MS_GRAPH_TOKEN_KEY="another key entirely"):
            with self.assertRaises(pdf_graph.PdfError) as cm:
                pdf_graph._access_token(10 ** 9)
        self.assertTrue(cm.exception.reconnect)

    def test_the_connection_never_goes_into_a_backup(self):
        self.assertNotIn("fees.PdfConnection", registry.BACKUP_MODELS)
        self.assertNotIn("fees.PdfConnection", registry.FEES_BACKUP_MODELS)


def said(response):
    return "\n".join(str(m) for m in get_messages(response.wsgi_request))


def tiny_pdf(_data):
    out = tempfile.TemporaryFile()
    out.write(PDF)
    out.seek(0)
    return out


@override_settings(SECURE_SSL_REDIRECT=False, **GRAPH_ON)
class PdfViewTests(TestCase):
    def setUp(self):
        self.profile = Profile.objects.create(program=KEY_FEES, name="Pdf-Fees")
        self.seed = xs.seed_web_data(self.profile)
        word_template.upload_template(self.profile, FIXTURE.name, FIXTURE.read_bytes())
        self.reader = User.objects.create_user("pdf-reader", password=PASSWORD)
        ProfileMembership.objects.create(user=self.reader, profile=self.profile, role=ROLE_READER)
        self.editor = User.objects.create_user("pdf-editor", password=PASSWORD)
        ProfileMembership.objects.create(user=self.editor, profile=self.profile, role=ROLE_EDITOR)
        self.admin = User.objects.create_user("pdf-admin", password=PASSWORD, is_superuser=True)
        ProfileMembership.objects.create(user=self.admin, profile=self.profile, role=ROLE_EDITOR)
        self.memo = self.seed["memo_a"]
        connect()

    def detail(self, user, query=""):
        self.client.force_login(user)
        return self.client.get(reverse("fees_memo_detail", kwargs={"memo_id": self.memo.pk}) + query).content.decode()

    def pdf_url(self):
        return reverse("fees_memo_pdf", kwargs={"memo_id": self.memo.pk})

    def test_the_memo_page_shows_word_and_pdf(self):
        page = self.detail(self.reader)
        self.assertIn('aria-label="Export to Word">Word</a>', page)
        self.assertIn('<a class="button primary" href="%s" aria-label="Export to PDF" data-pdf-button>PDF</a>' % self.pdf_url(), page)
        self.assertIn("js/fees/pdf-button.js", page)

    def test_a_user_who_switched_pdf_off_sees_only_word_and_is_refused(self):
        self.reader.pdf_export = False
        self.reader.save(update_fields=["pdf_export"])
        page = self.detail(self.reader)
        self.assertIn(">Word</a>", page)
        self.assertNotIn(self.pdf_url(), page)
        self.assertEqual(self.client.get(self.pdf_url()).status_code, 403)

    def test_no_button_while_not_connected(self):
        pdf_graph.disconnect()
        self.assertNotIn(self.pdf_url(), self.detail(self.reader))

    def test_the_pdf_downloads_with_the_word_file_name(self):
        self.client.force_login(self.reader)
        with mock.patch.object(pdf_graph, "convert", side_effect=tiny_pdf) as convert:
            response = self.client.get(self.pdf_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(b"".join(response.streaming_content), PDF)
        self.assertTrue(convert.call_args[0][0].startswith(b"PK"))      # the filled Word memo went to Microsoft
        word_name, _file = word_template.render_memo_docx(self.profile, self.memo.pk)
        self.assertEqual(response["Content-Disposition"], content_disposition(pdf_filename(word_name)))

    def test_a_failure_goes_back_to_the_memo_with_the_reason_and_the_word_link(self):
        self.client.force_login(self.reader)
        with mock.patch.object(pdf_graph, "convert", side_effect=pdf_graph.PdfError(pdf_graph.TIMEOUT)):
            response = self.client.get(self.pdf_url())
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].endswith("?pdf=failed"))
        self.assertIn(pdf_graph.TIMEOUT, said(response))
        page = self.client.get(response["Location"]).content.decode()
        self.assertIn('You can <a href="%s">download the Word memo</a> instead.' % reverse("fees_memo_word", kwargs={"memo_id": self.memo.pk}), page)

    def test_another_profiles_memo_is_a_404(self):
        other = Profile.objects.create(program=KEY_FEES, name="Other-Pdf")
        theirs = xs.seed_web_data(other)["memo_a"]
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(reverse("fees_memo_pdf", kwargs={"memo_id": theirs.pk})).status_code, 404)

    def test_the_memo_form_offers_word_and_pdf_and_pdf_lands_on_the_memo_page(self):
        self.client.force_login(self.editor)
        page = self.client.get(reverse("fees_memo_edit", kwargs={"memo_id": self.memo.pk})).content.decode()
        self.assertIn('aria-label="Save and export to Word">Word</button>', page)
        self.assertIn('value="save_export_pdf" class="secondary" title="Save, then download the memo as PDF" aria-label="Save and export to PDF">PDF</button>', page)
        landing = self.detail(self.editor, "?export=pdf")
        self.assertIn('data-word-download="%s"' % self.pdf_url(), landing)

    def test_settings_show_the_connection_and_only_an_admin_gets_the_buttons(self):
        self.client.force_login(self.editor)
        page = self.client.get(reverse("fees_settings") + "?tab=word").content.decode()
        self.assertIn("PDF export through Microsoft 365", page)
        self.assertIn("Status: connected since", page)
        self.assertNotIn("owner@hotmail.com", page)          # the account is shown to Admins only
        self.assertNotIn(reverse("fees_pdf_connect"), page)
        self.client.force_login(self.admin)
        page = self.client.get(reverse("fees_settings") + "?tab=word").content.decode()
        for name in ("fees_pdf_connect", "fees_pdf_disconnect", "fees_pdf_test"):
            self.assertIn(reverse(name), page, name)
        self.assertIn("connected as owner@hotmail.com", page)

    def test_connect_keeps_the_check_in_the_session_and_goes_to_microsoft(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("fees_pdf_connect"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(pdf_graph.LOGIN_HOST + "/consumers/oauth2/v2.0/authorize?"))
        saved = self.client.session["fees_pdf_sign_in"]
        self.assertIn("state=" + saved["state"], response["Location"])

    def test_the_callback_refuses_a_wrong_state_and_accepts_the_right_one(self):
        self.client.force_login(self.admin)
        self.client.get(reverse("fees_pdf_connect"))
        response = self.client.get(reverse("fees_pdf_callback") + "?code=C&state=wrong")
        self.assertIn("could not be checked", said(response))
        self.client.get(reverse("fees_pdf_connect"))
        state = self.client.session["fees_pdf_sign_in"]["state"]
        with mock.patch.object(pdf_graph, "finish_sign_in", return_value="owner@hotmail.com") as finish:
            response = self.client.get(reverse("fees_pdf_callback") + f"?code=C&state={state}")
        self.assertEqual(finish.call_args[0][0], "C")
        self.assertTrue(response["Location"].endswith(reverse("fees_settings") + "?tab=word"))
        self.assertIn("connected to Microsoft 365 as owner@hotmail.com", said(response))

    def test_a_callback_that_did_not_start_here_shows_nothing_it_carries(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("fees_pdf_callback") + "?error=x&error_description=Call+this+number&state=\u00e9")
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("Call this number", said(response))
        self.client.get(reverse("fees_pdf_connect"))
        state = self.client.session["fees_pdf_sign_in"]["state"]
        response = self.client.get(reverse("fees_pdf_callback") + f"?error=access_denied&error_description=Call+this+number&state={state}")
        self.assertIn("not connected (access_denied)", said(response))
        self.assertNotIn("Call this number", said(response))

    def test_a_failed_connect_stays_on_the_settings_page(self):
        self.client.force_login(self.admin)
        pdf_graph.disconnect()
        self.client.get(reverse("fees_pdf_callback") + "?code=C&state=S")       # no Connect in progress in this browser
        page = self.client.get(reverse("fees_settings") + "?tab=word").content.decode()
        self.assertIn("Status: not connected.", page)
        self.assertIn("Last problem", page)
        self.assertIn("no Connect in progress on this address", page)

    @override_settings(MS_GRAPH_REDIRECT_URI="https://madon.example/fees/settings/pdf/callback/", ALLOWED_HOSTS=["testserver", "madon.example"])
    def test_connect_on_another_address_of_the_site_moves_to_the_registered_one(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("fees_pdf_connect"))
        self.assertEqual(response["Location"], "https://madon.example" + reverse("fees_pdf_connect"))
        self.assertNotIn("fees_pdf_sign_in", self.client.session)
        response = self.client.get(reverse("fees_pdf_connect"), HTTP_HOST="madon.example", secure=True)
        self.assertTrue(response["Location"].startswith(pdf_graph.LOGIN_HOST))

    def test_microsofts_reason_is_named_when_the_code_is_refused(self):
        self.client.force_login(self.admin)
        self.client.get(reverse("fees_pdf_connect"))
        state = self.client.session["fees_pdf_sign_in"]["state"]
        refused = FakeMicrosoft([("POST", pdf_graph.LOGIN_HOST, answer(401, {
            "error": "invalid_client", "error_description": "AADSTS7000215: Invalid client secret provided."}))])
        with mock.patch.object(pdf_graph, "_urlopen", refused):
            response = self.client.get(reverse("fees_pdf_callback") + f"?code=C&state={state}")
        self.assertIn("invalid_client, AADSTS7000215", said(response))
        self.assertIn("AADSTS7000215", PdfConnection.objects.get(pk=1).last_error)
        self.assertFalse(pdf_graph.available())

    def test_disconnect_forgets_the_sign_in(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("fees_pdf_disconnect"))
        self.assertFalse(PdfConnection.objects.exists())

    def test_the_admin_can_test_with_the_newest_memo(self):
        self.client.force_login(self.admin)
        with mock.patch.object(pdf_graph, "convert", side_effect=tiny_pdf):
            response = self.client.get(reverse("fees_pdf_test"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")


@override_settings(SECURE_SSL_REDIRECT=False)
class MySettingsSwitchTests(TestCase):
    def test_each_user_switches_their_own_pdf_button(self):
        user = join_main(User.objects.create_user("lena", password=PASSWORD))
        self.assertTrue(user.pdf_export)
        self.client.force_login(user)
        page = self.client.get(reverse("my_settings") + "?tab=display").content.decode()
        self.assertIn('name="pdf_export"', page)
        self.assertIn("Memo PDF button", page)
        self.client.post(reverse("my_settings"), {"tab": "display", "colour_theme": "oxblood"})
        user.refresh_from_db()
        self.assertFalse(user.pdf_export)
        self.client.post(reverse("my_settings"), {"tab": "display", "colour_theme": "oxblood", "pdf_export": "on"})
        user.refresh_from_db()
        self.assertTrue(user.pdf_export)
