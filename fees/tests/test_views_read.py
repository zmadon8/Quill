"""Read views of the Fee Register (T7.1): every GET route, the role rules, the JSON shapes and the 404 scope.

A Reader may GET every page and export except the Editor-only ones (payments, backup, import). A user with no
Fee Register membership gets 403, an anonymous user is sent to login, and another profile's object id is a 404.
These tests use the Django test client, so a download is read through ``streaming_content``.
"""
import re
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.models import ROLE_EDITOR, ROLE_READER, Profile, ProfileMembership
from accounts.suite import KEY_DIARY, KEY_FEES
from fees.exports.placeholders import TEXT_TAGS
from fees.models import Payment
from fees.services import word_template
from fees.services.heavy import Busy
from fees.tests import docx_support as ds
from fees.tests import xlsx_support as xs

User = get_user_model()
PASSWORD = "x-Test-Pw-1"


def make_user(name, profile=None, role=None):
    user = User.objects.create_user(username=name, password=PASSWORD)
    if profile is not None:
        ProfileMembership.objects.create(user=user, profile=profile, role=role)
    return user


@override_settings(SECURE_SSL_REDIRECT=False)
class SeededViewsBase(TestCase):
    """A seeded Fee Register profile with a Reader, an Editor, an outsider and a second seeded profile."""

    def setUp(self):
        self.profile = Profile.objects.create(program=KEY_FEES, name="Views-Fees")
        self.seed = xs.seed_web_data(self.profile)
        everything = " ".join("{{%s}}" % name for name in sorted(TEXT_TAGS))
        template = ds.build_docx(ds.document_xml(ds.paragraph(everything)))
        word_template.upload_template(self.profile, "all-tags.docx", template)
        word_template.upload_signature(self.profile, "sig.png", "image/png", ds.png_bytes(80, 30))
        self.reader = make_user("reader-v", self.profile, ROLE_READER)
        self.editor = make_user("editor-v", self.profile, ROLE_EDITOR)
        self.outsider = make_user("outsider-v")
        self.other_profile = Profile.objects.create(program=KEY_FEES, name="Other-Fees")
        self.other_seed = xs.seed_web_data(self.other_profile)

    def login(self, user):
        self.client.force_login(user)

    def body(self, response):
        """The bytes of a download (or of an ordinary response)."""
        if getattr(response, "streaming", False):
            return b"".join(response.streaming_content)
        return response.content

    def ids(self):
        s = self.seed
        return {
            "memo": s["memo_a"].pk,
            "draft": s["draft"].pk,
            "firm": s["firm_a"].pk,
            "matter": s["matter_1"].pk,
            "payment": s["single"]["id"],
        }


