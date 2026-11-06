"""Write views of the Fee Register (T7.2): a successful write per endpoint, CSRF, roles, validation, 404 scope.

Every POST is Editor only; a Reader gets 403, an anonymous user is sent to login, a user with no Fee Register
membership gets 403, another profile's object id is a 404, and a POST without the CSRF token is refused.
The suite backup that restore and clear take first is stubbed (``_default_backup``), as in the service tests.
"""
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import ROLE_EDITOR, ROLE_READER, Profile, ProfileMembership
from accounts.suite import KEY_FEES
from fees.exports.placeholders import TEXT_TAGS
from fees.models import (
    Allocation,
    BankAccount,
    FeesSettings,
    Firm,
    Group,
    Matter,
    Memo,
    PeriodAdjustment,
    SavedView,
    Payment,
    WordTemplate,
)
from fees.services import excel_backup, matters, memos, payments, word_template
from fees.services.excel_restore import RESTORE_CONFIRMATION
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
class WriteBase(TestCase):
    def setUp(self):
        self.profile = Profile.objects.create(program=KEY_FEES, name="Write-Fees")
        self.seed = xs.seed_web_data(self.profile)
        self.editor = make_user("editor-w", self.profile, ROLE_EDITOR)
        self.reader = make_user("reader-w", self.profile, ROLE_READER)
        self.outsider = make_user("outsider-w")
        self.other_profile = Profile.objects.create(program=KEY_FEES, name="Other-Write")
        self.other_seed = xs.seed_web_data(self.other_profile)
        xs.statistics_on(self.profile)
        xs.statistics_on(self.other_profile)
        self.client.force_login(self.editor)

    def post(self, name, data=None, kwargs=None, **extra):
        return self.client.post(reverse(name, kwargs=kwargs or {}), data or {}, **extra)

    def version(self, profile=None):
        profile = profile or self.profile
        return FeesSettings.objects.get(profile=profile).data_version

    def messages(self, response):
        return [str(m) for m in get_messages(response.wsgi_request)]

    def new_memo(self, **over):
        """An unpaid finalised memo with a total of 14000 (2 x 5000 + 3000 + 1000)."""
        return memos.create_memo(self.profile, xs.memo_input(self.seed["matter_1"].pk, **over))


