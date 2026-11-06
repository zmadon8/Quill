"""Memo lifecycle tests for the Fee Register (T2.5, R-MEMO-1 to R-MEMO-7, R-DATA-4, R-DATA-6).

Ports ``memoService.test.ts`` (create / custom-number / update / delete /
drafts / write-off / create-based-on) and ``memoService.property.test.ts`` (the
property loop becomes a seeded ``random.Random`` run, U8: Hypothesis not
approved). Adds the explicit Q1/D3 test (a custom total of 0 with line customs
set stores the SUM, not 0) and the Q5 real-date test (an impossible date on a
non-draft save raises ``INVALID_MEMO``; a draft skips validation).

These tests use the ORM, so Django ``TestCase`` is used and everything is scoped
to a ``Profile(program="fees")``. The firm / group / matter helpers mirror
``test_memo_numbers.py``.
"""
import datetime
import random
from decimal import Decimal

from django.test import TestCase

from accounts.models import Profile
from accounts.suite import KEY_FEES
from fees.errors import FeesError
from fees.models import (
    Allocation,
    FeesSettings,
    Firm,
    Group,
    Matter,
    Memo,
    NumberSequence,
    Payment,
)
from fees.services import memo_fees, memos
from fees.services.financial_year import derive_financial_year


def fees_profile(name="Ziyad-Fees"):
    return Profile.objects.create(program=KEY_FEES, name=name)


def seed_matter(profile, archived=False, firm_name="Firm", matter_name="Matter"):
    firm = Firm.objects.create(profile=profile, name=firm_name)
    group = Group.objects.create(profile=profile, firm=firm, name="Group")
    matter = Matter.objects.create(
        profile=profile,
        firm=firm,
        group=group,
        name=matter_name,
        is_archived=archived,
    )
    return firm, group, matter


def base_input(matter_id, **over):
    data = dict(
        date="2026-07-15",
        matter_id=matter_id,
        addressee_line1="Acme Legal",
        num_appearances=2,
        fees_per_appearance=5000,
        num_conferences=1,
        fees_per_conference=3000,
        fees_misc_drafting=1000,
    )
    data.update(over)
    return data


def data_version(profile):
    return (
        FeesSettings.objects.filter(profile=profile)
        .values_list("data_version", flat=True)
        .first()
    )


# ---------------------------------------------------------------------------
# Create and compute
# ---------------------------------------------------------------------------

class CreateMemoTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, self.group, self.matter = seed_matter(self.profile)

    def test_creates_with_generated_number_and_computed_fields(self):
        memo = memos.create_memo(self.profile, base_input(self.matter.pk))
        self.assertEqual(memo.memo_number, "2026-27/1")
        self.assertEqual(memo.financial_year, "2026-27")
        self.assertEqual(memo.seq, 1)
        self.assertEqual(memo.total_fees, Decimal("14000.00"))
        # Snapshot came from the input, not the matter.
        self.assertEqual(memo.addressee_line1, "Acme Legal")
        # firm/group copied from the matter.
        self.assertEqual(memo.firm_id, self.matter.firm_id)
        self.assertEqual(memo.group_id, self.matter.group_id)

    def test_detail_derived_values(self):
        memo = memos.create_memo(self.profile, base_input(self.matter.pk))
        detail = memos.get_memo(self.profile, memo.pk)
        self.assertEqual(detail["fees_appearances"], Decimal("10000.00"))
        self.assertEqual(detail["fees_conferences"], Decimal("3000.00"))
        self.assertEqual(detail["total_fees"], Decimal("14000.00"))
        # net of tds at the default 10% rate: 14000 - 1400.
        self.assertEqual(detail["net_of_tds"], Decimal("12600.00"))
        self.assertEqual(detail["status"], "Unpaid")
        self.assertEqual(detail["amount_paid"], Decimal("0.00"))
        self.assertEqual(detail["payment_count"], 0)
        self.assertIsNone(detail["date_of_last_payment"])

    def test_matter_not_found(self):
        with self.assertRaises(FeesError) as ctx:
            memos.create_memo(self.profile, base_input(999999))
        self.assertEqual(ctx.exception.code, "MATTER_NOT_FOUND")

    def test_matter_from_other_profile_is_not_found(self):
        other = fees_profile("Other-Fees")
        _, _, other_matter = seed_matter(other)
        with self.assertRaises(FeesError) as ctx:
            memos.create_memo(self.profile, base_input(other_matter.pk))
        self.assertEqual(ctx.exception.code, "MATTER_NOT_FOUND")

    def test_archived_matter_rejected_for_non_draft(self):
        _, _, archived = seed_matter(self.profile, archived=True, firm_name="F2")
        with self.assertRaises(FeesError) as ctx:
            memos.create_memo(self.profile, base_input(archived.pk))
        self.assertEqual(ctx.exception.code, "MATTER_ARCHIVED")

    def test_missing_date_rejected(self):
        with self.assertRaises(FeesError) as ctx:
            memos.create_memo(self.profile, base_input(self.matter.pk, date=""))
        self.assertEqual(ctx.exception.code, "INVALID_MEMO")
        self.assertIn("Date", ctx.exception.message)

    def test_status_paid_when_payments_cover_total(self):
        memo = memos.create_memo(self.profile, base_input(self.matter.pk))
        # Simulate a fully paying allocation (payments.py lands in T2.6).
        memo.amount_paid = Decimal("14000.00")
        memo.save(update_fields=["amount_paid"])
        detail = memos.get_memo(self.profile, memo.pk)
        self.assertEqual(detail["status"], "Paid")
        self.assertEqual(detail["amount_due"], Decimal("0.00"))