class RouteTests(SeededViewsBase):
    def routes(self):
        i = self.ids()
        return {
            "html": [
                ("fees_dashboard", {}, ""),
                ("fees_statistics", {}, "?granularity=month&fy=2026-27"),
                ("fees_statistics", {}, "?granularity=financialYear"),
                ("fees_statistics_year_end", {}, "?fy=2026-27"),
                ("fees_memos", {}, ""),
                ("fees_memos", {}, "?fy=2026-27&unpaid=1"),
                ("fees_memo_drafts", {}, ""),
                ("fees_memo_new", {}, ""),
                ("fees_memo_new", {}, "?matter=%d" % i["matter"]),
                ("fees_memo_detail", {"memo_id": i["memo"]}, ""),
                ("fees_memo_detail", {"memo_id": i["draft"]}, ""),
                ("fees_memo_edit", {"memo_id": i["memo"]}, ""),
                ("fees_memo_edit", {"memo_id": i["draft"]}, ""),
                ("fees_memo_based_on", {"memo_id": i["memo"]}, ""),
                ("fees_firms", {}, ""),
                ("fees_firms", {}, "?status=archived"),
                ("fees_firm_new", {}, ""),
                ("fees_firm_detail", {"firm_id": i["firm"]}, ""),
                ("fees_firm_edit", {"firm_id": i["firm"]}, ""),
                ("fees_firm_statement", {"firm_id": i["firm"]}, ""),
                ("fees_firm_ledger", {"firm_id": i["firm"]}, ""),
                ("fees_matter_new", {}, "?firm=%d" % i["firm"]),
                ("fees_matter_detail", {"matter_id": i["matter"]}, ""),
                ("fees_matter_edit", {"matter_id": i["matter"]}, ""),
                ("fees_matter_statement", {"matter_id": i["matter"]}, ""),
                ("fees_matter_ledger", {"matter_id": i["matter"]}, ""),
                ("fees_feebook", {}, ""),
                ("fees_feebook", {}, "?unaccounted=1"),
                ("fees_outstanding", {}, ""),
                ("fees_outstanding", {}, "?sort=name&written_off=1"),
                ("fees_outstanding_detail", {}, ""),
                ("fees_outstanding_detail", {}, "?overdue=1"),
                ("fees_search_page", {}, "?q=alpha"),
                ("fees_settings", {}, ""),
            ],
            "json": [
                ("fees_dashboard_kpis", {}, ""),
                ("fees_statistics_data", {}, "?granularity=month&fy=2026-27"),
                ("fees_statistics_explore", {}, "?measure=billed&row_dim=financialYear&col_dim=none"),
                ("fees_statistics_views", {}, ""),
                ("fees_memo_preview_number", {}, "?date=2026-07-15"),
                ("fees_search", {}, "?q=alpha"),
                ("fees_filename_preview", {}, "?pattern=Memo+%7Bmemo_no%7D"),
                ("fees_settings_statistics_grid", {}, "?fy=2026-27"),
            ],
            "files": [
                ("fees_memo_word", {"memo_id": i["memo"]}, ""),
                ("fees_memos_export", {}, ""),
                ("fees_memo_statement", {"memo_id": i["memo"]}, ""),
                ("fees_firm_statement_export", {"firm_id": i["firm"]}, ""),
                ("fees_firm_ledger_export", {"firm_id": i["firm"]}, ""),
                ("fees_matter_statement_export", {"matter_id": i["matter"]}, ""),
                ("fees_matter_ledger_export", {"matter_id": i["matter"]}, ""),
                ("fees_feebook_export", {}, ""),
                ("fees_outstanding_export", {}, ""),
                ("fees_outstanding_summary_export", {}, ""),
                ("fees_statistics_export", {}, "?granularity=month&fy=2026-27"),
                ("fees_statistics_annual_export", {}, "?fy=2026-27"),
                ("fees_statistics_tax_summary", {}, "?fy=2026-27"),
                ("fees_template_download", {}, ""),
                ("fees_signature_download", {}, ""),
            ],
        }

    def editor_only(self):
        i = self.ids()
        return {
            "html": [
                ("fees_payment_new", {}, ""),
                ("fees_payment_new", {}, "?memo=%d" % i["memo"]),
                ("fees_payment_edit", {"payment_id": i["payment"]}, ""),
                ("fees_backup", {}, ""),
                ("fees_import", {}, ""),
            ],
            "json": [("fees_payment_payees", {}, "?matters=%d" % i["matter"])],
            "files": [("fees_backup_download", {}, "")],
        }

    def get(self, name, kwargs, query):
        return self.client.get(reverse(name, kwargs=kwargs) + query)

    def check(self, routes, user):
        self.login(user)
        for kind, rows in routes.items():
            for name, kwargs, query in rows:
                label = f"{name} {query}"
                response = self.get(name, kwargs, query)
                self.assertEqual(response.status_code, 200, label)
                if kind == "html":
                    self.assertIn("text/html", response["Content-Type"], label)
                    self.assertContains(response, "Fee Register", msg_prefix=label)
                elif kind == "json":
                    self.assertEqual(response["Content-Type"], "application/json", label)
                    self.assertIs(response.json()["ok"], True, label)
                else:
                    self.assertIn("filename*=UTF-8''", response["Content-Disposition"], label)
                    self.assertTrue(self.body(response), label)

    def test_reader_gets_every_read_route(self):
        self.check(self.routes(), self.reader)

    def test_editor_gets_every_route(self):
        self.check(self.routes(), self.editor)
        self.check(self.editor_only(), self.editor)

    def test_reader_is_refused_the_editor_only_routes(self):
        self.login(self.reader)
        for rows in self.editor_only().values():
            for name, kwargs, query in rows:
                self.assertEqual(self.get(name, kwargs, query).status_code, 403, name)

    def test_user_without_membership_gets_403_everywhere(self):
        self.login(self.outsider)
        for routes in (self.routes(), self.editor_only()):
            for rows in routes.values():
                for name, kwargs, query in rows:
                    self.assertEqual(self.get(name, kwargs, query).status_code, 403, name)

    def test_anonymous_is_sent_to_login(self):
        for routes in (self.routes(), self.editor_only()):
            for rows in routes.values():
                for name, kwargs, query in rows:
                    response = self.get(name, kwargs, query)
                    self.assertEqual(response.status_code, 302, name)
                    self.assertIn(reverse("login"), response["Location"], name)

    def test_exports_are_get_only(self):
        self.login(self.editor)
        for name, kwargs, _query in self.routes()["files"]:
            self.assertEqual(self.client.post(reverse(name, kwargs=kwargs)).status_code, 405, name)

    def test_diary_user_without_fees_membership_is_refused(self):
        diary = Profile.objects.create(program=KEY_DIARY, name="Diary-Only")
        user = make_user("diary-only-v", diary, ROLE_EDITOR)
        self.login(user)
        self.assertEqual(self.client.get(reverse("fees_dashboard")).status_code, 403)


