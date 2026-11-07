"""End-to-end flows through the web layer (T7.5), ported from the reference ``flows.test.ts``.

Every step goes through ``self.client`` (form posts and page loads), the way a user would: firm, group, matter,
memo, payment, outstanding, ledger, Word export, archive, a frozen memo and a backup round trip.
"""
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import ROLE_EDITOR, Profile, ProfileMembership
from accounts.suite import KEY_FEES
from fees.models import Allocation, Firm, Group, Matter, Memo, Payment
from fees.services import memos, word_template
from fees.services.excel_restore import RESTORE_CONFIRMATION
from fees.tests import docx_support as ds

User = get_user_model()
PASSWORD = "x-Test-Pw-1"


@override_settings(SECURE_SSL_REDIRECT=False)
class FlowBase(TestCase):
    def setUp(self):
        self.profile = Profile.objects.create(program=KEY_FEES, name="Flow-Fees")
        user = User.objects.create_user(username="editor-flow", password=PASSWORD)
        ProfileMembership.objects.create(user=user, profile=self.profile, role=ROLE_EDITOR)
        self.client.force_login(user)
        self.user = user

    def make_admin(self):
        """Restore, import and clear-all are Admin only: make the flow user the suite Admin."""
        self.user.is_superuser = True
        self.user.save()

    def post(self, name, data=None, kwargs=None):
        return self.client.post(reverse(name, kwargs=kwargs or {}), data or {})

    def get(self, name, kwargs=None, query=""):
        return self.client.get(reverse(name, kwargs=kwargs or {}) + query)

    def body(self, response):
        if getattr(response, "streaming", False):
            return b"".join(response.streaming_content)
        return response.content

    def make_setup(self):
        """A firm, its first group and a matter, all created through the forms."""
        self.post("fees_firm_new", {"name": "Acme Legal"})
        self.firm = Firm.objects.get(profile=self.profile, name="Acme Legal")
        self.group = Group.objects.get(firm=self.firm)
        self.post("fees_group_add", {"name": "Senior Partner"}, {"firm_id": self.firm.pk})
        self.assertTrue(Group.objects.filter(firm=self.firm, name="Senior Partner").exists())
        self.post(
            "fees_matter_new",
            {
                "firm_id": str(self.firm.pk),
                "group_id": str(self.group.pk),
                "name": "Varian Arbitration",
                "court_name": "Original Cause Title",
                "client": "Original Client",
            },
        )
        self.matter = Matter.objects.get(profile=self.profile, name="Varian Arbitration")

    def memo_data(self, date, **over):
        data = {
            "matter_id": str(self.matter.pk),
            "date": date,
            "addressee_line1": "Acme Legal",
            "num_appearances": "2",
            "fees_per_appearance": "5000",
            "num_conferences": "1",
            "fees_per_conference": "3000",
            "fees_misc_drafting": "1000",
            "action": "save",
        }
        data.update(over)
        return data

    def new_memo(self, date, **over):
        """Posts the memo form and returns the saved ``Memo`` (total 14000 with the default fees)."""
        before = set(Memo.objects.filter(profile=self.profile).values_list("pk", flat=True))
        response = self.post("fees_memo_new", self.memo_data(date, **over))
        self.assertEqual(response.status_code, 302)
        created = Memo.objects.filter(profile=self.profile).exclude(pk__in=before)
        self.assertEqual(created.count(), 1)
        return created.get()

    def pay(self, memo, amount, date):
        response = self.post(
            "fees_payment_new",
            {
                "amount": str(amount),
                "tds_rate": "0",
                "date_of_payment": date,
                "payee": "Client",
                "alloc_memo_0": memo.memo_number,
            },
        )
        self.assertEqual(response.status_code, 302)

    def detail(self, memo):
        return memos.get_memo(self.profile, memo.pk)