# ---------------------------------------------------------------------------
# Custom memo number (per-memo)
# ---------------------------------------------------------------------------

class CustomMemoNumberTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter = seed_matter(self.profile)

    def test_auto_sequence_when_no_custom_number(self):
        memo = memos.create_memo(self.profile, base_input(self.matter.pk))
        self.assertEqual(memo.memo_number, "2026-27/1")
        self.assertFalse(memos.get_memo(self.profile, memo.pk)["is_custom_number"])

    def test_custom_number_verbatim(self):
        memo = memos.create_memo(
            self.profile,
            base_input(self.matter.pk, custom_memo_number="ABC-2025/7"),
        )
        self.assertEqual(memo.memo_number, "ABC-2025/7")
        self.assertEqual(memo.seq, 0)
        detail = memos.get_memo(self.profile, memo.pk)
        self.assertTrue(detail["is_custom_number"])
        self.assertEqual(detail["custom_memo_number"], "ABC-2025/7")

    def test_custom_and_auto_coexist_sequence_unaffected(self):
        auto = memos.create_memo(self.profile, base_input(self.matter.pk))
        custom = memos.create_memo(
            self.profile,
            base_input(self.matter.pk, date="2026-08-01", custom_memo_number="X/1"),
        )
        auto2 = memos.create_memo(
            self.profile, base_input(self.matter.pk, date="2026-09-01")
        )
        self.assertEqual(auto.memo_number, "2026-27/1")
        self.assertEqual(custom.memo_number, "X/1")
        self.assertEqual(auto2.memo_number, "2026-27/2")

    def test_duplicate_custom_number_rejected(self):
        memos.create_memo(
            self.profile, base_input(self.matter.pk, custom_memo_number="DUP/1")
        )
        with self.assertRaises(FeesError) as ctx:
            memos.create_memo(
                self.profile,
                base_input(
                    self.matter.pk, date="2026-08-01", custom_memo_number="DUP/1"
                ),
            )
        self.assertEqual(ctx.exception.code, "INVALID_MEMO")