class LandingTests(SeededViewsBase):
    def test_landing_opens_the_default_tab(self):
        self.login(self.reader)
        # The seed sets default_tab to "firms".
        response = self.client.get("/fees/")
        self.assertRedirects(response, reverse("fees_firms"), fetch_redirect_response=False)

    def test_landing_follows_the_setting(self):
        from fees.models import FeesSettings

        FeesSettings.objects.filter(profile=self.profile).update(default_tab="outstanding")
        self.login(self.reader)
        self.assertRedirects(
            self.client.get(reverse("fees_landing")), reverse("fees_outstanding"), fetch_redirect_response=False
        )

    def test_fees_without_slash_redirects(self):
        response = self.client.get("/fees")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "/fees/")

    def test_landing_url_for_a_fees_user_is_the_landing_redirect(self):
        from accounts import landing

        self.editor.landing_program = KEY_FEES
        self.editor.save()
        self.assertEqual(landing.landing_url(self.editor), reverse("fees_landing"))


class ReadOnlyGetTests(SeededViewsBase):
    def test_a_readers_first_get_creates_no_settings_row(self):
        from fees.models import FeesSettings

        FeesSettings.objects.filter(profile=self.profile).delete()
        self.login(self.reader)
        self.assertEqual(self.client.get(reverse("fees_firms")).status_code, 200)
        self.assertEqual(self.client.get(reverse("fees_memos")).status_code, 200)
        self.assertFalse(FeesSettings.objects.filter(profile=self.profile).exists())

    def test_head_is_allowed_wherever_get_is(self):
        self.login(self.editor)
        for name in ("fees_firms", "fees_statistics", "fees_search_page", "fees_firm_new", "fees_backup"):
            self.assertEqual(self.client.head(reverse(name)).status_code, 200, name)


class HomeButtonTests(SeededViewsBase):
    def test_fees_user_sees_the_fees_button(self):
        self.login(self.reader)
        response = self.client.get(reverse("home") + "?home=1")
        self.assertContains(response, 'href="%s"' % reverse("fees_landing"))
        self.assertNotContains(response, "No programs are available")

    def test_diary_only_user_sees_no_fees_button(self):
        diary = Profile.objects.create(program=KEY_DIARY, name="Diary-Home")
        user = make_user("diary-home-v", diary, ROLE_EDITOR)
        self.login(user)
        response = self.client.get(reverse("home") + "?home=1")
        self.assertNotContains(response, "/fees/")
        self.assertContains(response, 'href="%s"' % reverse("diary_home"))