class MemoWriteTests(WriteBase):
    def memo_post(self, **over):
        data = {
            "matter_id": str(self.seed["matter_1"].pk),
            "date": "2026-08-10",
            "addressee_line1": "Typed addressee",
            "num_appearances": "2",
            "fees_per_appearance": "1000",
            "action": "save",
        }
        data.update(over)
        return data

    def test_create_memo(self):
        before = self.version()
        response = self.post("fees_memo_new", self.memo_post())
        memo = Memo.objects.filter(profile=self.profile, addressee_line1="Typed addressee").get()
        self.assertRedirects(
            response, reverse("fees_memo_detail", kwargs={"memo_id": memo.pk}), fetch_redirect_response=False
        )
        self.assertFalse(memo.is_draft)
        self.assertTrue(memo.memo_number.startswith("2026-27/"))
        self.assertEqual(memo.total_fees, Decimal("2000.00"))
        self.assertGreater(self.version(), before)

    def test_create_draft_needs_no_date(self):
        response = self.post("fees_memo_new", self.memo_post(date="", action="draft"))
        self.assertEqual(response.status_code, 302)
        draft = Memo.objects.filter(profile=self.profile, addressee_line1="Typed addressee").get()
        self.assertTrue(draft.is_draft)
        self.assertIsNone(draft.memo_number)

    def test_missing_date_shows_the_form_again_with_what_was_typed(self):
        count = Memo.objects.filter(profile=self.profile).count()
        response = self.post("fees_memo_new", self.memo_post(date=""))
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "Missing or invalid required field", status_code=422)
        self.assertContains(response, 'value="Typed addressee"', status_code=422)
        self.assertEqual(Memo.objects.filter(profile=self.profile).count(), count)

    def test_bad_number_is_a_message_not_a_crash(self):
        response = self.post("fees_memo_new", self.memo_post(fees_per_appearance="abc"))
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "must be a number", status_code=422)

    def test_negative_count_and_huge_amount_are_refused(self):
        self.assertEqual(self.post("fees_memo_new", self.memo_post(num_appearances="-1")).status_code, 422)
        self.assertEqual(self.post("fees_memo_new", self.memo_post(fees_per_appearance="9" * 20)).status_code, 422)

    def test_too_long_text_is_refused(self):
        response = self.post("fees_memo_new", self.memo_post(addressee_line1="x" * 301))
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "at most 300 characters", status_code=422)

    def test_no_matter_chosen(self):
        response = self.post("fees_memo_new", self.memo_post(matter_id=""))
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "Choose a matter", status_code=422)

    def test_archived_matter_is_refused(self):
        matters.archive_matter(self.profile, self.seed["matter_1"].pk)
        response = self.post("fees_memo_new", self.memo_post())
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "Active Matters", status_code=409)

    def test_another_profiles_matter_is_a_404(self):
        response = self.post("fees_memo_new", self.memo_post(matter_id=str(self.other_seed["matter_1"].pk)))
        self.assertEqual(response.status_code, 404)

    def test_edit_memo_keeps_its_number_and_recomputes_the_total(self):
        memo = self.new_memo()
        number = memo.memo_number
        data = self.memo_post(num_appearances="3", fees_per_appearance="2000", num_conferences="0", fees_misc_drafting="0")
        response = self.post("fees_memo_edit", data, {"memo_id": memo.pk})
        self.assertEqual(response.status_code, 302)
        memo.refresh_from_db()
        self.assertEqual(memo.memo_number, number)
        self.assertEqual(memo.total_fees, Decimal("6000.00"))

    def test_edit_draft_with_save_numbers_it(self):
        draft = memos.save_draft(self.profile, {"matter_id": self.seed["matter_1"].pk, "date": "2026-08-02"})
        data = self.memo_post(date="2026-08-02", action="save")
        response = self.post("fees_memo_edit", data, {"memo_id": draft.pk})
        self.assertEqual(response.status_code, 302)
        draft.refresh_from_db()
        self.assertFalse(draft.is_draft)
        self.assertTrue(draft.memo_number.startswith("2026-27/"))

    def test_edit_draft_with_save_but_no_date_stays_a_draft(self):
        draft = memos.save_draft(self.profile, {"matter_id": self.seed["matter_1"].pk})
        response = self.post("fees_memo_edit", self.memo_post(date=""), {"memo_id": draft.pk})
        self.assertEqual(response.status_code, 422)
        draft.refresh_from_db()
        self.assertTrue(draft.is_draft)

    def test_edit_another_profiles_memo_is_a_404(self):
        response = self.post("fees_memo_edit", self.memo_post(), {"memo_id": self.other_seed["memo_a"].pk})
        self.assertEqual(response.status_code, 404)

    def test_based_on_creates_a_new_memo(self):
        source = self.seed["memo_a"]
        count = Memo.objects.filter(profile=self.profile).count()
        response = self.post("fees_memo_based_on", self.memo_post(addressee_line1="Based on typed"), {"memo_id": source.pk})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Memo.objects.filter(profile=self.profile).count(), count + 1)
        self.assertTrue(Memo.objects.filter(profile=self.profile, addressee_line1="Based on typed").exists())

    def test_delete_needs_the_tick(self):
        memo = self.new_memo()
        response = self.post("fees_memo_delete", {}, {"memo_id": memo.pk})
        self.assertRedirects(
            response, reverse("fees_memo_detail", kwargs={"memo_id": memo.pk}), fetch_redirect_response=False
        )
        self.assertTrue(Memo.objects.filter(pk=memo.pk).exists())

    def test_delete_memo(self):
        memo = self.new_memo()
        response = self.post("fees_memo_delete", {"confirm": "1"}, {"memo_id": memo.pk})
        self.assertRedirects(response, reverse("fees_memos"), fetch_redirect_response=False)
        self.assertFalse(Memo.objects.filter(pk=memo.pk).exists())

    def test_delete_another_profiles_memo_is_a_404(self):
        response = self.post("fees_memo_delete", {"confirm": "1"}, {"memo_id": self.other_seed["memo_a"].pk})
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Memo.objects.filter(pk=self.other_seed["memo_a"].pk).exists())

    def test_write_off_and_restore(self):
        memo = self.new_memo()
        self.post("fees_memo_write_off", {"written_off": "1"}, {"memo_id": memo.pk})
        memo.refresh_from_db()
        self.assertTrue(memo.written_off)
        self.post("fees_memo_write_off", {"written_off": "0"}, {"memo_id": memo.pk})
        memo.refresh_from_db()
        self.assertFalse(memo.written_off)

    def test_a_fully_paid_memo_cannot_be_written_off(self):
        memo = self.new_memo()
        payments.add_payment_to_memo(
            self.profile,
            memo.pk,
            {"amount": 14000, "tds_rate": 0, "auto_tds": False, "tds_amount": 0, "date_of_payment": "2026-08-01"},
        )
        response = self.post("fees_memo_write_off", {"written_off": "1"}, {"memo_id": memo.pk})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(any("fully paid" in m for m in self.messages(response)))
        memo.refresh_from_db()
        self.assertFalse(memo.written_off)

    def test_finalise_a_draft(self):
        draft = memos.save_draft(self.profile, {"matter_id": self.seed["matter_1"].pk, "date": "2026-08-03"})
        response = self.post("fees_memo_finalise", {}, {"memo_id": draft.pk})
        self.assertEqual(response.status_code, 302)
        draft.refresh_from_db()
        self.assertFalse(draft.is_draft)
        self.assertIsNotNone(draft.memo_number)

    def test_finalise_with_a_custom_number(self):
        draft = memos.save_draft(self.profile, {"matter_id": self.seed["matter_1"].pk, "date": "2026-08-03"})
        self.post("fees_memo_finalise", {"custom_memo_number": "SPECIAL-9"}, {"memo_id": draft.pk})
        draft.refresh_from_db()
        self.assertEqual(draft.memo_number, "SPECIAL-9")

    def test_finalise_without_a_date_is_a_message(self):
        draft = memos.save_draft(self.profile, {"matter_id": self.seed["matter_1"].pk})
        response = self.post("fees_memo_finalise", {}, {"memo_id": draft.pk})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(any("valid date" in m for m in self.messages(response)))
        draft.refresh_from_db()
        self.assertTrue(draft.is_draft)


