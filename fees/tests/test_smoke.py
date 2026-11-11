"""End-to-end smoke test (T9.1), ported from the manual list in ``reference/PROJECT_STATUS.md``.

The reference list: add a firm, add a group, create a matter, create a memo, record a payment, upload a Word
template and export the memo to Word. This module walks that path through the real views with the test
client, then goes on to the rest of the readiness list: statistics, search, the Excel export of every
workbook, a restore of an exported workbook, the Reader role and a second profile that must see none of it.

The step helpers (``make_setup``, ``new_memo``, ``pay``) come from ``test_flows``; this module only adds the
whole-path walk and the checks that sit across several screens.
"""
import io
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from django.urls import reverse

from accounts.models import ROLE_EDITOR, ROLE_READER, Profile, ProfileMembership
from accounts.suite import KEY_FEES
from fees.models import Firm, Group, Matter, Memo, Payment
from fees.services import word_template
from fees.services.excel_restore import RESTORE_CONFIRMATION
from fees.tests import docx_support as ds
from fees.tests import test_flows
from fees.tests import xlsx_support as xs

User = get_user_model()
PASSWORD = test_flows.PASSWORD
FIXTURE = Path(__file__).parent / "fixtures" / "Template 2-11-2026 (short tags).docx"
XLSX_MAGIC = b"PK"


def _cells(sheets):
    """Every non-empty cell of a read workbook as text."""
    return [str(value) for rows in sheets.values() for row in rows for value in row if value is not None]


@override_settings(SECURE_SSL_REDIRECT=False)
class SmokeBase(test_flows.FlowBase):
    """The editor of the flow tests plus a filled register: one paid memo and one unpaid memo."""

    def setUp(self):
        super().setUp()
        self.make_setup()
        word_template.upload_template(self.profile, FIXTURE.name, FIXTURE.read_bytes())
        self.paid_memo = self.new_memo("2026-07-15")
        self.open_memo = self.new_memo("2026-08-10")
        self.pay(self.paid_memo, 14000, "2026-08-01")

    def other_client(self, name, profile, role, admin=False):
        user = User.objects.create_user(username=name, password=PASSWORD)
        user.is_superuser = admin
        user.save()
        ProfileMembership.objects.create(user=user, profile=profile, role=role)
        client = Client()
        client.force_login(user)
        return client

    def read_xlsx(self, response):
        data = self.body(response)
        self.assertEqual(data[:2], XLSX_MAGIC)
        return xs.read_workbook(io.BytesIO(data))


class PathWalkTests(test_flows.FlowBase):
    def test_the_reference_smoke_path_from_firm_to_word_export(self):
        # 1. Firms: add a firm. It gets its first group automatically.
        response = self.post("fees_firm_new", {"name": "Smoke Legal"})
        self.assertEqual(response.status_code, 302)
        firm = Firm.objects.get(profile=self.profile, name="Smoke Legal")
        self.assertContains(self.get("fees_firms"), "Smoke Legal")
        self.assertEqual(self.get("fees_firm_detail", {"firm_id": firm.pk}).status_code, 200)

        # 2. Add a group (a partner) to the firm.
        self.post("fees_group_add", {"name": "Smoke Partner"}, {"firm_id": firm.pk})
        self.assertContains(self.get("fees_firm_detail", {"firm_id": firm.pk}), "Smoke Partner")

        # 3. Create a matter under the firm and group.
        self.firm = firm
        self.group = Group.objects.get(firm=firm, name="Smoke Partner")
        self.post(
            "fees_matter_new",
            {
                "firm_id": str(firm.pk),
                "group_id": str(self.group.pk),
                "name": "Smoke Matter",
                "court_name": "High Court",
                "client": "Smoke Client",
            },
        )
        self.matter = Matter.objects.get(profile=self.profile, name="Smoke Matter")
        self.assertContains(self.get("fees_matter_detail", {"matter_id": self.matter.pk}), "Smoke Matter")

        # 4. New memo: the live totals preview, then save.
        preview = self.get(
            "fees_memo_preview_totals",
            query="?num_appearances=2&fees_per_appearance=5000&num_conferences=1&fees_per_conference=3000",
        )
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(self.get("fees_memo_new").status_code, 200)
        memo = self.new_memo("2026-07-15")
        self.assertEqual(memo.memo_number, "2026-27/1")
        self.assertContains(self.get("fees_memo_detail", {"memo_id": memo.pk}), memo.memo_number)
        self.assertEqual(self.detail(memo)["status"], "Unpaid")

        # 5. Payment: the status moves to Paid.
        self.pay(memo, 14000, "2026-08-01")
        self.assertEqual(self.detail(memo)["status"], "Paid")
        self.assertEqual(Payment.objects.filter(profile=self.profile).count(), 1)

        # 6. Upload the Word template, then export the memo to Word.
        upload = SimpleUploadedFile(FIXTURE.name, FIXTURE.read_bytes())
        response = self.client.post(reverse("fees_template_upload"), {"file": upload})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(word_template.get_template_info(self.profile) is not None)
        word = self.get("fees_memo_word", {"memo_id": memo.pk})
        self.assertEqual(word.status_code, 200)
        self.assertIn("wordprocessingml", word["Content-Type"])
        parts = ds.read_zip(self.body(word))
        self.assertIn(memo.memo_number.encode(), parts["word/document.xml"])