class KeptAutoNumberMemoTests(TestCase):
    """Owner decision 5: typing an automatic-shaped number on create, finalise and edit."""

    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter = seed_matter(self.profile)

    def counter(self, fy="2026-27"):
        return NumberSequence.objects.get(profile=self.profile, financial_year=fy).last_seq

    def test_typed_auto_number_is_a_real_auto_number_and_moves_the_counter(self):
        memo = memos.create_memo(
            self.profile, base_input(self.matter.pk, custom_memo_number=" 2026-27/10 ")
        )
        self.assertEqual((memo.memo_number, memo.seq, memo.financial_year), ("2026-27/10", 10, "2026-27"))
        self.assertFalse(memos.get_memo(self.profile, memo.pk)["is_custom_number"])
        self.assertEqual(self.counter(), 10)
        nxt = memos.create_memo(self.profile, base_input(self.matter.pk, date="2026-08-01"))
        self.assertEqual(nxt.memo_number, "2026-27/11")

    def test_a_lower_typed_number_does_not_lower_the_counter(self):
        memos.create_memo(self.profile, base_input(self.matter.pk, custom_memo_number="2026-27/10"))
        memos.create_memo(self.profile, base_input(self.matter.pk, custom_memo_number="2026-27/2"))
        self.assertEqual(self.counter(), 10)

    def test_wrong_financial_year_is_refused(self):
        with self.assertRaises(FeesError) as ctx:
            memos.create_memo(self.profile, base_input(self.matter.pk, custom_memo_number="2025-26/3"))
        self.assertEqual(ctx.exception.code, "INVALID_MEMO")
        self.assertFalse(Memo.objects.filter(profile=self.profile).exists())
        self.assertFalse(NumberSequence.objects.filter(profile=self.profile).exists())

    def test_a_number_already_used_is_refused(self):
        memos.create_memo(self.profile, base_input(self.matter.pk, custom_memo_number="2026-27/4"))
        with self.assertRaises(FeesError) as ctx:
            memos.create_memo(self.profile, base_input(self.matter.pk, custom_memo_number="2026-27/4"))
        self.assertIn("already in use", ctx.exception.message)

    def test_finalise_with_a_typed_auto_number(self):
        draft = memos.save_draft(self.profile, base_input(self.matter.pk))
        memo = memos.finalize_draft(self.profile, draft.pk, custom_number="2026-27/6")
        self.assertEqual((memo.memo_number, memo.seq), ("2026-27/6", 6))
        self.assertEqual(self.counter(), 6)

    def test_finalise_with_the_wrong_year_is_refused_and_stays_a_draft(self):
        draft = memos.save_draft(self.profile, base_input(self.matter.pk))
        with self.assertRaises(FeesError):
            memos.finalize_draft(self.profile, draft.pk, custom_number="2027-28/1")
        self.assertTrue(Memo.objects.get(pk=draft.pk).is_draft)

    def test_editing_a_number_to_an_auto_number_raises_the_counter(self):
        memo = memos.create_memo(self.profile, base_input(self.matter.pk))
        updated = memos.update_memo(self.profile, memo.pk, base_input(self.matter.pk, custom_memo_number="2026-27/20"))
        self.assertEqual((updated.memo_number, updated.seq), ("2026-27/20", 20))
        self.assertEqual(self.counter(), 20)

    def test_editing_away_from_an_auto_number_never_lowers_the_counter(self):
        memos.create_memo(self.profile, base_input(self.matter.pk))
        second = memos.create_memo(self.profile, base_input(self.matter.pk, date="2026-08-01"))
        updated = memos.update_memo(self.profile, second.pk, base_input(self.matter.pk, custom_memo_number="INV-9"))
        self.assertEqual((updated.memo_number, updated.seq), ("INV-9", 0))
        self.assertEqual(self.counter(), 2)
        third = memos.create_memo(self.profile, base_input(self.matter.pk, date="2026-09-01"))
        self.assertEqual(third.memo_number, "2026-27/3")  # 2026-27/2 is never reused

    def test_sending_the_memos_own_custom_text_back_changes_nothing(self):
        memo = Memo.objects.create(
            profile=self.profile, matter=self.matter, firm=self.matter.firm, group=self.matter.group,
            financial_year="2026-27", date=datetime.date(2026, 7, 15), addressee_line1="A",
            memo_number="2020-21/5", seq=0, is_draft=False,
        )
        updated = memos.update_memo(self.profile, memo.pk, base_input(self.matter.pk, custom_memo_number="2020-21/5"))
        self.assertEqual((updated.memo_number, updated.seq, updated.financial_year), ("2020-21/5", 0, "2026-27"))
        self.assertFalse(NumberSequence.objects.filter(profile=self.profile).exists())

    def test_editing_to_another_year_auto_number_is_refused(self):
        memo = memos.create_memo(self.profile, base_input(self.matter.pk))
        with self.assertRaises(FeesError):
            memos.update_memo(self.profile, memo.pk, base_input(self.matter.pk, custom_memo_number="2025-26/1"))

    def test_preview_still_reads_the_counter(self):
        memos.create_memo(self.profile, base_input(self.matter.pk, custom_memo_number="2026-27/7"))
        self.assertEqual(memos.preview_number(self.profile, "2026-07-15"), "2026-27/8")


# ---------------------------------------------------------------------------
# Drafts and finalise
# ---------------------------------------------------------------------------

class DraftAndFinalizeTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter = seed_matter(self.profile)

    def test_draft_has_no_number_and_fy_from_date(self):
        draft = memos.save_draft(self.profile, base_input(self.matter.pk))
        self.assertTrue(draft.is_draft)
        self.assertIsNone(draft.memo_number)
        self.assertEqual(draft.seq, 0)
        self.assertEqual(draft.financial_year, "2026-27")

    def test_draft_with_no_date_uses_current_fy(self):
        draft = memos.save_draft(self.profile, base_input(self.matter.pk, date=""))
        self.assertIsNone(draft.memo_number)
        self.assertEqual(
            draft.financial_year, derive_financial_year(datetime.date.today())
        )

    def test_draft_does_not_consume_numbers_then_finalise_assigns_next(self):
        draft = memos.save_draft(self.profile, base_input(self.matter.pk))
        numbered = memos.create_memo(
            self.profile, base_input(self.matter.pk, date="2026-08-01")
        )
        self.assertEqual(numbered.memo_number, "2026-27/1")
        finalised = memos.finalize_draft(self.profile, draft.pk)
        self.assertFalse(finalised.is_draft)
        self.assertEqual(finalised.memo_number, "2026-27/2")

    def test_finalize_is_noop_when_already_final(self):
        memo = memos.create_memo(self.profile, base_input(self.matter.pk))
        again = memos.finalize_draft(self.profile, memo.pk)
        self.assertEqual(again.memo_number, "2026-27/1")

    def test_finalize_requires_a_valid_date(self):
        draft = memos.save_draft(self.profile, base_input(self.matter.pk, date=""))
        with self.assertRaises(FeesError) as ctx:
            memos.finalize_draft(self.profile, draft.pk)
        self.assertEqual(ctx.exception.code, "INVALID_MEMO")

    def test_finalize_with_custom_number(self):
        draft = memos.save_draft(self.profile, base_input(self.matter.pk))
        finalised = memos.finalize_draft(
            self.profile, draft.pk, custom_number="MY-1"
        )
        self.assertFalse(finalised.is_draft)
        self.assertEqual(finalised.memo_number, "MY-1")
        self.assertEqual(finalised.seq, 0)

    def test_finalize_memo_not_found(self):
        with self.assertRaises(FeesError) as ctx:
            memos.finalize_draft(self.profile, 123456)
        self.assertEqual(ctx.exception.code, "MEMO_NOT_FOUND")


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

class UpdateMemoTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter = seed_matter(self.profile)

    def test_update_recomputes_totals(self):
        memo = memos.create_memo(self.profile, base_input(self.matter.pk))
        updated = memos.update_memo(
            self.profile, memo.pk, base_input(self.matter.pk, num_appearances=4)
        )
        self.assertEqual(updated.total_fees, Decimal("24000.00"))
        detail = memos.get_memo(self.profile, memo.pk)
        self.assertEqual(detail["fees_appearances"], Decimal("20000.00"))

    def test_finalised_date_edit_keeps_number_and_fy(self):
        memo = memos.create_memo(self.profile, base_input(self.matter.pk))
        memos.update_memo(
            self.profile, memo.pk, base_input(self.matter.pk, date="2026-08-20")
        )
        reloaded = memos.get_memo(self.profile, memo.pk)
        self.assertEqual(str(reloaded["date"]), "2026-08-20")
        self.assertEqual(reloaded["memo_number"], "2026-27/1")
        self.assertEqual(reloaded["financial_year"], "2026-27")

    def test_draft_date_edit_re_derives_fy(self):
        draft = memos.save_draft(self.profile, base_input(self.matter.pk))
        self.assertEqual(draft.financial_year, "2026-27")
        memos.update_memo(
            self.profile, draft.pk, base_input(self.matter.pk, date="2026-03-31")
        )
        reloaded = memos.get_memo(self.profile, draft.pk)
        self.assertEqual(str(reloaded["date"]), "2026-03-31")
        self.assertEqual(reloaded["financial_year"], "2025-26")

    def test_update_does_not_advance_sequence(self):
        memo = memos.create_memo(self.profile, base_input(self.matter.pk))
        before = NumberSequence.objects.get(
            profile=self.profile, financial_year="2026-27"
        ).last_seq
        memos.update_memo(
            self.profile, memo.pk, base_input(self.matter.pk, num_appearances=9)
        )
        after = NumberSequence.objects.get(
            profile=self.profile, financial_year="2026-27"
        ).last_seq
        self.assertEqual(before, after)

    def test_update_memo_not_found(self):
        with self.assertRaises(FeesError) as ctx:
            memos.update_memo(self.profile, 7777, base_input(self.matter.pk))
        self.assertEqual(ctx.exception.code, "MEMO_NOT_FOUND")


# ---------------------------------------------------------------------------
# Write-off
# ---------------------------------------------------------------------------

class WriteOffTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter = seed_matter(self.profile)

    def test_cannot_write_off_a_fully_paid_memo(self):
        memo = memos.create_memo(self.profile, base_input(self.matter.pk))
        memo.amount_paid = Decimal("14000.00")
        memo.save(update_fields=["amount_paid"])
        with self.assertRaises(FeesError) as ctx:
            memos.set_memo_written_off(self.profile, memo.pk, True)
        self.assertEqual(ctx.exception.code, "INVALID_MEMO")
        self.assertEqual(
            ctx.exception.message, "A fully paid memo cannot be written off"
        )

    def test_write_off_unpaid_leaves_payment_untouched(self):
        memo = memos.create_memo(self.profile, base_input(self.matter.pk))
        memo.amount_paid = Decimal("1000.00")  # partial
        memo.save(update_fields=["amount_paid"])
        off = memos.set_memo_written_off(self.profile, memo.pk, True)
        self.assertTrue(off.written_off)
        self.assertEqual(off.amount_paid, Decimal("1000.00"))

    def test_restore_is_always_allowed_even_when_paid(self):
        memo = memos.create_memo(self.profile, base_input(self.matter.pk))
        memo.amount_paid = Decimal("14000.00")
        memo.written_off = True
        memo.save(update_fields=["amount_paid", "written_off"])
        restored = memos.set_memo_written_off(self.profile, memo.pk, False)
        self.assertFalse(restored.written_off)

    def test_write_off_memo_not_found(self):
        with self.assertRaises(FeesError) as ctx:
            memos.set_memo_written_off(self.profile, 42, True)
        self.assertEqual(ctx.exception.code, "MEMO_NOT_FOUND")


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def make_payment(profile, amount, date="2026-08-01"):
    return Payment.objects.create(
        profile=profile,
        amount=Decimal(str(amount)),
        date_of_payment=datetime.date.fromisoformat(date),
    )


def allocate(profile, payment, memo, amount, tds=0):
    return Allocation.objects.create(
        payment=payment,
        memo=memo,
        profile=profile,
        amount=Decimal(str(amount)),
        tds_amount=Decimal(str(tds)),
    )


class DeleteMemoTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter = seed_matter(self.profile)

    def test_delete_does_not_reuse_number(self):
        first = memos.create_memo(self.profile, base_input(self.matter.pk))
        self.assertEqual(first.memo_number, "2026-27/1")
        memos.delete_memo(self.profile, first.pk)
        second = memos.create_memo(self.profile, base_input(self.matter.pk))
        self.assertEqual(second.memo_number, "2026-27/2")

    def test_delete_removes_allocations_and_only_this_memo_orphan_payment(self):
        memo = memos.create_memo(self.profile, base_input(self.matter.pk))
        payment = make_payment(self.profile, 14000)
        allocate(self.profile, payment, memo, 14000)
        memos.delete_memo(self.profile, memo.pk)
        self.assertFalse(Memo.objects.filter(pk=memo.pk).exists())
        self.assertFalse(Allocation.objects.filter(memo_id=memo.pk).exists())
        # The payment was linked ONLY to this memo, so it is deleted.
        self.assertFalse(Payment.objects.filter(pk=payment.pk).exists())

    def test_delete_keeps_a_split_payment_and_its_other_allocations(self):
        memo_a = memos.create_memo(self.profile, base_input(self.matter.pk))
        memo_b = memos.create_memo(
            self.profile, base_input(self.matter.pk, date="2026-09-01")
        )
        payment = make_payment(self.profile, 20000)
        alloc_a = allocate(self.profile, payment, memo_a, 14000)
        alloc_b = allocate(self.profile, payment, memo_b, 6000)
        memos.delete_memo(self.profile, memo_a.pk)
        # The split payment survives with its other allocation intact.
        self.assertTrue(Payment.objects.filter(pk=payment.pk).exists())
        self.assertFalse(Allocation.objects.filter(pk=alloc_a.pk).exists())
        self.assertTrue(Allocation.objects.filter(pk=alloc_b.pk).exists())
        self.assertTrue(Memo.objects.filter(pk=memo_b.pk).exists())

    def test_delete_memo_not_found(self):
        with self.assertRaises(FeesError) as ctx:
            memos.delete_memo(self.profile, 55555)
        self.assertEqual(ctx.exception.code, "MEMO_NOT_FOUND")


# ---------------------------------------------------------------------------
# Create based on
# ---------------------------------------------------------------------------

class CreateBasedOnTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter = seed_matter(self.profile)

    def test_copies_fields_blanks_date_no_id_or_number(self):
        src = memos.create_memo(
            self.profile,
            base_input(
                self.matter.pk, client="Mr X", plaintiff_name="P"
            ),
        )
        form = memos.create_based_on(self.profile, src.pk)
        self.assertEqual(form["source_memo_id"], src.pk)
        self.assertEqual(form["date"], "")
        self.assertEqual(form["matter_id"], self.matter.pk)
        self.assertEqual(form["client"], "Mr X")
        self.assertEqual(form["plaintiff_name"], "P")
        self.assertEqual(form["fees_per_appearance"], Decimal("5000.00"))
        self.assertNotIn("id", form)
        self.assertNotIn("memo_number", form)

    def test_copies_custom_overrides(self):
        src = memos.create_memo(
            self.profile,
            base_input(self.matter.pk, custom_fees_appearances=777),
        )
        form = memos.create_based_on(self.profile, src.pk)
        self.assertEqual(form["custom_fees_appearances"], Decimal("777.00"))

    def test_source_not_found(self):
        with self.assertRaises(FeesError) as ctx:
            memos.create_based_on(self.profile, 99)
        self.assertEqual(ctx.exception.code, "MEMO_NOT_FOUND")


# ---------------------------------------------------------------------------
# Preview number
# ---------------------------------------------------------------------------

class PreviewNumberTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter = seed_matter(self.profile)

    def test_preview_is_read_only(self):
        self.assertEqual(memos.preview_number(self.profile, "2026-07-15"), "2026-27/1")
        # Preview creates nothing.
        self.assertFalse(
            NumberSequence.objects.filter(
                profile=self.profile, financial_year="2026-27"
            ).exists()
        )


# ---------------------------------------------------------------------------
# Honour custom amounts (R-MEMO-1)
# ---------------------------------------------------------------------------

class CustomAmountTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter = seed_matter(self.profile)

    def test_custom_total_overrides_auto(self):
        memo = memos.create_memo(
            self.profile, base_input(self.matter.pk, custom_total_fees=99999)
        )
        self.assertEqual(
            memos.get_memo(self.profile, memo.pk)["total_fees"],
            Decimal("99999.00"),
        )


# ---------------------------------------------------------------------------
# R-DATA-4: stored total_fees equals resolve_memo_fees of the stored columns
# ---------------------------------------------------------------------------

class StoredTotalFeesTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter = seed_matter(self.profile)

    def test_stored_total_matches_resolve_after_create(self):
        memo = memos.create_memo(self.profile, base_input(self.matter.pk))
        self.assertEqual(
            memo.total_fees, memo_fees.resolve_memo_fees(memo).total_fees
        )

    def test_stored_total_matches_resolve_after_update(self):
        memo = memos.create_memo(self.profile, base_input(self.matter.pk))
        memos.update_memo(
            self.profile,
            memo.pk,
            base_input(self.matter.pk, num_appearances=3, fees_per_appearance=2500),
        )
        memo.refresh_from_db()
        self.assertEqual(
            memo.total_fees, memo_fees.resolve_memo_fees(memo).total_fees
        )