class NumberingFlowTests(FlowBase):
    def test_numbers_increment_within_a_year_and_reset_at_the_next(self):
        self.make_setup()
        a = self.new_memo("2026-05-01")
        b = self.new_memo("2026-12-31")
        c = self.new_memo("2027-03-31")
        d = self.new_memo("2027-04-01")
        self.assertEqual(a.memo_number, "2026-27/1")
        self.assertEqual(b.memo_number, "2026-27/2")
        self.assertEqual(c.memo_number, "2026-27/3")
        self.assertEqual(d.memo_number, "2027-28/1")

    def test_deleting_a_memo_never_reuses_its_number(self):
        self.make_setup()
        first = self.new_memo("2026-05-01")
        self.new_memo("2026-06-01")
        response = self.post("fees_memo_delete", {"confirm": "1"}, {"memo_id": first.pk})
        self.assertRedirects(response, reverse("fees_memos"), fetch_redirect_response=False)
        self.assertFalse(Memo.objects.filter(pk=first.pk).exists())
        third = self.new_memo("2026-07-01")
        self.assertEqual(third.memo_number, "2026-27/3")

    def test_the_memo_list_shows_the_new_numbers(self):
        self.make_setup()
        self.new_memo("2026-05-01")
        self.assertContains(self.get("fees_memos", query="?fy="), "2026-27/1")


class PaymentFlowTests(FlowBase):
    def test_partial_then_full_payment_marks_the_memo_paid(self):
        self.make_setup()
        memo = self.new_memo("2026-07-15")
        self.assertEqual(memo.total_fees, Decimal("14000.00"))
        self.assertEqual(self.detail(memo)["status"], "Unpaid")
        self.assertContains(self.get("fees_outstanding_detail"), memo.memo_number)

        self.pay(memo, 4000, "2026-08-01")
        part = self.detail(memo)
        self.assertEqual(part["status"], "Unpaid")
        self.assertEqual(Decimal(str(part["amount_paid"])), Decimal("4000"))
        self.assertContains(self.get("fees_outstanding_detail"), memo.memo_number)

        self.pay(memo, 10000, "2026-09-01")
        paid = self.detail(memo)
        self.assertEqual(paid["status"], "Paid")
        self.assertEqual(str(paid["date_of_last_payment"]), "2026-09-01")
        self.assertEqual(Decimal(str(paid["amount_paid"])), Decimal("14000"))

        # Two separate payments, each allocated to this one memo, so both feebook rows are Single.
        self.assertEqual(Payment.objects.filter(profile=self.profile).count(), 2)
        self.assertEqual(Allocation.objects.filter(memo=memo).count(), 2)
        feebook = self.get("fees_feebook", query="?fy=")
        self.assertContains(feebook, memo.memo_number)
        self.assertContains(feebook, "Single")
        self.assertNotContains(feebook, "Split")

        # A paid memo is no longer outstanding.
        self.assertNotContains(self.get("fees_outstanding_detail"), memo.memo_number)

    def test_the_ledger_balance_returns_to_zero_when_the_memo_is_paid(self):
        self.make_setup()
        memo = self.new_memo("2026-07-15")
        ledger = self.get("fees_matter_ledger", {"matter_id": self.matter.pk})
        self.assertContains(ledger, "Memo %s" % memo.memo_number)
        self.assertEqual(Decimal(str(ledger.context["rows"][-1]["balance"])), Decimal("14000"))

        self.pay(memo, 14000, "2026-08-01")
        rows = self.get("fees_matter_ledger", {"matter_id": self.matter.pk}).context["rows"]
        self.assertEqual(Decimal(str(rows[-1]["balance"])), Decimal("0"))
        firm_rows = self.get("fees_firm_ledger", {"firm_id": self.firm.pk}).context["rows"]
        self.assertEqual(Decimal(str(firm_rows[-1]["balance"])), Decimal("0"))

    def test_the_word_export_carries_the_memo_number(self):
        self.make_setup()
        template = ds.build_docx(ds.document_xml(ds.paragraph("Memo {{LINE_2_MEMO_NUMBER}}")))
        word_template.upload_template(self.profile, "flow.docx", template)
        memo = self.new_memo("2026-07-15")
        response = self.get("fees_memo_word", {"memo_id": memo.pk})
        self.assertEqual(response.status_code, 200)
        self.assertIn("wordprocessingml", response["Content-Type"])
        parts = ds.read_zip(self.body(response))
        self.assertIn(memo.memo_number.encode(), parts["word/document.xml"])

    def test_a_split_payment_is_one_payment_over_two_memos(self):
        self.make_setup()
        first = self.new_memo("2026-07-15")
        second = self.new_memo("2026-07-16")
        response = self.post(
            "fees_payment_new",
            {
                "amount": "500",
                "tds_rate": "0",
                "date_of_payment": "2026-08-01",
                "payee": "Client",
                "alloc_memo_0": first.memo_number,
                "alloc_amount_0": "200",
                "alloc_memo_1": second.memo_number,
                "alloc_amount_1": "300",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Payment.objects.filter(profile=self.profile).count(), 1)
        self.assertEqual(Decimal(str(self.detail(first)["amount_paid"])), Decimal("200"))
        self.assertEqual(Decimal(str(self.detail(second)["amount_paid"])), Decimal("300"))
        self.assertContains(self.get("fees_feebook", query="?fy="), "Multiple")


class LifecycleFlowTests(FlowBase):
    def test_archive_blocks_memo_creation_and_unarchive_restores_it(self):
        self.make_setup()
        self.post("fees_matter_archive", {"archive": "1"}, {"matter_id": self.matter.pk})
        self.matter.refresh_from_db()
        self.assertTrue(self.matter.is_archived)

        response = self.post("fees_memo_new", self.memo_data("2026-07-15"))
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "Active Matters", status_code=409)
        self.assertFalse(Memo.objects.filter(profile=self.profile).exists())

        self.post("fees_matter_archive", {"archive": "0"}, {"matter_id": self.matter.pk})
        memo = self.new_memo("2026-07-15")
        self.assertEqual(memo.memo_number, "2026-27/1")

    def test_firm_status_is_independent_of_its_matters(self):
        self.make_setup()
        self.assertEqual(self.firm.status, "active")
        self.post("fees_matter_archive", {"archive": "1"}, {"matter_id": self.matter.pk})
        self.firm.refresh_from_db()
        self.assertEqual(self.firm.status, "active")

    def test_a_saved_memo_is_frozen_against_later_matter_edits(self):
        self.make_setup()
        memo = self.new_memo("2026-07-15", court_name="Original Cause Title", client="Original Client")
        self.assertEqual(self.detail(memo)["court_name"], "Original Cause Title")

        response = self.post(
            "fees_matter_edit",
            {
                "firm_id": str(self.firm.pk),
                "group_id": str(self.group.pk),
                "name": "Varian Arbitration",
                "court_name": "Changed Cause Title",
                "client": "Changed Client",
            },
            {"matter_id": self.matter.pk},
        )
        self.assertEqual(response.status_code, 302)
        self.matter.refresh_from_db()
        self.assertEqual(self.matter.court_name, "Changed Cause Title")

        after = self.detail(memo)
        self.assertEqual(after["court_name"], "Original Cause Title")
        self.assertEqual(after["client"], "Original Client")