class StatisticsAndSearchSmokeTests(SmokeBase):
    def test_statistics_is_on_and_serves_its_pages_and_data(self):
        self.assertEqual(self.get("fees_statistics", query="?granularity=month&fy=2026-27").status_code, 200)
        data = self.get("fees_statistics_data", query="?granularity=month&fy=2026-27")
        self.assertEqual(data.status_code, 200)
        self.assertTrue(data.json()["ok"])
        explore = self.get("fees_statistics_explore", query="?measure=billed&row_dim=financialYear&col_dim=none")
        self.assertEqual(explore.status_code, 200)
        self.assertTrue(explore.json()["ok"])
        self.assertEqual(self.get("fees_statistics_year_end", query="?fy=2026-27").status_code, 200)
        self.assertEqual(self.get("fees_dashboard").status_code, 200)

    def test_search_finds_the_firm_the_matter_and_the_memo(self):
        found = self.get("fees_search", query="?q=acme").json()
        self.assertTrue(found["ok"])
        self.assertIn(("firm", self.firm.pk), [(r["kind"], r["id"]) for r in found["results"]])
        by_matter = self.get("fees_search", query="?q=varian").json()
        self.assertIn(("matter", self.matter.pk), [(r["kind"], r["id"]) for r in by_matter["results"]])
        page = self.get("fees_search_page", query="?q=acme")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Acme Legal")
        self.assertEqual(self.get("fees_search", query="?q=zzzz-no-such-thing").json()["results"], [])