# ---------------------------------------------------------------------------
# Q1 / D3 (R-MEMO-1): custom total of 0 with line customs stores the SUM
# ---------------------------------------------------------------------------

class D3CustomTotalZeroTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter = seed_matter(self.profile)

    def test_create_custom_total_zero_with_line_customs_stores_sum(self):
        memo = memos.create_memo(
            self.profile,
            base_input(
                self.matter.pk,
                custom_total_fees=0,
                custom_fees_appearances=1000,
                custom_fees_conferences=500,
                custom_fees_misc=250,
            ),
        )
        # custom_total_fees=0 is NOT an override (D3); the stored total is the sum.
        self.assertEqual(memo.total_fees, Decimal("1750.00"))
        self.assertEqual(
            memo.total_fees, memo_fees.resolve_memo_fees(memo).total_fees
        )

    def test_update_custom_total_zero_with_line_customs_stores_sum(self):
        memo = memos.create_memo(self.profile, base_input(self.matter.pk))
        memos.update_memo(
            self.profile,
            memo.pk,
            base_input(
                self.matter.pk,
                custom_total_fees=0,
                custom_fees_appearances=1200,
                custom_fees_conferences=0,
                custom_fees_misc=300,
            ),
        )
        memo.refresh_from_db()
        # Line custom of exactly 0 IS a real override for that line (conferences).
        self.assertEqual(memo.total_fees, Decimal("1500.00"))


# ---------------------------------------------------------------------------
# Q5 (R-MEMO-2): real calendar date validation on a non-draft save
# ---------------------------------------------------------------------------

class Q5RealDateTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter = seed_matter(self.profile)

    def test_impossible_month_rejected_on_non_draft(self):
        with self.assertRaises(FeesError) as ctx:
            memos.create_memo(
                self.profile, base_input(self.matter.pk, date="2026-13-40")
            )
        self.assertEqual(ctx.exception.code, "INVALID_MEMO")

    def test_impossible_day_rejected_on_non_draft(self):
        with self.assertRaises(FeesError) as ctx:
            memos.create_memo(
                self.profile, base_input(self.matter.pk, date="2026-02-30")
            )
        self.assertEqual(ctx.exception.code, "INVALID_MEMO")

    def test_draft_allows_a_bad_or_empty_date(self):
        # A draft skips validation entirely.
        draft = memos.save_draft(self.profile, base_input(self.matter.pk, date=""))
        self.assertTrue(draft.is_draft)

    def test_valid_date_passes(self):
        memo = memos.create_memo(
            self.profile, base_input(self.matter.pk, date="2026-02-28")
        )
        self.assertEqual(str(memo.date), "2026-02-28")


# ---------------------------------------------------------------------------
# R-DATA-6: each mutating op bumps data_version exactly once; reads never bump
# ---------------------------------------------------------------------------

class DataVersionTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter = seed_matter(self.profile)

    def test_create_bumps_once(self):
        FeesSettings.objects.create(profile=self.profile)
        before = data_version(self.profile)
        memos.create_memo(self.profile, base_input(self.matter.pk))
        self.assertEqual(data_version(self.profile), before + 1)

    def test_create_creates_settings_row_when_missing_and_bumps(self):
        self.assertIsNone(data_version(self.profile))
        memos.create_memo(self.profile, base_input(self.matter.pk))
        self.assertEqual(data_version(self.profile), 1)

    def test_update_bumps_once(self):
        memo = memos.create_memo(self.profile, base_input(self.matter.pk))
        before = data_version(self.profile)
        memos.update_memo(
            self.profile, memo.pk, base_input(self.matter.pk, num_appearances=5)
        )
        self.assertEqual(data_version(self.profile), before + 1)

    def test_finalize_bumps_once(self):
        draft = memos.save_draft(self.profile, base_input(self.matter.pk))
        before = data_version(self.profile)
        memos.finalize_draft(self.profile, draft.pk)
        self.assertEqual(data_version(self.profile), before + 1)

    def test_write_off_bumps_once(self):
        memo = memos.create_memo(self.profile, base_input(self.matter.pk))
        before = data_version(self.profile)
        memos.set_memo_written_off(self.profile, memo.pk, True)
        self.assertEqual(data_version(self.profile), before + 1)

    def test_delete_bumps_once(self):
        memo = memos.create_memo(self.profile, base_input(self.matter.pk))
        before = data_version(self.profile)
        memos.delete_memo(self.profile, memo.pk)
        self.assertEqual(data_version(self.profile), before + 1)

    def test_reads_do_not_bump(self):
        memo = memos.create_memo(self.profile, base_input(self.matter.pk))
        before = data_version(self.profile)
        memos.get_memo(self.profile, memo.pk)
        memos.create_based_on(self.profile, memo.pk)
        memos.preview_number(self.profile, "2026-07-15")
        self.assertEqual(data_version(self.profile), before)