class PaymentWriteTests(WriteBase):
    def payment_post(self, **over):
        data = {
            "amount": "900",
            "tds_rate": "10",
            "auto_tds": "1",
            "date_of_payment": "2026-09-01",
            "payee": "Typed payee",
            "payment_mode": "NEFT",
        }
        data.update(over)
        return data

    def test_unaccounted_payment(self):
        response = self.post("fees_payment_new", self.payment_post())
        self.assertRedirects(response, reverse("fees_feebook"), fetch_redirect_response=False)
        payment = Payment.objects.get(profile=self.profile, payee="Typed payee")
        self.assertFalse(Allocation.objects.filter(payment=payment).exists())
        self.assertEqual(payment.tds_amount, Decimal("100.00"))

    def test_payment_to_a_memo_by_number(self):
        memo = self.new_memo()
        data = self.payment_post(alloc_memo_0=memo.memo_number)
        response = self.post("fees_payment_new", data)
        self.assertRedirects(
            response, reverse("fees_memo_detail", kwargs={"memo_id": memo.pk}), fetch_redirect_response=False
        )
        allocation = Allocation.objects.get(memo=memo)
        self.assertEqual(allocation.amount, Decimal("900.00"))
        self.assertEqual(allocation.tds_amount, Decimal("100.00"))
        memo.refresh_from_db()
        self.assertEqual(memo.amount_paid, Decimal("1000.00"))

    def test_payment_split_over_two_memos(self):
        first, second = self.new_memo(), self.new_memo()
        data = self.payment_post(
            amount="500", auto_tds="", tds_rate="0",
            alloc_memo_0=first.memo_number, alloc_amount_0="200",
            alloc_memo_1=second.memo_number, alloc_amount_1="300",
        )
        response = self.post("fees_payment_new", data)
        self.assertRedirects(response, reverse("fees_feebook"), fetch_redirect_response=False)
        self.assertEqual(Allocation.objects.get(memo=first).amount, Decimal("200.00"))
        self.assertEqual(Allocation.objects.get(memo=second).amount, Decimal("300.00"))

    def test_zero_amount_is_refused(self):
        response = self.post("fees_payment_new", self.payment_post(amount="0"))
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "greater than 0", status_code=422)

    def test_missing_amount_and_bad_date(self):
        self.assertEqual(self.post("fees_payment_new", self.payment_post(amount="")).status_code, 422)
        self.assertEqual(self.post("fees_payment_new", self.payment_post(date_of_payment="2026-02-30")).status_code, 422)

    def test_unknown_memo_number_is_a_validation_error(self):
        response = self.post("fees_payment_new", self.payment_post(alloc_memo_0="NO-SUCH-NUMBER"))
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "no numbered memo", status_code=422)

    def test_another_profiles_memo_number_is_not_found_by_number(self):
        # Memo numbers repeat across profiles, so give the other profile's memo a number only it has.
        Memo.objects.filter(pk=self.other_seed["memo_c"].pk).update(memo_number="ONLY-OTHER-1")
        response = self.post("fees_payment_new", self.payment_post(alloc_memo_0="ONLY-OTHER-1"))
        self.assertEqual(response.status_code, 422)
        self.assertFalse(Allocation.objects.filter(memo_id=self.other_seed["memo_c"].pk).exists())

    def test_another_profiles_bank_account_is_refused(self):
        other_bank = self.other_seed["bank"]
        response = self.post("fees_payment_new", self.payment_post(bank_account_id=str(other_bank.pk)))
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "your own bank accounts", status_code=422)

    def test_own_bank_account_is_kept(self):
        bank = self.seed["bank"]
        self.post("fees_payment_new", self.payment_post(bank_account_id=str(bank.pk)))
        self.assertEqual(Payment.objects.get(profile=self.profile, payee="Typed payee").bank_account_id, bank.pk)

    def test_edit_payment(self):
        single = self.seed["single"]
        memo = self.seed["memo_a"]
        data = self.payment_post(
            amount="9000", payee="Edited payee", alloc_memo_0=memo.memo_number, date_of_payment="2026-08-01"
        )
        response = self.post("fees_payment_edit", data, {"payment_id": single["id"]})
        self.assertEqual(response.status_code, 302)
        payment = Payment.objects.get(pk=single["id"])
        self.assertEqual(payment.payee, "Edited payee")
        self.assertEqual(Allocation.objects.filter(payment=payment).count(), 1)

    def test_edit_with_every_row_blank_makes_the_payment_unaccounted(self):
        single = self.seed["single"]
        data = self.payment_post(amount="9000", date_of_payment="2026-08-01")
        self.post("fees_payment_edit", data, {"payment_id": single["id"]})
        self.assertFalse(Allocation.objects.filter(payment_id=single["id"]).exists())

    def test_edit_validation_error_shows_the_form_with_what_was_typed(self):
        single = self.seed["single"]
        response = self.post("fees_payment_edit", self.payment_post(amount="0", payee="Kept text"), {"payment_id": single["id"]})
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "Kept text", status_code=422)

    def test_edit_or_delete_another_profiles_payment_is_a_404(self):
        other_id = self.other_seed["single"]["id"]
        self.assertEqual(self.post("fees_payment_edit", self.payment_post(), {"payment_id": other_id}).status_code, 404)
        self.assertEqual(self.post("fees_payment_delete", {"confirm": "1"}, {"payment_id": other_id}).status_code, 404)
        self.assertEqual(self.post("fees_payment_assign", {"memo_number": "x"}, {"payment_id": other_id}).status_code, 404)
        self.assertTrue(Payment.objects.filter(pk=other_id).exists())

    def test_delete_payment(self):
        single = self.seed["single"]
        self.post("fees_payment_delete", {}, {"payment_id": single["id"]})
        self.assertTrue(Payment.objects.filter(pk=single["id"]).exists())
        response = self.post("fees_payment_delete", {"confirm": "1"}, {"payment_id": single["id"]})
        self.assertRedirects(response, reverse("fees_feebook"), fetch_redirect_response=False)
        self.assertFalse(Payment.objects.filter(pk=single["id"]).exists())

    def test_assign_an_unaccounted_payment_by_memo_number(self):
        target = self.seed["memo_b"]
        unaccounted = self.seed["unaccounted"]
        response = self.post("fees_payment_assign", {"memo_number": target.memo_number}, {"payment_id": unaccounted["id"]})
        self.assertRedirects(response, reverse("fees_feebook"), fetch_redirect_response=False)
        self.assertTrue(Allocation.objects.filter(payment_id=unaccounted["id"], memo=target).exists())

    def test_assign_with_an_unknown_number_changes_nothing(self):
        unaccounted = self.seed["unaccounted"]
        response = self.post("fees_payment_assign", {"memo_number": "NOPE"}, {"payment_id": unaccounted["id"]})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Allocation.objects.filter(payment_id=unaccounted["id"]).exists())