class ExcelExportSmokeTests(SmokeBase):
    def assert_workbook(self, name, kwargs=None, query=""):
        response = self.get(name, kwargs, query)
        self.assertEqual(response.status_code, 200, name)
        self.assertIn("spreadsheetml", response["Content-Type"], name)
        return self.read_xlsx(response)

    def test_every_workbook_exports(self):
        matter_ids = {"matter_id": self.matter.pk}
        firm_ids = {"firm_id": self.firm.pk}
        memos_book = self.assert_workbook("fees_memos_export")
        self.assertIn(self.paid_memo.memo_number, _cells(memos_book))
        self.assertIn(self.open_memo.memo_number, _cells(memos_book))
        self.assert_workbook("fees_memo_statement", {"memo_id": self.paid_memo.pk})
        self.assert_workbook("fees_firm_statement_export", firm_ids)
        self.assert_workbook("fees_firm_ledger_export", firm_ids)
        self.assert_workbook("fees_matter_statement_export", matter_ids)
        self.assert_workbook("fees_matter_ledger_export", matter_ids)
        ledger_book = self.assert_workbook("fees_firm_ledger_export", firm_ids)
        self.assertTrue(any(str(cell).startswith("Totals (") for cell in _cells(ledger_book)))
        group_query = "?group=%d" % self.matter.group_id
        self.assert_workbook("fees_firm_ledger_export", firm_ids, group_query)
        self.assert_workbook("fees_firm_statement_export", firm_ids, group_query)
        feebook = self.assert_workbook("fees_feebook_export")
        self.assertIn(self.paid_memo.memo_number, _cells(feebook))
        outstanding = self.assert_workbook("fees_outstanding_export")
        self.assertIn(self.open_memo.memo_number, _cells(outstanding))
        self.assertNotIn(self.paid_memo.memo_number, _cells(outstanding))
        self.assert_workbook("fees_outstanding_summary_export")
        self.assert_workbook("fees_statistics_export", query="?granularity=month&fy=2026-27")
        self.assert_workbook("fees_statistics_annual_export", query="?fy=2026-27")
        self.assertEqual(self.get("fees_statistics_tax_summary", query="?fy=2026-27").status_code, 200)

    def test_the_full_backup_downloads_as_a_workbook(self):
        sheets = self.assert_workbook("fees_backup_download")
        self.assertIn(self.paid_memo.memo_number, _cells(sheets))


class RestoreSmokeTests(SmokeBase):
    def test_an_exported_workbook_restores_into_a_fresh_profile(self):
        workbook = self.body(self.get("fees_backup_download"))
        self.assertEqual(workbook[:2], XLSX_MAGIC)

        fresh = Profile.objects.create(program=KEY_FEES, name="Smoke-Fresh")
        client = self.other_client("admin-fresh", fresh, ROLE_EDITOR, admin=True)
        self.assertFalse(Memo.objects.filter(profile=fresh).exists())

        upload = SimpleUploadedFile("backup.xlsx", workbook)
        preview = client.post(reverse("fees_backup_restore"), {"action": "preview", "file": upload})
        self.assertEqual(preview.status_code, 200)

        with mock.patch("fees.services.excel_restore._default_backup", return_value=None):
            response = client.post(
                reverse("fees_backup_restore"),
                {
                    "action": "restore",
                    "file": SimpleUploadedFile("backup.xlsx", workbook),
                    "confirmation": RESTORE_CONFIRMATION,
                },
            )
        self.assertRedirects(response, reverse("fees_backup_restored"), fetch_redirect_response=False)
        self.assertEqual(client.get(reverse("fees_backup_restored")).status_code, 200)

        numbers = sorted(Memo.objects.filter(profile=fresh).values_list("memo_number", flat=True))
        self.assertEqual(numbers, sorted([self.paid_memo.memo_number, self.open_memo.memo_number]))
        self.assertEqual(Firm.objects.filter(profile=fresh).count(), 1)
        self.assertEqual(Payment.objects.filter(profile=fresh).count(), 1)
        # The source profile is untouched by a restore into another one.
        self.assertEqual(Memo.objects.filter(profile=self.profile).count(), 2)

    def test_the_desktop_backup_fixture_restores_to_an_empty_register(self):
        self.make_admin()
        fixture = Path(__file__).parent / "fixtures" / "fee_register_empty_reset_backup.xlsx"
        with mock.patch("fees.services.excel_restore._default_backup", return_value=None):
            response = self.post(
                "fees_backup_restore",
                {
                    "action": "restore",
                    "file": SimpleUploadedFile("desktop.xlsx", fixture.read_bytes()),
                    "confirmation": RESTORE_CONFIRMATION,
                },
            )
        self.assertRedirects(response, reverse("fees_backup_restored"), fetch_redirect_response=False)
        self.assertFalse(Memo.objects.filter(profile=self.profile).exists())
        self.assertFalse(Firm.objects.filter(profile=self.profile).exists())