# ---------------------------------------------------------------------------
# Property tests (seeded random.Random loop; U8: no Hypothesis)
# ---------------------------------------------------------------------------

class MemoPropertyTests(TestCase):
    """Seeded port of ``memoService.property.test.ts`` (200 cases)."""

    SEED = 52025
    RUNS = 200

    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter = seed_matter(self.profile)

    def test_stored_total_always_equals_resolve_of_stored_columns(self):
        rng = random.Random(self.SEED)
        for _ in range(self.RUNS):
            n_app = rng.randint(0, 50)
            f_app = round(rng.uniform(0, 100000), 2)
            n_conf = rng.randint(0, 50)
            f_conf = round(rng.uniform(0, 100000), 2)
            misc = round(rng.uniform(0, 100000), 2)
            use_custom_total = rng.random() < 0.3
            over = dict(
                date="2026-07-15",
                num_appearances=n_app,
                fees_per_appearance=f_app,
                num_conferences=n_conf,
                fees_per_conference=f_conf,
                fees_misc_drafting=misc,
            )
            if use_custom_total:
                # A real positive override (0 would be "no override" per D3).
                over["custom_total_fees"] = round(rng.uniform(1, 500000), 2)
            memo = memos.create_memo(self.profile, base_input(self.matter.pk, **over))
            memo.refresh_from_db()
            self.assertEqual(
                memo.total_fees, memo_fees.resolve_memo_fees(memo).total_fees
            )

    def test_delete_removes_target_and_leaves_others_intact(self):
        rng = random.Random(self.SEED + 1)
        survivors = []
        for _ in range(20):
            memo = memos.create_memo(
                self.profile,
                base_input(self.matter.pk, num_appearances=rng.randint(1, 5)),
            )
            survivors.append(memo.pk)
        # Delete a random subset and confirm the rest survive.
        rng.shuffle(survivors)
        to_delete = survivors[:8]
        remaining = survivors[8:]
        payments = {}
        for pk in to_delete:
            memo = Memo.objects.get(pk=pk)
            pay = make_payment(self.profile, 100)
            allocate(self.profile, pay, memo, 100)
            payments[pk] = pay.pk
        for pk in to_delete:
            memos.delete_memo(self.profile, pk)
        for pk in to_delete:
            self.assertFalse(Memo.objects.filter(pk=pk).exists())
            self.assertFalse(Payment.objects.filter(pk=payments[pk]).exists())
        for pk in remaining:
            self.assertTrue(Memo.objects.filter(pk=pk).exists())

    def test_write_off_toggling_never_changes_payments(self):
        rng = random.Random(self.SEED + 2)
        memo = memos.create_memo(self.profile, base_input(self.matter.pk))
        pay = make_payment(self.profile, 1000)
        allocate(self.profile, pay, memo, 1000)
        memo.amount_paid = Decimal("1000.00")  # partial, so write-off allowed
        memo.save(update_fields=["amount_paid"])
        for _ in range(30):
            flag = rng.random() < 0.5
            memos.set_memo_written_off(self.profile, memo.pk, flag)
            self.assertTrue(Payment.objects.filter(pk=pay.pk).exists())
            self.assertEqual(
                Allocation.objects.filter(memo_id=memo.pk).count(), 1
            )

    def test_create_based_on_preserves_fields_and_blanks_date(self):
        rng = random.Random(self.SEED + 3)
        for _ in range(30):
            n_app = rng.randint(0, 100)
            f_app = round(rng.uniform(0, 50000), 2)
            client = f"client-{rng.randint(0, 999)}"
            src = memos.create_memo(
                self.profile,
                base_input(
                    self.matter.pk,
                    num_appearances=n_app,
                    fees_per_appearance=f_app,
                    client=client,
                ),
            )
            form = memos.create_based_on(self.profile, src.pk)
            self.assertEqual(form["date"], "")
            self.assertEqual(form["matter_id"], self.matter.pk)
            self.assertEqual(form["num_appearances"], n_app)
            self.assertEqual(form["client"], client)
            self.assertNotIn("id", form)
            self.assertNotIn("memo_number", form)


# ---------------------------------------------------------------------------
# Signature flag (item 2.3)
# ---------------------------------------------------------------------------

class IncludeSignatureTests(TestCase):
    def setUp(self):
        self.profile = fees_profile("Sig-Memo")
        _, _, self.matter = seed_matter(self.profile)

    def test_defaults_to_off_and_is_stored_when_given(self):
        plain = memos.create_memo(self.profile, base_input(self.matter.pk))
        ticked = memos.create_memo(self.profile, base_input(self.matter.pk, include_signature=True))
        self.assertFalse(plain.include_signature)
        self.assertTrue(ticked.include_signature)
        self.assertTrue(memos.get_memo(self.profile, ticked.pk)["include_signature"])

    def test_update_changes_it_and_leaves_it_alone_when_not_sent(self):
        memo = memos.create_memo(self.profile, base_input(self.matter.pk))
        memos.update_memo(self.profile, memo.pk, base_input(self.matter.pk, include_signature=True))
        self.assertTrue(Memo.objects.get(pk=memo.pk).include_signature)
        memos.update_memo(self.profile, memo.pk, base_input(self.matter.pk))
        self.assertTrue(Memo.objects.get(pk=memo.pk).include_signature)
        memos.update_memo(self.profile, memo.pk, base_input(self.matter.pk, include_signature=False))
        self.assertFalse(Memo.objects.get(pk=memo.pk).include_signature)

    def test_create_based_on_copies_the_flag(self):
        memo = memos.create_memo(self.profile, base_input(self.matter.pk, include_signature=True))
        self.assertTrue(memos.create_based_on(self.profile, memo.pk)["include_signature"])