class FirmAndMatterWriteTests(WriteBase):
    def test_create_firm(self):
        response = self.post("fees_firm_new", {"name": "  Gamma LLP  "})
        firm = Firm.objects.get(profile=self.profile, name="Gamma LLP")
        self.assertRedirects(
            response, reverse("fees_firm_detail", kwargs={"firm_id": firm.pk}), fetch_redirect_response=False
        )
        self.assertTrue(Group.objects.filter(firm=firm).exists())

    def test_duplicate_firm_name_shows_the_form_again(self):
        response = self.post("fees_firm_new", {"name": "alpha & co"})
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "already exists", status_code=409)

    def test_blank_firm_name(self):
        self.assertEqual(self.post("fees_firm_new", {"name": "  "}).status_code, 422)

    def test_edit_firm(self):
        firm = self.seed["firm_b"]
        response = self.post("fees_firm_edit", {"name": "Beta Renamed", "notes": "A note"}, {"firm_id": firm.pk})
        self.assertEqual(response.status_code, 302)
        firm.refresh_from_db()
        self.assertEqual((firm.name, firm.notes), ("Beta Renamed", "A note"))

    def test_firm_status(self):
        firm = self.seed["firm_b"]
        self.post("fees_firm_status", {"status": "archived"}, {"firm_id": firm.pk})
        firm.refresh_from_db()
        self.assertEqual(firm.status, "archived")
        self.post("fees_firm_status", {"status": "active"}, {"firm_id": firm.pk})
        firm.refresh_from_db()
        self.assertEqual(firm.status, "active")

    def test_bad_firm_status_is_a_message(self):
        firm = self.seed["firm_b"]
        response = self.post("fees_firm_status", {"status": "gone"}, {"firm_id": firm.pk})
        self.assertEqual(response.status_code, 302)
        firm.refresh_from_db()
        self.assertEqual(firm.status, "active")

    def test_groups_add_rename_remove(self):
        firm = self.seed["firm_b"]
        self.post("fees_group_add", {"name": "Extra Group"}, {"firm_id": firm.pk})
        group = Group.objects.get(firm=firm, name="Extra Group")
        self.post("fees_group_rename", {"name": "Renamed Group"}, {"firm_id": firm.pk, "group_id": group.pk})
        group.refresh_from_db()
        self.assertEqual(group.name, "Renamed Group")
        self.post("fees_group_remove", {}, {"firm_id": firm.pk, "group_id": group.pk})
        self.assertFalse(Group.objects.filter(pk=group.pk).exists())

    def test_a_group_with_matters_cannot_be_removed(self):
        firm = self.seed["firm_b"]
        group = Group.objects.get(firm=firm)  # Matter Three sits in it
        response = self.post("fees_group_remove", {}, {"firm_id": firm.pk, "group_id": group.pk})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Group.objects.filter(pk=group.pk).exists())
        self.assertTrue(any("matters" in m for m in self.messages(response)))

    def test_a_group_of_another_firm_in_the_url_is_a_404(self):
        group_of_a = Group.objects.filter(firm=self.seed["firm_a"]).first()
        url_kwargs = {"firm_id": self.seed["firm_b"].pk, "group_id": group_of_a.pk}
        self.assertEqual(self.post("fees_group_rename", {"name": "X"}, url_kwargs).status_code, 404)
        self.assertEqual(self.post("fees_group_remove", {}, url_kwargs).status_code, 404)

    def test_other_profiles_firm_is_a_404(self):
        other = self.other_seed["firm_a"].pk
        self.assertEqual(self.post("fees_firm_edit", {"name": "Z"}, {"firm_id": other}).status_code, 404)
        self.assertEqual(self.post("fees_firm_status", {"status": "archived"}, {"firm_id": other}).status_code, 404)
        self.assertEqual(self.post("fees_group_add", {"name": "Z"}, {"firm_id": other}).status_code, 404)

    def matter_post(self, **over):
        firm = self.seed["firm_a"]
        data = {
            "firm_id": str(firm.pk),
            "group_id": str(Group.objects.filter(firm=firm).first().pk),
            "name": "Matter Four",
            "short_name": "M4",
            "addressee_line1": "To Four",
            "court_name": "Four Court",
        }
        data.update(over)
        return data

    def test_create_matter(self):
        response = self.post("fees_matter_new", self.matter_post())
        matter = Matter.objects.get(profile=self.profile, name="Matter Four")
        self.assertRedirects(
            response, reverse("fees_matter_detail", kwargs={"matter_id": matter.pk}), fetch_redirect_response=False
        )
        self.assertEqual((matter.short_name, matter.court_name), ("M4", "Four Court"))

    def test_create_matter_needs_a_firm_and_group(self):
        response = self.post("fees_matter_new", self.matter_post(group_id=""))
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "Choose a firm and a group", status_code=422)

    def test_duplicate_matter_name(self):
        response = self.post("fees_matter_new", self.matter_post(name="matter one"))
        self.assertEqual(response.status_code, 409)

    def test_matter_in_another_profiles_firm_is_a_404(self):
        other_firm = self.other_seed["firm_a"]
        data = self.matter_post(firm_id=str(other_firm.pk), group_id=str(Group.objects.filter(firm=other_firm).first().pk))
        self.assertEqual(self.post("fees_matter_new", data).status_code, 404)

    def test_edit_matter(self):
        matter = self.seed["matter_1"]
        data = self.matter_post(name="Matter One Renamed", group_id=str(matter.group_id), notes="n")
        response = self.post("fees_matter_edit", data, {"matter_id": matter.pk})
        self.assertEqual(response.status_code, 302)
        matter.refresh_from_db()
        self.assertEqual(matter.name, "Matter One Renamed")

    def test_edit_other_profiles_matter_is_a_404(self):
        other = self.other_seed["matter_1"]
        self.assertEqual(self.post("fees_matter_edit", self.matter_post(), {"matter_id": other.pk}).status_code, 404)

    def test_archive_and_unarchive(self):
        matter = self.seed["matter_2"]
        self.post("fees_matter_archive", {"archive": "1"}, {"matter_id": matter.pk})
        matter.refresh_from_db()
        self.assertTrue(matter.is_archived)
        self.post("fees_matter_archive", {"archive": "0"}, {"matter_id": matter.pk})
        matter.refresh_from_db()
        self.assertFalse(matter.is_archived)