class ReaderSmokeTests(SmokeBase):
    def setUp(self):
        super().setUp()
        self.reader = self.other_client("reader-smoke", self.profile, ROLE_READER)

    def test_a_reader_reads_and_exports_but_cannot_write(self):
        memo_id = {"memo_id": self.paid_memo.pk}
        for name, kwargs in (
            ("fees_memos", {}),
            ("fees_memo_detail", memo_id),
            ("fees_firms", {}),
            ("fees_feebook", {}),
            ("fees_outstanding", {}),
            ("fees_statistics", {}),
            ("fees_search_page", {}),
        ):
            self.assertEqual(self.reader.get(reverse(name, kwargs=kwargs)).status_code, 200, name)
        # Exports are reads.
        word = self.reader.get(reverse("fees_memo_word", kwargs=memo_id))
        self.assertEqual(word.status_code, 200)
        self.assertEqual(self.reader.get(reverse("fees_memos_export")).status_code, 200)
        # Writes and the editor-only screens are refused.
        before = Firm.objects.filter(profile=self.profile).count()
        self.assertEqual(self.reader.post(reverse("fees_firm_new"), {"name": "Reader Firm"}).status_code, 403)
        self.assertEqual(Firm.objects.filter(profile=self.profile).count(), before)
        self.assertEqual(self.reader.post(reverse("fees_memo_new"), self.memo_data("2026-09-01")).status_code, 403)
        self.assertEqual(self.reader.post(reverse("fees_memo_delete", kwargs=memo_id), {"confirm": "1"}).status_code, 403)
        self.assertTrue(Memo.objects.filter(pk=self.paid_memo.pk).exists())
        self.assertEqual(self.reader.post(reverse("fees_payment_new"), {"amount": "1"}).status_code, 403)
        self.assertEqual(self.reader.get(reverse("fees_backup")).status_code, 403)
        for name in ("fees_backup_restore", "fees_backup_clear", "fees_import", "fees_import_inspect"):
            self.assertEqual(self.reader.get(reverse(name)).status_code, 403, name)
        self.assertEqual(self.reader.get(reverse("fees_backup_download")).status_code, 403)


class SecondProfileSmokeTests(SmokeBase):
    def setUp(self):
        super().setUp()
        self.other_profile = Profile.objects.create(program=KEY_FEES, name="Smoke-Other")
        self.other = self.other_client("editor-other", self.other_profile, ROLE_EDITOR)

    def test_the_second_profile_sees_nothing_of_the_first(self):
        self.assertNotContains(self.other.get(reverse("fees_firms")), "Acme Legal")
        self.assertNotContains(self.other.get(reverse("fees_memos")), self.paid_memo.memo_number)
        self.assertEqual(self.other.get(reverse("fees_search"), {"q": "acme"}).json()["results"], [])
        self.assertNotContains(self.other.get(reverse("fees_feebook")), self.paid_memo.memo_number)

    def test_the_second_profile_cannot_open_the_first_ones_records(self):
        for name, kwargs in (
            ("fees_memo_detail", {"memo_id": self.paid_memo.pk}),
            ("fees_memo_word", {"memo_id": self.paid_memo.pk}),
            ("fees_memo_statement", {"memo_id": self.paid_memo.pk}),
            ("fees_firm_detail", {"firm_id": self.firm.pk}),
            ("fees_matter_detail", {"matter_id": self.matter.pk}),
            ("fees_matter_ledger_export", {"matter_id": self.matter.pk}),
        ):
            self.assertEqual(self.other.get(reverse(name, kwargs=kwargs)).status_code, 404, name)

    def test_the_second_profile_writes_stay_in_its_own_profile(self):
        response = self.other.post(reverse("fees_firm_new"), {"name": "Other Legal"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Firm.objects.filter(profile=self.other_profile, name="Other Legal").exists())
        self.assertFalse(Firm.objects.filter(profile=self.profile, name="Other Legal").exists())
        self.assertEqual(Memo.objects.filter(profile=self.profile).count(), 2)