class ScopeTests(SeededViewsBase):
    """Another profile's object id is a 404 and never shows its data."""

    def other_ids(self):
        s = self.other_seed
        return {
            "memo": s["memo_a"].pk,
            "firm": s["firm_a"].pk,
            "matter": s["matter_1"].pk,
            "payment": s["single"]["id"],
        }

    def test_other_profiles_objects_are_404(self):
        o = self.other_ids()
        self.login(self.editor)
        names = [
            ("fees_memo_detail", {"memo_id": o["memo"]}),
            ("fees_memo_edit", {"memo_id": o["memo"]}),
            ("fees_memo_based_on", {"memo_id": o["memo"]}),
            ("fees_memo_word", {"memo_id": o["memo"]}),
            ("fees_memo_statement", {"memo_id": o["memo"]}),
            ("fees_firm_detail", {"firm_id": o["firm"]}),
            ("fees_firm_edit", {"firm_id": o["firm"]}),
            ("fees_firm_statement", {"firm_id": o["firm"]}),
            ("fees_firm_ledger", {"firm_id": o["firm"]}),
            ("fees_firm_statement_export", {"firm_id": o["firm"]}),
            ("fees_firm_ledger_export", {"firm_id": o["firm"]}),
            ("fees_matter_detail", {"matter_id": o["matter"]}),
            ("fees_matter_edit", {"matter_id": o["matter"]}),
            ("fees_matter_statement", {"matter_id": o["matter"]}),
            ("fees_matter_ledger", {"matter_id": o["matter"]}),
            ("fees_matter_statement_export", {"matter_id": o["matter"]}),
            ("fees_matter_ledger_export", {"matter_id": o["matter"]}),
            ("fees_payment_edit", {"payment_id": o["payment"]}),
        ]
        for name, kwargs in names:
            self.assertEqual(self.client.get(reverse(name, kwargs=kwargs)).status_code, 404, name)

    def test_missing_ids_are_404(self):
        self.login(self.reader)
        self.assertEqual(self.client.get(reverse("fees_memo_detail", kwargs={"memo_id": 99999999})).status_code, 404)
        self.assertEqual(self.client.get(reverse("fees_firm_detail", kwargs={"firm_id": 99999999})).status_code, 404)

    def test_list_pages_show_only_this_profiles_data(self):
        other_firm = self.other_seed["firm_a"]
        # Both profiles have a firm with the same name, so compare ids in the links.
        self.login(self.reader)
        body = self.client.get(reverse("fees_firms")).content.decode()
        self.assertIn(reverse("fees_firm_detail", kwargs={"firm_id": self.seed["firm_a"].pk}), body)
        self.assertNotIn(reverse("fees_firm_detail", kwargs={"firm_id": other_firm.pk}), body)

    def test_payment_details_never_reach_a_page_a_reader_can_open(self):
        self.login(self.reader)
        for name, kwargs in (
            ("fees_memo_detail", {"memo_id": self.seed["memo_a"].pk}),
            ("fees_feebook", {}),
            ("fees_dashboard", {}),
        ):
            self.assertNotContains(self.client.get(reverse(name, kwargs=kwargs)), xs.PAYMENT_DETAILS_SENTINEL)