class BackupRoundTripFlowTests(FlowBase):
    def test_backup_clear_and_restore_bring_everything_back(self):
        self.make_admin()
        self.make_setup()
        first = self.new_memo("2026-07-15")
        self.new_memo("2026-08-15")
        self.pay(first, 5000, "2026-09-01")

        numbers_before = sorted(Memo.objects.filter(profile=self.profile).values_list("memo_number", flat=True))
        paid_before = Decimal(str(self.detail(first)["amount_paid"]))
        firms_before = Firm.objects.filter(profile=self.profile).count()

        download = self.get("fees_backup_download")
        self.assertEqual(download.status_code, 200)
        workbook = self.body(download)
        self.assertEqual(workbook[:2], b"PK")

        with mock.patch("fees.services.clear_all._default_backup", return_value=None):
            self.post("fees_backup_clear", {"confirmation": self.profile.name})
        self.assertFalse(Memo.objects.filter(profile=self.profile).exists())

        with mock.patch("fees.services.excel_restore._default_backup", return_value=None):
            response = self.post(
                "fees_backup_restore",
                {
                    "action": "restore",
                    "file": SimpleUploadedFile("backup.xlsx", workbook),
                    "confirmation": RESTORE_CONFIRMATION,
                },
            )
        self.assertRedirects(response, reverse("fees_backup_restored"), fetch_redirect_response=False)
        self.assertEqual(self.get("fees_backup_restored").status_code, 200)

        numbers_after = sorted(Memo.objects.filter(profile=self.profile).values_list("memo_number", flat=True))
        self.assertEqual(numbers_after, numbers_before)
        self.assertEqual(Firm.objects.filter(profile=self.profile).count(), firms_before)
        restored = Memo.objects.get(profile=self.profile, memo_number=first.memo_number)
        self.assertEqual(Decimal(str(self.detail(restored)["amount_paid"])), paid_before)

        # Numbering continues without reuse after the restore.
        self.matter = Matter.objects.get(profile=self.profile, name="Varian Arbitration")
        nxt = self.new_memo("2026-10-01")
        self.assertEqual(nxt.memo_number, "2026-27/3")