# ---------------------------------------------------------------------------
# Move a memo to another matter (item 2.6)
# ---------------------------------------------------------------------------

class MoveMemoTests(TestCase):
    def setUp(self):
        self.profile = fees_profile("Move-Memo")
        self.firm, self.group, self.matter = seed_matter(self.profile)
        self.firm2 = Firm.objects.create(profile=self.profile, name="Other firm")
        self.group2 = Group.objects.create(profile=self.profile, firm=self.firm2, name="Other group")
        self.target = Matter.objects.create(
            profile=self.profile, firm=self.firm2, group=self.group2, name="Target matter"
        )
        self.memo = memos.create_memo(self.profile, base_input(self.matter.pk))

    def test_matter_firm_and_group_follow_the_target(self):
        moved = memos.move_memo(self.profile, self.memo.pk, self.target.pk)
        saved = Memo.objects.get(pk=self.memo.pk)
        self.assertEqual(moved.pk, self.memo.pk)
        self.assertEqual(
            (saved.matter_id, saved.firm_id, saved.group_id),
            (self.target.pk, self.firm2.pk, self.group2.pk),
        )

    def test_number_year_totals_and_payments_are_untouched(self):
        pay = Payment.objects.create(
            profile=self.profile, amount=100, date_of_payment=datetime.date(2026, 8, 1)
        )
        Allocation.objects.create(payment=pay, memo=self.memo, profile=self.profile, amount=100)
        Memo.objects.filter(pk=self.memo.pk).update(amount_paid=100, amount_received=100)
        before = Memo.objects.get(pk=self.memo.pk)
        memos.move_memo(self.profile, self.memo.pk, self.target.pk)
        after = Memo.objects.get(pk=self.memo.pk)
        for field in (
            "memo_number", "financial_year", "seq", "date", "total_fees", "amount_paid",
            "amount_received", "amount_tds", "addressee_line1", "num_appearances",
        ):
            self.assertEqual(getattr(after, field), getattr(before, field), field)
        self.assertEqual(Allocation.objects.filter(memo_id=self.memo.pk).count(), 1)
        self.assertTrue(Payment.objects.filter(pk=pay.pk).exists())

    def test_an_archived_target_is_refused(self):
        Matter.objects.filter(pk=self.target.pk).update(is_archived=True)
        with self.assertRaises(FeesError) as ctx:
            memos.move_memo(self.profile, self.memo.pk, self.target.pk)
        self.assertEqual(ctx.exception.code, "MATTER_ARCHIVED")
        self.assertEqual(Memo.objects.get(pk=self.memo.pk).matter_id, self.matter.pk)

    def test_a_target_in_another_profile_is_not_found(self):
        other = fees_profile("Move-Other")
        _, _, foreign = seed_matter(other)
        with self.assertRaises(FeesError) as ctx:
            memos.move_memo(self.profile, self.memo.pk, foreign.pk)
        self.assertEqual(ctx.exception.code, "MATTER_NOT_FOUND")
        self.assertEqual(Memo.objects.get(pk=self.memo.pk).matter_id, self.matter.pk)

    def test_a_memo_in_another_profile_is_not_found(self):
        other = fees_profile("Move-Other-2")
        with self.assertRaises(FeesError) as ctx:
            memos.move_memo(other, self.memo.pk, self.target.pk)
        self.assertEqual(ctx.exception.code, "MEMO_NOT_FOUND")

    def test_bumps_the_data_version_once(self):
        before = data_version(self.profile)
        memos.move_memo(self.profile, self.memo.pk, self.target.pk)
        self.assertEqual(data_version(self.profile), before + 1)

    def test_a_refused_move_does_not_bump_the_data_version(self):
        Matter.objects.filter(pk=self.target.pk).update(is_archived=True)
        before = data_version(self.profile)
        with self.assertRaises(FeesError):
            memos.move_memo(self.profile, self.memo.pk, self.target.pk)
        self.assertEqual(data_version(self.profile), before)

    def test_a_draft_can_be_moved_too(self):
        draft = memos.save_draft(self.profile, {"matter_id": self.matter.pk, "addressee_line1": "D"})
        memos.move_memo(self.profile, draft.pk, self.target.pk)
        saved = Memo.objects.get(pk=draft.pk)
        self.assertEqual((saved.matter_id, saved.firm_id, saved.group_id), (self.target.pk, self.firm2.pk, self.group2.pk))
        self.assertIsNone(saved.memo_number)
