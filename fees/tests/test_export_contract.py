"""Cross-export contract tests (T5.5 and T5.6).

* Readers may use every export (R-EX-6): a test-only view built with ``program_reader_required`` serves each
  export; a Reader gets 200, a user with no membership 403, an anonymous user is sent to login.
  The real export URLs use the same decorator and are covered in ``test_views_read.py``; this test-only view stays
  as an independent check of the decorator itself.
* Exports are pure reads: no ``data_version`` bump and no row changes.
* ``payment_details`` never appears in any export (sentinel over the bytes of every export), with the full
  backup as a positive control that the sentinel is really in the data.
* RFC 5987 ``Content-Disposition`` helper cases.
* Memory gates (``memory`` tag): Excel export 12 MB, annual summary 20 MB, on the planning dataset. The Word
  2 MB gate is in ``test_word_export.py`` (``WordMemoryTests``).
"""

import io
import zipfile

from django.contrib.auth import get_user_model
from django.http import FileResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, tag

from accounts.models import ROLE_EDITOR, ROLE_READER, Profile, ProfileMembership
from accounts.permissions import program_reader_required
from accounts.profiles import get_membership_for
from accounts.suite import KEY_FEES
from fees.exports import tax_summary, xlsx
from fees.exports.filenames import content_disposition
from fees.exports.placeholders import TEXT_TAGS
from fees.models import Allocation, FeesSettings, Memo, Payment
from fees.services import excel_backup, word_template
from fees.tests import docx_support as ds
from fees.tests import xlsx_support as xs
from fees.tests.datasets import build_planning_dataset
from fees.tests.memory import assert_peak_under

User = get_user_model()
FY = "2026-27"


def all_exports(profile, memo_id):
    """Every export as ``(label, file_name, file)``. Callers close the files."""
    out = []

    def add(label, result):
        out.append((label, result[0], result[1]))

    add("memos", xlsx.export_memos(profile))
    add("statement", xlsx.export_statement(profile))
    add("ledger", xlsx.export_ledger(profile))
    add("feebook", xlsx.export_feebook(profile))
    add("outstanding", xlsx.export_outstanding(profile))
    add("outstanding_by_firm", xlsx.export_outstanding_by_firm(profile))
    add("statistics", xlsx.export_statistics(profile, "month", FY))
    add("annual", xlsx.export_annual_summary(profile, FY))
    add("tax", tax_summary.export_tax_summary(profile, FY))
    add("word", word_template.render_memo_docx(profile, memo_id))
    return out


def all_bytes(fileobj):
    """Every byte a file carries: the file itself and, for a zip, each part uncompressed."""
    data = fileobj.read()
    chunks = [data]
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            chunks.extend(zf.read(name) for name in zf.namelist())
    return b"".join(chunks)


class SeededBase(TestCase):
    def setUp(self):
        self.profile = Profile.objects.create(program=KEY_FEES, name="Contract-Fees")
        self.seed = xs.seed_web_data(self.profile)
        everything = " ".join("{{%s}}" % name for name in sorted(TEXT_TAGS))
        template = ds.build_docx(ds.document_xml(ds.paragraph(everything)))
        word_template.upload_template(self.profile, "all-tags.docx", template)
        word_template.upload_signature(self.profile, "sig.png", "image/png", ds.png_bytes(80, 30))
        self.memo_id = self.seed["memo_a"].pk
        # The signature picture is embedded only for a memo that asks for it.
        Memo.objects.filter(pk=self.memo_id).update(include_signature=True)


class ReaderPermissionTests(SeededBase):
    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
        self.reader = User.objects.create_user(username="reader1", password="x-Reader-Pw-1")
        self.editor = User.objects.create_user(username="editor1", password="x-Editor-Pw-1")
        self.outsider = User.objects.create_user(username="outsider1", password="x-Outsider-Pw-1")
        ProfileMembership.objects.create(user=self.reader, profile=self.profile, role=ROLE_READER)
        ProfileMembership.objects.create(user=self.editor, profile=self.profile, role=ROLE_EDITOR)

        @program_reader_required(KEY_FEES)
        def export_view(request, label):
            profile = get_membership_for(request.user, KEY_FEES).profile
            for name, file_name, fileobj in all_exports(profile, self.memo_id):
                if name == label:
                    response = FileResponse(fileobj, as_attachment=False)
                    response["Content-Disposition"] = content_disposition(file_name)
                    return response
            raise AssertionError(label)

        self.view = export_view

    def get(self, user, label):
        request = self.factory.get("/fees/export/")
        request.user = user
        return self.view(request, label)

    def test_reader_and_editor_get_every_export(self):
        labels = []
        for name, _file_name, fileobj in all_exports(self.profile, self.memo_id):
            fileobj.close()
            labels.append(name)
        self.assertEqual(len(labels), 10)
        for user in (self.reader, self.editor):
            for label in labels:
                response = self.get(user, label)
                try:
                    self.assertEqual(response.status_code, 200, label)
                    self.assertIn("filename*=UTF-8''", response["Content-Disposition"])
                    self.assertTrue(b"".join(response.streaming_content))
                finally:
                    # Close the file only: response.close() sends request_finished, whose receiver
                    # close_old_connections would close the test database connection.
                    response.file_to_stream.close()

    def test_user_without_membership_gets_403(self):
        from django.core.exceptions import PermissionDenied

        with self.assertRaises(PermissionDenied):
            self.get(self.outsider, "memos")

    def test_anonymous_is_sent_to_login(self):
        from django.contrib.auth.models import AnonymousUser

        response = self.get(AnonymousUser(), "memos")
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_exports_do_not_write(self):
        def snapshot():
            version = FeesSettings.objects.filter(profile=self.profile).values_list("data_version", flat=True).first()
            return (
                version,
                Memo.objects.filter(profile=self.profile).count(),
                Payment.objects.filter(profile=self.profile).count(),
                Allocation.objects.filter(profile=self.profile).count(),
            )

        before = snapshot()
        for _label, _name, fileobj in all_exports(self.profile, self.memo_id):
            fileobj.close()
        self.assertEqual(snapshot(), before)