class JsonShapeTests(SeededViewsBase):
    def test_error_body_has_the_documented_shape(self):
        self.login(self.reader)
        response = self.client.get(reverse("fees_memo_preview_number") + "?date=not-a-date")
        self.assertEqual(response.status_code, 422)
        body = response.json()
        self.assertEqual(set(body), {"ok", "error", "code", "message", "details"})
        self.assertIs(body["ok"], False)
        self.assertEqual(body["error"], "INVALID_DATE")
        self.assertEqual(body["code"], "INVALID_DATE")
        self.assertTrue(body["message"])

    def test_pivot_error_uses_the_error_status(self):
        self.login(self.reader)
        response = self.client.get(reverse("fees_statistics_explore") + "?measure=billed&row_dim=bogus")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "UNKNOWN")

    def test_bad_financial_year_is_422(self):
        self.login(self.reader)
        response = self.client.get(reverse("fees_statistics_data") + "?granularity=month&fy=2026")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"], "INVALID_FINANCIAL_YEAR")

    def test_preview_number_reads_without_reserving(self):
        self.login(self.reader)
        first = self.client.get(reverse("fees_memo_preview_number") + "?date=2031-05-01").json()
        second = self.client.get(reverse("fees_memo_preview_number") + "?date=2031-05-01").json()
        self.assertEqual(first["number"], "2031-32/1")
        self.assertEqual(first["number"], second["number"])

    def test_search_json_shape(self):
        self.login(self.reader)
        body = self.client.get(reverse("fees_search") + "?q=alpha").json()
        self.assertIs(body["ok"], True)
        kinds = {row["kind"] for row in body["results"]}
        self.assertIn("firm", kinds)
        for row in body["results"]:
            self.assertEqual(set(row), {"kind", "id", "title", "subtitle"})
        self.assertEqual(self.client.get(reverse("fees_search") + "?q=a").json()["results"], [])

    def test_statistics_data_shape(self):
        self.login(self.reader)
        body = self.client.get(reverse("fees_statistics_data") + "?granularity=quarter&fy=2026-27").json()
        self.assertEqual(body["statistics"]["granularity"], "quarter")
        self.assertEqual(len(body["statistics"]["periods"]), 4)
        self.assertTrue(body["rows"])

    def test_pivot_shape(self):
        self.login(self.reader)
        body = self.client.get(
            reverse("fees_statistics_explore") + "?measure=billed&row_dim=firm&col_dim=financialYear"
        ).json()["pivot"]
        for key in ("measure", "row_dim", "col_dim", "money", "columns", "rows", "column_totals", "grand_total"):
            self.assertIn(key, body)

    def test_filename_preview_uses_the_real_function(self):
        self.login(self.reader)
        body = self.client.get(reverse("fees_filename_preview") + "?pattern=Memo+%7Bmemo_no%7D").json()
        self.assertTrue(body["file_name"].startswith("Memo "))
        self.assertTrue(body["file_name"].endswith(".docx"))
        self.assertEqual(body["errors"], [])
        self.assertIs(body["sample"], False)
        bad = self.client.get(reverse("fees_filename_preview") + "?pattern=%7Bnope%7D").json()
        self.assertTrue(bad["errors"])

    def test_filename_preview_uses_a_sample_when_there_are_no_memos(self):
        empty = Profile.objects.create(program=KEY_FEES, name="Empty-Preview")
        user = make_user("empty-preview", empty, ROLE_READER)
        self.login(user)
        body = self.client.get(reverse("fees_filename_preview") + "?pattern=Memo+%7Bmemo_no%7D+%7Bmatter%7D").json()
        self.assertIs(body["sample"], True)
        self.assertIn("Sample Matter", body["file_name"])

    def test_kpis_when_the_switch_is_on(self):
        from fees.models import FeesSettings

        FeesSettings.objects.filter(profile=self.profile).update(dashboard_kpis_enabled=True)
        self.login(self.reader)
        body = self.client.get(reverse("fees_dashboard_kpis")).json()
        self.assertIs(body["enabled"], True)
        self.assertIn("billed_this_year", body["kpis"])
        self.assertTrue(body["selected"])

    def test_payees_json_for_an_editor(self):
        self.login(self.editor)
        url = reverse("fees_payment_payees") + "?matters=%d" % self.seed["matter_1"].pk
        names = [row["payee"] for row in self.client.get(url).json()["payees"]]
        self.assertIn("Alpha payer", names)