class SettingsWriteTests(WriteBase):
    def config(self):
        return FeesSettings.objects.get(profile=self.profile)

    def test_save_settings(self):
        response = self.post(
            "fees_settings",
            {
                "overdue_days": "45",
                "default_tds_rate": "12.5",
                "default_tab": "dashboard",
                "money_unit": "truncated",
                "export_owner_name": "Typed Owner",
                "memo_default_address": "Line one\r\nLine two",
                "statistics_enabled": "1",
                "show_status_dots": "0",
            },
        )
        self.assertRedirects(response, reverse("fees_settings"), fetch_redirect_response=False)
        config = self.config()
        self.assertEqual(config.overdue_days, 45)
        self.assertEqual(config.default_tds_rate, Decimal("12.5"))
        self.assertEqual(config.default_tab, "dashboard")
        self.assertEqual(config.money_unit, "truncated")
        self.assertEqual(config.export_owner_name, "Typed Owner")
        self.assertEqual(config.memo_default_address, "Line one\nLine two")
        self.assertTrue(config.statistics_enabled)
        self.assertFalse(config.show_status_dots)

    def test_a_partial_post_leaves_the_other_settings_alone(self):
        self.post("fees_settings", {"overdue_days": "50"})
        config = self.config()
        self.assertEqual(config.overdue_days, 50)
        self.assertEqual(config.default_tab, "firms")  # set by the seed
        self.assertEqual(config.export_owner_name, "Test Owner")
        # WriteBase.setUp switches statistics on; the partial POST must not change it.
        self.assertTrue(config.statistics_enabled)

    def test_a_bad_value_shows_the_page_again_and_saves_nothing(self):
        response = self.post("fees_settings", {"overdue_days": "many", "default_tab": "dashboard"})
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "Overdue days must be", status_code=422)
        self.assertEqual(self.config().default_tab, "firms")

    def test_bad_filename_pattern_is_refused(self):
        response = self.post("fees_settings", {"memo_filename_pattern": "{nope}"})
        self.assertEqual(response.status_code, 422)

    def test_bank_accounts(self):
        self.post("fees_bank_account_add", {"name": "New Bank"})
        account = BankAccount.objects.get(profile=self.profile, name="New Bank")
        self.post("fees_bank_account_rename", {"name": "Renamed Bank"}, {"account_id": account.pk})
        account.refresh_from_db()
        self.assertEqual(account.name, "Renamed Bank")
        self.post("fees_bank_account_delete", {}, {"account_id": account.pk})
        self.assertFalse(BankAccount.objects.filter(pk=account.pk).exists())

    def test_a_bank_account_in_use_cannot_be_deleted(self):
        bank = self.seed["bank"]
        response = self.post("fees_bank_account_delete", {}, {"account_id": bank.pk})
        self.assertRedirects(response, reverse("fees_settings"), fetch_redirect_response=False)
        self.assertTrue(BankAccount.objects.filter(pk=bank.pk).exists())
        self.assertTrue(any("used by a payment" in m for m in self.messages(response)))

    def test_duplicate_bank_account_name(self):
        response = self.post("fees_bank_account_add", {"name": "hdfc current"})
        self.assertRedirects(response, reverse("fees_settings"), fetch_redirect_response=False)
        self.assertEqual(BankAccount.objects.filter(profile=self.profile).count(), 1)

    def test_other_profiles_bank_account_is_a_404(self):
        other = self.other_seed["bank"]
        self.assertEqual(self.post("fees_bank_account_rename", {"name": "Z"}, {"account_id": other.pk}).status_code, 404)
        self.assertEqual(self.post("fees_bank_account_delete", {}, {"account_id": other.pk}).status_code, 404)

    def docx(self):
        everything = " ".join("{{%s}}" % name for name in sorted(TEXT_TAGS))
        return ds.build_docx(ds.document_xml(ds.paragraph(everything)))

    def test_template_upload(self):
        upload = SimpleUploadedFile("memo.docx", self.docx())
        response = self.post("fees_template_upload", {"file": upload})
        self.assertRedirects(response, reverse("fees_settings"), fetch_redirect_response=False)
        self.assertEqual(word_template.get_template_info(self.profile)["filename"], "memo.docx")
        self.assertEqual(self.client.get(reverse("fees_template_download")).status_code, 200)

    def test_template_upload_refuses_a_non_docx(self):
        response = self.post("fees_template_upload", {"file": SimpleUploadedFile("memo.txt", b"hello")})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(any("Word (.docx)" in m for m in self.messages(response)))

    def test_template_upload_without_a_file(self):
        response = self.post("fees_template_upload", {})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(any("Choose a file" in m for m in self.messages(response)))

    def test_signature_upload(self):
        upload = SimpleUploadedFile("new-sig.png", ds.png_bytes(60, 20), content_type="image/png")
        response = self.post("fees_signature_upload", {"file": upload})
        self.assertRedirects(response, reverse("fees_settings"), fetch_redirect_response=False)
        info = word_template.get_template_info(self.profile)
        self.assertTrue(info["has_signature"])
        self.assertEqual(info["signature_filename"], "new-sig.png")

    def test_signature_upload_refuses_a_big_or_wrong_file(self):
        big = SimpleUploadedFile("big.png", b"\x89PNG" + b"0" * (2 * 1024 * 1024 + 10), content_type="image/png")
        response = self.post("fees_signature_upload", {"file": big})
        self.assertTrue(any("2 MB" in m for m in self.messages(response)))
        wrong = SimpleUploadedFile("sig.png", b"not an image", content_type="image/png")
        response = self.post("fees_signature_upload", {"file": wrong})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(any("signature" in m.lower() for m in self.messages(response)))

    def test_dashboard_kpi_selection(self):
        response = self.post("fees_dashboard_kpis", {"kpi": ["billed_this_year", "billed_this_month", "bogus"]})
        self.assertRedirects(response, reverse("fees_dashboard"), fetch_redirect_response=False)
        self.assertEqual(self.config().dashboard_kpis, "billed_this_month,billed_this_year")

    def test_dashboard_kpi_get_is_still_json(self):
        self.assertEqual(self.client.get(reverse("fees_dashboard_kpis")).json()["ok"], True)

    def test_saved_views(self):
        response = self.post(
            "fees_statistics_views",
            {"name": "By firm", "measure": "billed", "row_dim": "firm", "col_dim": "none", "from_fy": "2025-26"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertIn("By firm", [v["name"] for v in response.json()["views"]])
        view = SavedView.objects.get(profile=self.profile, name="By firm")
        response = self.post("fees_statistics_view_delete", {}, {"view_id": view.pk})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(SavedView.objects.filter(pk=view.pk).exists())

    def test_saved_view_errors(self):
        blank = self.post("fees_statistics_views", {"name": " "})
        self.assertEqual(blank.status_code, 400)
        self.assertIs(blank.json()["ok"], False)
        bad_fy = self.post("fees_statistics_views", {"name": "x", "from_fy": "2025"})
        self.assertEqual(bad_fy.status_code, 422)
        other_firm = self.post("fees_statistics_views", {"name": "x", "firm_id": str(self.other_seed["firm_a"].pk)})
        self.assertEqual(other_firm.status_code, 404)
        self.assertEqual(other_firm.json()["error"], "FIRM_NOT_FOUND")

    def test_deleting_another_profiles_saved_view_changes_nothing(self):
        other_view = SavedView.objects.get(profile=self.other_profile)
        self.post("fees_statistics_view_delete", {}, {"view_id": other_view.pk})
        self.assertTrue(SavedView.objects.filter(pk=other_view.pk).exists())

    def test_statistics_grid_saves_a_month(self):
        response = self.post(
            "fees_settings_statistics_grid",
            {"financial_year": "2026-27", "fy": "2026-27", "month": "5", "working_days": "21", "extra_appearances": "2",
             "override_billed": "1000.50"},
        )
        self.assertEqual(response.status_code, 200)
        row = PeriodAdjustment.objects.get(profile=self.profile, financial_year="2026-27", month=5)
        self.assertEqual((row.working_days, row.extra_appearances), (21, 2))
        self.assertEqual(row.ov_billed, Decimal("1000.50"))
        months = [a["month"] for a in response.json()["adjustments"]]
        self.assertIn(5, months)

    def test_statistics_grid_refuses_a_bad_month(self):
        response = self.post("fees_settings_statistics_grid", {"fy": "2026-27", "month": "13"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"], "INVALID_MONTH")
        self.assertEqual(self.post("fees_settings_statistics_grid", {"fy": "2026-27", "month": "x"}).status_code, 422)


class BackupWriteTests(WriteBase):
    def workbook(self):
        out = excel_backup.export_workbook(self.profile)
        with out:
            return out.read()

    def upload(self, data=None, name="backup.xlsx"):
        return SimpleUploadedFile(name, data if data is not None else self.workbook())

    def counts(self):
        return (
            Memo.objects.filter(profile=self.profile).count(),
            Payment.objects.filter(profile=self.profile).count(),
            Firm.objects.filter(profile=self.profile).count(),
        )

    def test_restore_preview_shows_the_file_and_the_phrase(self):
        before = self.counts()
        response = self.post("fees_backup_restore", {"action": "preview", "file": self.upload()})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, RESTORE_CONFIRMATION)
        self.assertContains(response, "Memos")
        self.assertTemplateUsed(response, "fees/restore_preview.html")
        self.assertEqual(self.counts(), before)

    def test_restore_refuses_without_the_typed_phrase(self):
        before = self.counts()
        with mock.patch("fees.services.excel_restore._default_backup", return_value=None):
            response = self.post(
                "fees_backup_restore", {"action": "restore", "file": self.upload(), "confirmation": "yes please"}
            )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(any("exactly to confirm" in m for m in self.messages(response)))
        self.assertEqual(self.counts(), before)

    def test_restore_refuses_with_no_phrase_at_all(self):
        before = self.counts()
        with mock.patch("fees.services.excel_restore._default_backup", return_value=None):
            response = self.post("fees_backup_restore", {"action": "restore", "file": self.upload()})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.counts(), before)

    def test_restore_with_the_phrase(self):
        before = self.counts()
        data = self.workbook()
        with mock.patch("fees.services.excel_restore._default_backup", return_value=None):
            response = self.post(
                "fees_backup_restore",
                {"action": "restore", "file": self.upload(data), "confirmation": RESTORE_CONFIRMATION},
            )
        # Post/redirect/get: the result is a page of its own, so a refresh does not repeat the restore.
        self.assertRedirects(response, reverse("fees_backup_restored"), fetch_redirect_response=False)
        self.assertEqual(self.counts(), before)
        page = self.client.get(reverse("fees_backup_restored"))
        self.assertEqual(page.status_code, 200)
        self.assertTemplateUsed(page, "fees/restore_result.html")
        self.assertEqual(self.client.get(reverse("fees_backup_restored")).status_code, 200)

    def test_restore_result_page_without_a_job_goes_to_the_backup_page(self):
        response = self.client.get(reverse("fees_backup_restored"))
        self.assertRedirects(response, reverse("fees_backup"), fetch_redirect_response=False)

    def test_restore_of_a_damaged_file_is_a_message(self):
        before = self.counts()
        response = self.post("fees_backup_restore", {"action": "preview", "file": self.upload(b"this is not a workbook")})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.messages(response))
        self.assertEqual(self.counts(), before)

    def test_restore_without_a_file(self):
        response = self.post("fees_backup_restore", {"action": "preview"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(any("Choose a file" in m for m in self.messages(response)))

    def test_restore_get_goes_back_to_the_backup_page(self):
        response = self.client.get(reverse("fees_backup_restore"))
        self.assertRedirects(response, reverse("fees_backup"), fetch_redirect_response=False)

    def test_restore_busy_is_the_503_page(self):
        with mock.patch("fees.views_backup.excel_restore.preview_workbook", side_effect=Busy()):
            response = self.post("fees_backup_restore", {"action": "preview", "file": self.upload()})
        self.assertEqual(response.status_code, 503)
        self.assertTemplateUsed(response, "fees/busy.html")

    def test_clear_page_asks_for_the_profile_name(self):
        response = self.client.get(reverse("fees_backup_clear"))
        self.assertContains(response, "Write-Fees")

    def test_clear_refuses_a_wrong_name(self):
        before = self.counts()
        with mock.patch("fees.services.clear_all._default_backup", return_value=None):
            response = self.post("fees_backup_clear", {"confirmation": "Something else"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(any("Nothing was deleted" in m for m in self.messages(response)))
        self.assertEqual(self.counts(), before)

    def test_clear_refuses_no_confirmation(self):
        before = self.counts()
        with mock.patch("fees.services.clear_all._default_backup", return_value=None):
            self.post("fees_backup_clear", {})
        self.assertEqual(self.counts(), before)

    def test_clear_with_the_profile_name(self):
        with mock.patch("fees.services.clear_all._default_backup", return_value=None):
            response = self.post("fees_backup_clear", {"confirmation": " Write-Fees "})
        self.assertRedirects(response, reverse("fees_backup_cleared"), fetch_redirect_response=False)
        page = self.client.get(reverse("fees_backup_cleared"))
        self.assertEqual(page.status_code, 200)
        self.assertTemplateUsed(page, "fees/clear_result.html")
        self.assertEqual(self.counts(), (0, 0, 0))
        # The other profile is untouched.
        self.assertTrue(Memo.objects.filter(profile=self.other_profile).exists())

    def test_clear_result_page_without_a_job_goes_to_the_backup_page(self):
        response = self.client.get(reverse("fees_backup_cleared"))
        self.assertRedirects(response, reverse("fees_backup"), fetch_redirect_response=False)

    def test_clear_busy_is_the_503_page(self):
        with mock.patch("fees.views_backup.clear_all.clear_all", side_effect=Busy()):
            response = self.post("fees_backup_clear", {"confirmation": "Write-Fees"})
        self.assertEqual(response.status_code, 503)
        self.assertTemplateUsed(response, "fees/busy.html")


class ImportWriteTests(WriteBase):
    CSV = b"Firm,Matter,Date,Total Fees\nImport Firm,Import Matter,2026-08-01,5000\n"

    def csv(self, data=None, name="memos.csv"):
        return SimpleUploadedFile(name, data if data is not None else self.CSV, content_type="text/csv")

    def test_inspect_shows_headers_and_a_guess(self):
        response = self.post("fees_import_inspect", {"file": self.csv()})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "fees/import_map.html")
        self.assertContains(response, "Total Fees")
        self.assertEqual(response.context["info"]["row_count"], 1)
        self.assertEqual(response.context["info"]["headers"], ["Firm", "Matter", "Date", "Total Fees"])

    def test_run_imports_the_file(self):
        before = self.version()
        data = {
            "file": self.csv(),
            "map_firm_name": "Firm",
            "map_matter_name": "Matter",
            "map_date": "Date",
            "map_total_fees": "Total Fees",
            "auto_number": "1",
        }
        response = self.post("fees_import_run", data)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "fees/import_result.html")
        memo = Memo.objects.get(profile=self.profile, matter__name="Import Matter")
        self.assertFalse(memo.is_draft)
        self.assertEqual(memo.total_fees, Decimal("5000.00"))
        self.assertTrue(Firm.objects.filter(profile=self.profile, name="Import Firm").exists())
        self.assertGreater(self.version(), before)

    def test_run_without_the_required_columns_is_a_message(self):
        count = Memo.objects.filter(profile=self.profile).count()
        response = self.post("fees_import_run", {"file": self.csv(), "map_date": "Date"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(any("must be mapped" in m for m in self.messages(response)))
        self.assertEqual(Memo.objects.filter(profile=self.profile).count(), count)

    def test_wrong_file_type_is_a_message(self):
        response = self.post("fees_import_inspect", {"file": SimpleUploadedFile("memos.txt", b"a,b\n1,2\n")})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(any(".xlsx and .csv" in m for m in self.messages(response)))

    def test_inspect_without_a_file(self):
        self.assertEqual(self.post("fees_import_inspect", {}).status_code, 302)

    def test_busy_is_the_503_page(self):
        with mock.patch("fees.views_import.imports.run_import", side_effect=Busy()):
            response = self.post(
                "fees_import_run", {"file": self.csv(), "map_firm_name": "Firm", "map_matter_name": "Matter"}
            )
        self.assertEqual(response.status_code, 503)
        self.assertTemplateUsed(response, "fees/busy.html")
        with mock.patch("fees.views_import.imports.inspect_file", side_effect=Busy()):
            response = self.post("fees_import_inspect", {"file": self.csv()})
        self.assertEqual(response.status_code, 503)


class RoleAndCsrfTests(WriteBase):
    def endpoints(self):
        s = self.seed
        return [
            ("fees_memo_new", {}),
            ("fees_memo_edit", {"memo_id": s["memo_a"].pk}),
            ("fees_memo_delete", {"memo_id": s["memo_a"].pk}),
            ("fees_memo_write_off", {"memo_id": s["memo_a"].pk}),
            ("fees_memo_finalise", {"memo_id": s["draft"].pk}),
            ("fees_memo_based_on", {"memo_id": s["memo_a"].pk}),
            ("fees_payment_new", {}),
            ("fees_payment_edit", {"payment_id": s["single"]["id"]}),
            ("fees_payment_delete", {"payment_id": s["single"]["id"]}),
            ("fees_payment_assign", {"payment_id": s["unaccounted"]["id"]}),
            ("fees_firm_new", {}),
            ("fees_firm_edit", {"firm_id": s["firm_a"].pk}),
            ("fees_firm_status", {"firm_id": s["firm_a"].pk}),
            ("fees_group_add", {"firm_id": s["firm_a"].pk}),
            ("fees_group_rename", {"firm_id": s["firm_a"].pk, "group_id": Group.objects.filter(firm=s["firm_a"]).first().pk}),
            ("fees_group_remove", {"firm_id": s["firm_a"].pk, "group_id": Group.objects.filter(firm=s["firm_a"]).first().pk}),
            ("fees_matter_new", {}),
            ("fees_matter_edit", {"matter_id": s["matter_1"].pk}),
            ("fees_matter_archive", {"matter_id": s["matter_1"].pk}),
            ("fees_settings", {}),
            ("fees_bank_account_add", {}),
            ("fees_bank_account_rename", {"account_id": s["bank"].pk}),
            ("fees_bank_account_delete", {"account_id": s["bank"].pk}),
            ("fees_template_upload", {}),
            ("fees_signature_upload", {}),
            ("fees_dashboard_kpis", {}),
            ("fees_statistics_views", {}),
            ("fees_statistics_view_delete", {"view_id": SavedView.objects.get(profile=self.profile).pk}),
            ("fees_settings_statistics_grid", {}),
            ("fees_backup_restore", {}),
            ("fees_backup_clear", {}),
            ("fees_import_inspect", {}),
            ("fees_import_run", {}),
        ]

    def snapshot(self):
        return (
            Memo.objects.filter(profile=self.profile).count(),
            Payment.objects.filter(profile=self.profile).count(),
            Firm.objects.filter(profile=self.profile).count(),
            Matter.objects.filter(profile=self.profile).count(),
            BankAccount.objects.filter(profile=self.profile).count(),
            SavedView.objects.filter(profile=self.profile).count(),
            WordTemplate.objects.get(profile=self.profile).filename,
            FeesSettings.objects.get(profile=self.profile).data_version,
        )

    def test_a_reader_cannot_write_anywhere(self):
        self.client.force_login(self.reader)
        before = self.snapshot()
        for name, kwargs in self.endpoints():
            response = self.client.post(reverse(name, kwargs=kwargs), {"confirm": "1", "confirmation": "Write-Fees"})
            self.assertEqual(response.status_code, 403, name)
        self.assertEqual(self.snapshot(), before)

    def test_a_user_without_membership_cannot_write_anywhere(self):
        self.client.force_login(self.outsider)
        for name, kwargs in self.endpoints():
            self.assertEqual(self.client.post(reverse(name, kwargs=kwargs), {}).status_code, 403, name)

    def test_an_anonymous_user_is_sent_to_login(self):
        self.client.logout()
        for name, kwargs in self.endpoints():
            response = self.client.post(reverse(name, kwargs=kwargs), {})
            self.assertEqual(response.status_code, 302, name)
            self.assertIn(reverse("login"), response["Location"], name)

    def test_a_post_without_the_csrf_token_is_refused(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.editor)
        before = self.snapshot()
        for name, kwargs in self.endpoints():
            response = client.post(reverse(name, kwargs=kwargs), {"confirm": "1"})
            self.assertEqual(response.status_code, 403, name)
        self.assertEqual(self.snapshot(), before)

    def test_a_post_with_the_token_works(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.editor)
        client.get(reverse("fees_firm_new"))
        token = client.cookies["csrftoken"].value
        response = client.post(reverse("fees_firm_new"), {"name": "Token Firm", "csrfmiddlewaretoken": token})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Firm.objects.filter(profile=self.profile, name="Token Firm").exists())

    def test_the_token_can_be_sent_in_the_header_for_json_endpoints(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.editor)
        client.get(reverse("fees_firm_new"))
        token = client.cookies["csrftoken"].value
        response = client.post(reverse("fees_statistics_views"), {"name": "Via header"}, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 201)

    def test_get_is_refused_on_post_only_endpoints(self):
        for name, kwargs in (
            ("fees_memo_delete", {"memo_id": self.seed["memo_a"].pk}),
            ("fees_memo_write_off", {"memo_id": self.seed["memo_a"].pk}),
            ("fees_memo_finalise", {"memo_id": self.seed["draft"].pk}),
            ("fees_payment_delete", {"payment_id": self.seed["single"]["id"]}),
            ("fees_payment_assign", {"payment_id": self.seed["unaccounted"]["id"]}),
            ("fees_firm_status", {"firm_id": self.seed["firm_a"].pk}),
            ("fees_group_add", {"firm_id": self.seed["firm_a"].pk}),
            ("fees_matter_archive", {"matter_id": self.seed["matter_1"].pk}),
            ("fees_bank_account_add", {}),
            ("fees_template_upload", {}),
            ("fees_signature_upload", {}),
            ("fees_import_inspect", {}),
            ("fees_import_run", {}),
        ):
            self.assertEqual(self.client.get(reverse(name, kwargs=kwargs)).status_code, 405, name)


class ServicesDoTheWorkTests(WriteBase):
    """A view never bumps ``data_version`` itself: one memo create is one bump, from the service."""

    def test_one_create_is_one_bump(self):
        before = self.version()
        self.post(
            "fees_memo_new",
            {"matter_id": str(self.seed["matter_1"].pk), "date": "2026-08-10", "num_appearances": "1", "action": "save"},
        )
        self.assertEqual(self.version(), before + 1)

    def test_a_refused_write_does_not_bump(self):
        before = self.version()
        self.post("fees_memo_new", {"matter_id": str(self.seed["matter_1"].pk), "date": "", "action": "save"})
        self.post("fees_firm_new", {"name": ""})
        self.assertEqual(self.version(), before)