class PaymentDetailsSentinelTests(SeededBase):
    def test_sentinel_is_in_the_data(self):
        # Positive control: the full backup does carry payment_details (R-PAY-5).
        out = excel_backup.export_workbook(self.profile)
        with out:
            self.assertIn(xs.PAYMENT_DETAILS_SENTINEL.encode(), all_bytes(out))
        self.assertTrue(
            Payment.objects.filter(profile=self.profile, payment_details=xs.PAYMENT_DETAILS_SENTINEL).exists()
        )

    def test_no_export_contains_payment_details(self):
        checked = 0
        for label, _name, fileobj in all_exports(self.profile, self.memo_id):
            with fileobj:
                blob = all_bytes(fileobj)
            self.assertTrue(blob, label)
            self.assertNotIn(xs.PAYMENT_DETAILS_SENTINEL.encode(), blob, label)
            checked += 1
        self.assertEqual(checked, 10)

    def test_word_output_carries_memo_values_and_signature(self):
        # Guards the sentinel test above against passing because the Word file was empty.
        _name, fileobj = word_template.render_memo_docx(self.profile, self.memo_id)
        with fileobj:
            parts = ds.read_zip(fileobj)
        document = parts["word/document.xml"].decode()
        self.assertIn("Acme Legal", document)
        self.assertIn("A. B. Advocate", document)
        self.assertTrue([n for n in parts if n.startswith("word/media/")])


class FilenameHeaderTests(SimpleTestCase):
    def test_em_dash_is_percent_encoded_and_fallback_is_ascii(self):
        header = content_disposition(xlsx.OUTSTANDING_FIRM_SUMMARY_FILENAME)
        self.assertTrue(header.startswith("attachment; "))
        self.assertIn("filename*=UTF-8''Outstanding%20%E2%80%94%20Firm%20Summary.xlsx", header)
        self.assertIn('filename="Outstanding _ Firm Summary.xlsx"', header)
        self.assertTrue(header.isascii())

    def test_reserved_characters_are_encoded(self):
        header = content_disposition("a;b'c(d)e,f=g.xlsx")
        encoded = header.split("filename*=UTF-8''")[1]
        for char in ";'(),=":
            self.assertNotIn(char, encoded)
        self.assertIn("%3B", encoded)
        self.assertIn("%27", encoded)

    def test_line_breaks_cannot_inject_headers(self):
        header = content_disposition("a\r\nSet-Cookie: x.xlsx")
        self.assertNotIn("\r", header)
        self.assertNotIn("\n", header)
        self.assertIn("%0D%0A", header)

    def test_quote_and_backslash_cannot_break_the_fallback(self):
        header = content_disposition('a"b\\c.xlsx')
        fallback = header.split('filename="')[1].split('"; filename*')[0]
        self.assertNotIn('"', fallback)
        self.assertNotIn("\\", fallback)

    def test_plain_ascii_name_round_trips(self):
        header = content_disposition("Memos 2026-27.xlsx")
        self.assertIn('filename="Memos 2026-27.xlsx"', header)
        self.assertIn("filename*=UTF-8''Memos%202026-27.xlsx", header)


@tag("memory")
class ExportMemoryTests(TestCase):
    def planning_profile(self, name):
        profile = Profile.objects.create(program=KEY_FEES, name=name)
        build_planning_dataset(profile)
        return profile

    def test_memos_excel_export_peaks_under_12_mb(self):
        profile = self.planning_profile("mem-xlsx")
        with assert_peak_under(self, 12):
            _name, out = xlsx.export_memos(profile)
            size = out.seek(0, 2)
            out.close()
        self.assertGreater(size, 100000)

    def test_annual_summary_peaks_under_20_mb(self):
        profile = self.planning_profile("mem-annual")
        fy = Memo.objects.filter(profile=profile).order_by("-financial_year").values_list(
            "financial_year", flat=True
        ).first()
        with assert_peak_under(self, 20):
            _name, out = xlsx.export_annual_summary(profile, fy)
            size = out.seek(0, 2)
            out.close()
        self.assertGreater(size, 5000)