class ExportContentTests(SeededViewsBase):
    def test_exports_do_not_write(self):
        from fees.models import Allocation, FeesSettings, Memo

        def snapshot():
            version = FeesSettings.objects.filter(profile=self.profile).values_list("data_version", flat=True).first()
            return (
                version,
                Memo.objects.filter(profile=self.profile).count(),
                Payment.objects.filter(profile=self.profile).count(),
                Allocation.objects.filter(profile=self.profile).count(),
            )

        before = snapshot()
        self.login(self.editor)
        for rows in RouteTests.routes(self).values():
            for name, kwargs, query in rows:
                self.client.get(reverse(name, kwargs=kwargs) + query)
        self.assertEqual(snapshot(), before)

    def test_no_download_carries_payment_details(self):
        self.login(self.reader)
        for name, kwargs, query in RouteTests.routes(self)["files"]:
            response = self.client.get(reverse(name, kwargs=kwargs) + query)
            self.assertNotIn(xs.PAYMENT_DETAILS_SENTINEL.encode(), self.body(response), name)

    def test_memo_word_download_has_the_file_name_and_type(self):
        self.login(self.reader)
        response = self.client.get(reverse("fees_memo_word", kwargs={"memo_id": self.seed["memo_a"].pk}))
        self.assertEqual(response.status_code, 200)
        self.assertIn("wordprocessingml", response["Content-Type"])
        self.assertIn(".docx", response["Content-Disposition"])
        self.assertEqual(self.body(response)[:2], b"PK")

    def test_outstanding_summary_export_name_has_the_em_dash_percent_encoded(self):
        self.login(self.reader)
        response = self.client.get(reverse("fees_outstanding_summary_export"))
        self.assertIn("%E2%80%94", response["Content-Disposition"])

    def test_backup_download_is_a_workbook(self):
        self.login(self.editor)
        response = self.client.get(reverse("fees_backup_download"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.body(response)[:2], b"PK")
        self.assertIn(".xlsx", response["Content-Disposition"])


class ErrorMappingTests(SeededViewsBase):
    def test_html_error_is_a_message_and_a_redirect(self):
        empty = Profile.objects.create(program=KEY_FEES, name="Empty-Exports")
        user = make_user("empty-exports", empty, ROLE_READER)
        self.login(user)
        response = self.client.get(reverse("fees_memos_export"))
        self.assertRedirects(response, reverse("fees_dashboard"), fetch_redirect_response=False)
        texts = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("nothing to export" in t.lower() for t in texts), texts)

    def test_html_error_goes_back_to_the_page_the_user_came_from(self):
        empty = Profile.objects.create(program=KEY_FEES, name="Empty-Back")
        user = make_user("empty-back", empty, ROLE_READER)
        self.login(user)
        back = reverse("fees_memos")
        response = self.client.get(reverse("fees_memos_export"), HTTP_REFERER="http://testserver" + back)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "http://testserver" + back)

    def test_missing_template_is_a_message_not_a_crash(self):
        empty = Profile.objects.create(program=KEY_FEES, name="No-Template")
        user = make_user("no-template", empty, ROLE_READER)
        self.login(user)
        response = self.client.get(reverse("fees_template_download"))
        self.assertEqual(response.status_code, 302)

    def test_busy_is_a_503_page(self):
        self.login(self.editor)
        with mock.patch("fees.views_backup.heavy_operation", side_effect=Busy()):
            response = self.client.get(reverse("fees_backup_download"))
        self.assertEqual(response.status_code, 503)
        self.assertTemplateUsed(response, "fees/busy.html")

    def test_busy_on_the_annual_export_is_a_503_page(self):
        self.login(self.reader)
        with mock.patch("fees.views_statistics.heavy_operation", side_effect=Busy()):
            response = self.client.get(reverse("fees_statistics_annual_export") + "?fy=2026-27")
        self.assertEqual(response.status_code, 503)
        self.assertTemplateUsed(response, "fees/busy.html")


class ProgramLabelTests(SeededViewsBase):
    def test_fees_pages_are_labelled_with_the_fees_name(self):
        self.login(self.reader)
        response = self.client.get(reverse("fees_memos"))
        self.assertContains(response, "<title>Memos - Fee Register</title>", html=False)


class SourceGuardTests(SimpleTestCase):
    """Views stay thin: no touch, no fee arithmetic, no em dash, no csrf_exempt."""

    def sources(self):
        root = Path(__file__).resolve().parent.parent
        names = [p for p in root.glob("views_*.py")] + [root / "decorators.py", root / "pages.py", root / "forms.py"]
        return [(p.name, p.read_text(encoding="utf-8")) for p in names]

    def test_views_never_touch(self):
        for name, text in self.sources():
            self.assertIsNone(re.search(r"\btouch\(", text), name)

    def test_no_line_fee_arithmetic_in_views_or_templates(self):
        root = Path(__file__).resolve().parent.parent
        files = self.sources() + [(p.name, p.read_text(encoding="utf-8")) for p in (root.parent / "templates" / "fees").glob("*.html")]
        pattern = re.compile(r"num_appearances\s*\*\s*fees_per_appearance|num_conferences\s*\*\s*fees_per_conference")
        for name, text in files:
            self.assertIsNone(pattern.search(text), name)

    def test_no_em_dash_and_no_csrf_exempt(self):
        root = Path(__file__).resolve().parent.parent
        files = self.sources() + [(p.name, p.read_text(encoding="utf-8")) for p in (root.parent / "templates" / "fees").glob("*.html")]
        for name, text in files:
            self.assertNotIn(chr(0x2014), text, name)
            self.assertNotIn("csrf_exempt", text, name)
