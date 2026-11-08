"""Payment and allocation tests for the Fee Register (T2.6, R-PAY-1 to R-PAY-7, R-DATA-4, R-DATA-6).

Ports ``paymentService.test.ts`` (auto TDS, validation, add-to-memo, add,
add-unaccounted, assign, update incl. the Q3 case, delete, per-memo share),
``paymentService.property.test.ts`` (the aggregate-status property becomes a
seeded ``random.Random`` run, U8: no Hypothesis) and ``paymentPrefill.test.ts``
(a table test of the pure ``payment_prefill`` helper).

Adds the key R-DATA-4 invariant as a SEEDED random operation-sequence test
(~180 steps of add / update / assign / delete across a few memos) that after
every step recomputes ``amount_paid`` / ``amount_received`` / ``amount_tds`` from
the ``Allocation`` table and asserts they equal the stored memo columns (the
same style as the memo-service property test). Also an explicit Q3 test covering
omitted vs explicit-``[]`` vs 1-existing vs 2+-existing.

These tests use the ORM, so Django ``TestCase`` is used and everything is scoped
to a ``Profile(program="fees")``. Memos are created via ``memos.create_memo`` so
``total_fees`` is stored; the firm / group / matter helpers mirror
``test_memos.py``.
"""
import random
from decimal import Decimal

from django.test import TestCase

from accounts.models import Profile
from accounts.suite import KEY_FEES
from fees.errors import FeesError
from fees.models import Allocation, BankAccount, FeesSettings, Firm, Group, Matter, Memo
from fees.services import memos, payments
from fees.services.money import round2


def fees_profile(name="Ziyad-Fees"):
    return Profile.objects.create(program=KEY_FEES, name=name)


def seed_matter(profile, firm_name="Firm", matter_name="Matter"):
    firm = Firm.objects.create(profile=profile, name=firm_name)
    group = Group.objects.create(profile=profile, firm=firm, name="Group")
    matter = Matter.objects.create(
        profile=profile, firm=firm, group=group, name=matter_name
    )
    return firm, group, matter


def memo_with_total(profile, matter, total, date="2026-07-15"):
    """Creates a memo whose whole total is a single misc-drafting fee."""
    memo = memos.create_memo(
        profile,
        dict(
            date=date,
            matter_id=matter.pk,
            addressee_line1="A",
            num_appearances=0,
            fees_per_appearance=0,
            num_conferences=0,
            fees_per_conference=0,
            fees_misc_drafting=total,
        ),
    )
    return memo


def data_version(profile):
    return (
        FeesSettings.objects.filter(profile=profile)
        .values_list("data_version", flat=True)
        .first()
    )


def stored(memo_id):
    memo = Memo.objects.get(pk=memo_id)
    return (memo.amount_paid, memo.amount_received, memo.amount_tds)


def recomputed_from_allocations(memo_id):
    """Independently recomputes the three stored amounts from the Allocation table."""
    net = Decimal("0")
    tds = Decimal("0")
    for alloc in Allocation.objects.filter(memo_id=memo_id):
        net += alloc.amount
        tds += alloc.tds_amount
    net = round2(net)
    tds = round2(tds)
    return (round2(net + tds), net, tds)


# ---------------------------------------------------------------------------
# Auto TDS gross-up (R-PAY-1) -- distinct from memo net-of-tds
# ---------------------------------------------------------------------------

class AutoTdsTests(TestCase):
    def test_net_90_at_10_percent_grosses_to_tds_10(self):
        self.assertEqual(payments.compute_auto_tds(90, 10), Decimal("10.00"))

    def test_net_9000_at_10_percent_grosses_to_tds_1000(self):
        self.assertEqual(payments.compute_auto_tds(9000, 10), Decimal("1000.00"))

    def test_net_45000_at_10_percent_grosses_to_tds_5000(self):
        self.assertEqual(payments.compute_auto_tds(45000, 10), Decimal("5000.00"))

    def test_rate_zero_gives_zero(self):
        self.assertEqual(payments.compute_auto_tds(1000, 0), Decimal("0.00"))

    def test_rate_100_or_more_gives_zero(self):
        self.assertEqual(payments.compute_auto_tds(1000, 100), Decimal("0.00"))
        self.assertEqual(payments.compute_auto_tds(1000, 150), Decimal("0.00"))

    def test_negative_rate_gives_zero(self):
        self.assertEqual(payments.compute_auto_tds(1000, -5), Decimal("0.00"))

    def test_resolve_tds_auto_on_uses_grossup(self):
        self.assertEqual(
            payments.resolve_tds_amount(45000, 10, True, None), Decimal("5000.00")
        )

    def test_resolve_tds_auto_off_takes_as_sent(self):
        self.assertEqual(
            payments.resolve_tds_amount(45000, 10, False, 3000), Decimal("3000.00")
        )

    def test_resolve_tds_auto_off_missing_is_zero(self):
        self.assertEqual(
            payments.resolve_tds_amount(45000, 10, False, None), Decimal("0.00")
        )

    def test_gross_helper(self):
        self.assertEqual(payments.gross(45000, 5000), Decimal("50000.00"))


# ---------------------------------------------------------------------------
# Validation (R-PAY-2)
# ---------------------------------------------------------------------------

class ValidatePaymentTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter = seed_matter(self.profile)
        self.memo = memo_with_total(self.profile, self.matter, 5000)

    def test_zero_amount_rejected(self):
        with self.assertRaises(FeesError) as ctx:
            payments.add_payment_to_memo(
                self.profile, self.memo.pk, {"amount": 0, "date_of_payment": "2026-08-01"}
            )
        self.assertEqual(ctx.exception.code, "INVALID_PAYMENT")

    def test_negative_amount_rejected(self):
        with self.assertRaises(FeesError) as ctx:
            payments.add_payment_to_memo(
                self.profile, self.memo.pk, {"amount": -5, "date_of_payment": "2026-08-01"}
            )
        self.assertEqual(ctx.exception.code, "INVALID_PAYMENT")

    def test_missing_date_rejected(self):
        with self.assertRaises(FeesError) as ctx:
            payments.add_payment_to_memo(
                self.profile, self.memo.pk, {"amount": 100, "date_of_payment": ""}
            )
        self.assertEqual(ctx.exception.code, "INVALID_PAYMENT")

    def test_impossible_date_rejected(self):
        # R-PAY-2 port improvement: a real calendar date, not just a prefix.
        with self.assertRaises(FeesError) as ctx:
            payments.add_payment_to_memo(
                self.profile, self.memo.pk, {"amount": 100, "date_of_payment": "2026-13-40"}
            )
        self.assertEqual(ctx.exception.code, "INVALID_PAYMENT")

    def test_rate_out_of_range_rejected(self):
        with self.assertRaises(FeesError) as ctx:
            payments.add_payment_to_memo(
                self.profile,
                self.memo.pk,
                {"amount": 100, "date_of_payment": "2026-08-01", "tds_rate": 100},
            )
        self.assertEqual(ctx.exception.code, "INVALID_PAYMENT")
        with self.assertRaises(FeesError) as ctx:
            payments.add_payment_to_memo(
                self.profile,
                self.memo.pk,
                {"amount": 100, "date_of_payment": "2026-08-01", "tds_rate": -1},
            )
        self.assertEqual(ctx.exception.code, "INVALID_PAYMENT")

    def test_valid_rate_passes(self):
        pay = payments.add_payment_to_memo(
            self.profile,
            self.memo.pk,
            {"amount": 100, "date_of_payment": "2026-08-01", "tds_rate": 10},
        )
        self.assertEqual(pay["amount"], Decimal("100.00"))


# ---------------------------------------------------------------------------
# Add to memo (R-PAY-3)
# ---------------------------------------------------------------------------

class AddPaymentToMemoTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter = seed_matter(self.profile)

    def test_single_allocation_and_stored_amounts(self):
        memo = memo_with_total(self.profile, self.matter, 5000)
        pay = payments.add_payment_to_memo(
            self.profile, memo.pk, {"amount": 1000, "date_of_payment": "2026-08-01"}
        )
        self.assertEqual(pay["amount"], Decimal("1000.00"))
        self.assertEqual(pay["memo_id"], memo.pk)
        self.assertEqual(len(pay["allocations"]), 1)
        self.assertEqual(stored(memo.pk), (Decimal("1000.00"), Decimal("1000.00"), Decimal("0.00")))

    def test_auto_tds_single_payment_clears_memo(self):
        memo = memo_with_total(self.profile, self.matter, 50000)
        pay = payments.add_payment_to_memo(
            self.profile,
            memo.pk,
            {"amount": 45000, "tds_rate": 10, "auto_tds": True, "date_of_payment": "2026-08-01"},
        )
        self.assertEqual(pay["tds_amount"], Decimal("5000.00"))
        self.assertEqual(pay["gross_amount"], Decimal("50000.00"))
        detail = memos.get_memo(self.profile, memo.pk)
        self.assertEqual(detail["status"], "Paid")
        self.assertEqual(detail["amount_paid"], Decimal("50000.00"))
        self.assertEqual(detail["amount_received"], Decimal("45000.00"))
        self.assertEqual(detail["amount_tds"], Decimal("5000.00"))

    def test_manual_tds_off_uses_entered_amount(self):
        memo = memo_with_total(self.profile, self.matter, 50000)
        pay = payments.add_payment_to_memo(
            self.profile,
            memo.pk,
            {
                "amount": 45000,
                "tds_rate": 10,
                "auto_tds": False,
                "tds_amount": 3000,
                "date_of_payment": "2026-08-01",
            },
        )
        self.assertEqual(pay["tds_amount"], Decimal("3000.00"))
        self.assertEqual(pay["gross_amount"], Decimal("48000.00"))
        self.assertEqual(memos.get_memo(self.profile, memo.pk)["status"], "Unpaid")

    def test_explicit_allocation_list_used(self):
        memo = memo_with_total(self.profile, self.matter, 5000)
        other = memo_with_total(self.profile, self.matter, 3000, date="2026-07-16")
        pay = payments.add_payment_to_memo(
            self.profile,
            memo.pk,
            {
                "amount": 8000,
                "date_of_payment": "2026-08-01",
                "allocations": [
                    {"memo_id": memo.pk, "amount": 5000, "tds_amount": 0},
                    {"memo_id": other.pk, "amount": 3000, "tds_amount": 0},
                ],
            },
        )
        self.assertEqual(len(pay["allocations"]), 2)
        self.assertEqual(stored(memo.pk)[1], Decimal("5000.00"))
        self.assertEqual(stored(other.pk)[1], Decimal("3000.00"))

    def test_multiple_payments_partial_then_full(self):
        memo = memo_with_total(self.profile, self.matter, 1000)
        payments.add_payment_to_memo(
            self.profile, memo.pk, {"amount": 400, "date_of_payment": "2026-08-01"}
        )
        self.assertEqual(memos.get_memo(self.profile, memo.pk)["status"], "Unpaid")
        payments.add_payment_to_memo(
            self.profile, memo.pk, {"amount": 600, "date_of_payment": "2026-09-01"}
        )
        self.assertEqual(memos.get_memo(self.profile, memo.pk)["status"], "Paid")
        self.assertEqual(len(payments.list_payments_for_memo(self.profile, memo.pk)), 2)

    def test_memo_not_found(self):
        with self.assertRaises(FeesError) as ctx:
            payments.add_payment_to_memo(
                self.profile, 999999, {"amount": 100, "date_of_payment": "2026-08-01"}
            )
        self.assertEqual(ctx.exception.code, "MEMO_NOT_FOUND")

    def test_memo_from_other_profile_not_found(self):
        other = fees_profile("Other-Fees")
        _, _, other_matter = seed_matter(other)
        other_memo = memo_with_total(other, other_matter, 1000)
        with self.assertRaises(FeesError) as ctx:
            payments.add_payment_to_memo(
                self.profile, other_memo.pk, {"amount": 100, "date_of_payment": "2026-08-01"}
            )
        self.assertEqual(ctx.exception.code, "MEMO_NOT_FOUND")


# ---------------------------------------------------------------------------
# Add (Feebook, 0..n allocations) and add_unaccounted (R-PAY-3)
# ---------------------------------------------------------------------------

class AddPaymentTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter = seed_matter(self.profile)
        self.a = memo_with_total(self.profile, self.matter, 5000)
        self.b = memo_with_total(self.profile, self.matter, 3000, date="2026-07-16")

    def test_split_across_two_memos_clears_both(self):
        payments.add_payment(
            self.profile,
            {
                "amount": 8000,
                "date_of_payment": "2026-08-01",
                "allocations": [
                    {"memo_id": self.a.pk, "amount": 5000, "tds_amount": 0},
                    {"memo_id": self.b.pk, "amount": 3000, "tds_amount": 0},
                ],
            },
        )
        self.assertEqual(memos.get_memo(self.profile, self.a.pk)["status"], "Paid")
        self.assertEqual(memos.get_memo(self.profile, self.a.pk)["amount_paid"], Decimal("5000.00"))
        self.assertEqual(memos.get_memo(self.profile, self.b.pk)["status"], "Paid")
        self.assertEqual(memos.get_memo(self.profile, self.b.pk)["amount_paid"], Decimal("3000.00"))

    def test_more_than_five_allocations_save(self):
        extra = [memo_with_total(self.profile, self.matter, 100) for _ in range(5)]
        memo_list = [self.a, self.b] + extra
        pay = payments.add_payment(
            self.profile,
            {
                "amount": 8500,
                "date_of_payment": "2026-08-01",
                "allocations": [
                    {"memo_id": m.pk, "amount": {self.a.pk: 5000, self.b.pk: 3000}.get(m.pk, 100), "tds_amount": 0}
                    for m in memo_list
                ],
            },
        )
        self.assertEqual(len(pay["allocations"]), 7)
        for m in memo_list:
            self.assertEqual(memos.get_memo(self.profile, m.pk)["status"], "Paid")

    def test_any_number_of_allocations_pass_validation(self):
        rows = [{"memo_id": self.a.pk, "amount": 1, "tds_amount": 0}] * 1000
        payments.validate_payment({"amount": 1000, "date_of_payment": "2026-08-01", "allocations": rows})
        self.assertFalse(hasattr(payments, "MAX_ALLOCATIONS"))

    def test_no_allocations_is_unaccounted(self):
        pay = payments.add_payment(
            self.profile, {"amount": 1000, "date_of_payment": "2026-08-01"}
        )
        self.assertIsNone(pay["memo_id"])
        self.assertEqual(len(pay["allocations"]), 0)
        self.assertEqual(memos.get_memo(self.profile, self.a.pk)["amount_paid"], Decimal("0.00"))

    def test_add_unaccounted_always_empty(self):
        pay = payments.add_unaccounted_payment(
            self.profile,
            {
                "amount": 1000,
                "date_of_payment": "2026-08-01",
                "allocations": [{"memo_id": self.a.pk, "amount": 1000, "tds_amount": 0}],
            },
        )
        # add_unaccounted ignores any supplied allocations.
        self.assertEqual(len(pay["allocations"]), 0)
        self.assertEqual(stored(self.a.pk)[0], Decimal("0.00"))

    def test_per_memo_share_surfaced(self):
        payments.add_payment(
            self.profile,
            {
                "amount": 8000,
                "date_of_payment": "2026-08-01",
                "allocations": [
                    {"memo_id": self.a.pk, "amount": 5000, "tds_amount": 0},
                    {"memo_id": self.b.pk, "amount": 3000, "tds_amount": 0},
                ],
            },
        )
        for_a = payments.list_payments_for_memo(self.profile, self.a.pk)
        self.assertEqual(len(for_a), 1)
        self.assertEqual(for_a[0]["amount"], Decimal("5000.00"))
        self.assertEqual(for_a[0]["memo_id"], self.a.pk)


# ---------------------------------------------------------------------------
# Assign unaccounted to memo (R-PAY-3)
# ---------------------------------------------------------------------------

class AssignPaymentTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter = seed_matter(self.profile)
        self.memo = memo_with_total(self.profile, self.matter, 5000)

    def test_unaccounted_then_assigned(self):
        pay = payments.add_unaccounted_payment(
            self.profile, {"amount": 5000, "date_of_payment": "2026-08-01"}
        )
        self.assertIsNone(pay["memo_id"])
        assigned = payments.assign_payment_to_memo(self.profile, pay["id"], self.memo.pk)
        self.assertEqual(assigned["memo_id"], self.memo.pk)
        self.assertEqual(memos.get_memo(self.profile, self.memo.pk)["status"], "Paid")

    def test_assign_replaces_existing_allocations(self):
        other = memo_with_total(self.profile, self.matter, 3000, date="2026-07-16")
        pay = payments.add_payment(
            self.profile,
            {
                "amount": 5000,
                "date_of_payment": "2026-08-01",
                "allocations": [
                    {"memo_id": other.pk, "amount": 3000, "tds_amount": 0},
                    {"memo_id": self.memo.pk, "amount": 2000, "tds_amount": 0},
                ],
            },
        )
        payments.assign_payment_to_memo(self.profile, pay["id"], self.memo.pk)
        # Now wholly on self.memo; the other memo is reset to 0.
        self.assertEqual(stored(self.memo.pk)[1], Decimal("5000.00"))
        self.assertEqual(stored(other.pk), (Decimal("0.00"), Decimal("0.00"), Decimal("0.00")))

    def test_assign_keeps_payment_tds(self):
        pay = payments.add_unaccounted_payment(
            self.profile,
            {"amount": 45000, "tds_rate": 10, "auto_tds": True, "date_of_payment": "2026-08-01"},
        )
        payments.assign_payment_to_memo(self.profile, pay["id"], self.memo.pk)
        self.assertEqual(stored(self.memo.pk), (Decimal("50000.00"), Decimal("45000.00"), Decimal("5000.00")))

    def test_assign_payment_not_found(self):
        with self.assertRaises(FeesError) as ctx:
            payments.assign_payment_to_memo(self.profile, 123456, self.memo.pk)
        self.assertEqual(ctx.exception.code, "INVALID_PAYMENT")

    def test_assign_memo_not_found(self):
        pay = payments.add_unaccounted_payment(
            self.profile, {"amount": 100, "date_of_payment": "2026-08-01"}
        )
        with self.assertRaises(FeesError) as ctx:
            payments.assign_payment_to_memo(self.profile, pay["id"], 999999)
        self.assertEqual(ctx.exception.code, "MEMO_NOT_FOUND")


# ---------------------------------------------------------------------------
# Update and delete (R-PAY-4, R-PAY-3)
# ---------------------------------------------------------------------------

class UpdateAndDeleteTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter = seed_matter(self.profile)
        self.memo = memo_with_total(self.profile, self.matter, 1000)

    def test_update_fields_and_single_allocation_rebuilt(self):
        pay = payments.add_payment_to_memo(
            self.profile, self.memo.pk, {"amount": 100, "date_of_payment": "2026-08-01"}
        )
        updated = payments.update_payment(
            self.profile,
            pay["id"],
            {"amount": 250, "date_of_payment": "2026-08-02", "payee": "X"},
        )
        self.assertEqual(updated["amount"], Decimal("250.00"))
        self.assertEqual(updated["payee"], "X")
        # The single allocation is rebuilt to the new amount (omitted + 1 existing).
        self.assertEqual(stored(self.memo.pk)[1], Decimal("250.00"))

    def test_delete_removes_allocations_and_resets_memo(self):
        pay = payments.add_payment_to_memo(
            self.profile, self.memo.pk, {"amount": 100, "date_of_payment": "2026-08-01"}
        )
        payments.delete_payment(self.profile, pay["id"])
        self.assertEqual(len(payments.list_payments_for_memo(self.profile, self.memo.pk)), 0)
        self.assertEqual(stored(self.memo.pk), (Decimal("0.00"), Decimal("0.00"), Decimal("0.00")))

    def test_update_payment_not_found(self):
        with self.assertRaises(FeesError) as ctx:
            payments.update_payment(
                self.profile, 777, {"amount": 1, "date_of_payment": "2026-08-01"}
            )
        self.assertEqual(ctx.exception.code, "INVALID_PAYMENT")

    def test_delete_payment_not_found(self):
        with self.assertRaises(FeesError) as ctx:
            payments.delete_payment(self.profile, 777)
        self.assertEqual(ctx.exception.code, "INVALID_PAYMENT")


# ---------------------------------------------------------------------------
# Q3 re-derivation (R-PAY-4): omitted vs explicit [] vs 1-existing vs 2+-existing
# ---------------------------------------------------------------------------

class Q3UpdateRederivationTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter = seed_matter(self.profile)
        self.a = memo_with_total(self.profile, self.matter, 5000)
        self.b = memo_with_total(self.profile, self.matter, 3000, date="2026-07-16")

    def _split_payment(self):
        return payments.add_payment(
            self.profile,
            {
                "amount": 8000,
                "date_of_payment": "2026-08-01",
                "allocations": [
                    {"memo_id": self.a.pk, "amount": 5000, "tds_amount": 0},
                    {"memo_id": self.b.pk, "amount": 3000, "tds_amount": 0},
                ],
            },
        )

    def test_omitted_with_two_allocations_keeps_them(self):
        pay = self._split_payment()
        # Change only payee / date; allocations key omitted -> both kept (Q3 FIX).
        payments.update_payment(
            self.profile,
            pay["id"],
            {"amount": 8000, "date_of_payment": "2026-08-05", "payee": "New"},
        )
        self.assertEqual(stored(self.a.pk)[1], Decimal("5000.00"))
        self.assertEqual(stored(self.b.pk)[1], Decimal("3000.00"))
        reloaded = payments.get_payment(self.profile, pay["id"])
        self.assertEqual(len(reloaded["allocations"]), 2)
        self.assertEqual(reloaded["payee"], "New")

    def test_explicit_empty_list_makes_unaccounted(self):
        pay = self._split_payment()
        payments.update_payment(
            self.profile,
            pay["id"],
            {"amount": 8000, "date_of_payment": "2026-08-05", "allocations": []},
        )
        self.assertEqual(stored(self.a.pk), (Decimal("0.00"), Decimal("0.00"), Decimal("0.00")))
        self.assertEqual(stored(self.b.pk), (Decimal("0.00"), Decimal("0.00"), Decimal("0.00")))
        self.assertEqual(len(payments.get_payment(self.profile, pay["id"])["allocations"]), 0)

    def test_omitted_with_one_allocation_rebuilds_with_new_amount(self):
        pay = payments.add_payment_to_memo(
            self.profile, self.a.pk, {"amount": 2000, "date_of_payment": "2026-08-01"}
        )
        payments.update_payment(
            self.profile,
            pay["id"],
            {"amount": 4000, "date_of_payment": "2026-08-02"},
        )
        self.assertEqual(stored(self.a.pk)[1], Decimal("4000.00"))

    def test_omitted_with_zero_allocations_stays_unaccounted(self):
        pay = payments.add_unaccounted_payment(
            self.profile, {"amount": 2000, "date_of_payment": "2026-08-01"}
        )
        payments.update_payment(
            self.profile,
            pay["id"],
            {"amount": 4000, "date_of_payment": "2026-08-02", "payee": "Y"},
        )
        self.assertEqual(len(payments.get_payment(self.profile, pay["id"])["allocations"]), 0)

    def test_explicit_new_list_replaces(self):
        pay = self._split_payment()
        payments.update_payment(
            self.profile,
            pay["id"],
            {
                "amount": 5000,
                "date_of_payment": "2026-08-05",
                "allocations": [{"memo_id": self.a.pk, "amount": 5000, "tds_amount": 0}],
            },
        )
        self.assertEqual(stored(self.a.pk)[1], Decimal("5000.00"))
        self.assertEqual(stored(self.b.pk), (Decimal("0.00"), Decimal("0.00"), Decimal("0.00")))


# ---------------------------------------------------------------------------
# listPaymentsForMemo ordering and payees_for_matters grouping (R-PAY-6)
# ---------------------------------------------------------------------------

class ListPaymentsForMemoTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter = seed_matter(self.profile)
        self.memo = memo_with_total(self.profile, self.matter, 10000)

    def test_ordered_by_date_then_id(self):
        payments.add_payment_to_memo(
            self.profile, self.memo.pk, {"amount": 100, "date_of_payment": "2026-09-01"}
        )
        payments.add_payment_to_memo(
            self.profile, self.memo.pk, {"amount": 200, "date_of_payment": "2026-08-01"}
        )
        rows = payments.list_payments_for_memo(self.profile, self.memo.pk)
        dates = [r["date_of_payment"] for r in rows]
        self.assertEqual(dates, sorted(dates))


class PayeesForMattersTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter = seed_matter(self.profile)
        self.memo = memo_with_total(self.profile, self.matter, 100000)

    def test_distinct_case_insensitive_ordered(self):
        payments.add_payment_to_memo(
            self.profile,
            self.memo.pk,
            {"amount": 100, "date_of_payment": "2026-08-01", "payee": "Acme"},
        )
        payments.add_payment_to_memo(
            self.profile,
            self.memo.pk,
            {"amount": 100, "date_of_payment": "2026-09-01", "payee": "acme"},
        )
        payments.add_payment_to_memo(
            self.profile,
            self.memo.pk,
            {"amount": 100, "date_of_payment": "2026-10-01", "payee": "Beta"},
        )
        result = payments.payees_for_matters(self.profile, [self.matter.pk])
        # Grouped case-insensitively: Acme (count 2) and Beta (count 1).
        payees = [r["payee"] for r in result]
        self.assertEqual(len(result), 2)
        # Beta has the most recent payment, so it sorts first.
        self.assertEqual(payees[0], "Beta")
        acme = next(r for r in result if r["payee"].lower() == "acme")
        self.assertEqual(acme["count"], 2)

    def test_blank_payees_ignored(self):
        payments.add_payment_to_memo(
            self.profile,
            self.memo.pk,
            {"amount": 100, "date_of_payment": "2026-08-01", "payee": "   "},
        )
        self.assertEqual(payments.payees_for_matters(self.profile, [self.matter.pk]), [])

    def test_empty_matter_ids(self):
        self.assertEqual(payments.payees_for_matters(self.profile, []), [])


# ---------------------------------------------------------------------------
# payment_prefill (R-PAY-7): port paymentPrefill.test.ts as a table test
# ---------------------------------------------------------------------------

class PaymentPrefillTests(TestCase):
    def test_table(self):
        cases = [
            # (mode, due, rate, amount, auto_tds, tds_amount)
            ("zero", 50000, 10, Decimal("0.00"), True, Decimal("0.00")),
            ("full", 50000, 10, Decimal("50000.00"), False, Decimal("0.00")),
            ("netOfTds", 50000, 10, Decimal("45000.00"), True, Decimal("0.00")),
            ("netOfTds", 12345, 10, Decimal("11110.50"), True, Decimal("0.00")),
            ("netOfTds", 8000, 0, Decimal("8000.00"), True, Decimal("0.00")),
            ("full", -300, 10, Decimal("0.00"), False, Decimal("0.00")),
            ("netOfTds", -300, 10, Decimal("0.00"), True, Decimal("0.00")),
        ]
        for mode, due, rate, amount, auto_tds, tds in cases:
            with self.subTest(mode=mode, due=due, rate=rate):
                out = payments.payment_prefill(mode, due, rate)
                self.assertEqual(out["amount"], amount)
                self.assertEqual(out["auto_tds"], auto_tds)
                self.assertEqual(out["tds_amount"], tds)


# ---------------------------------------------------------------------------
# Bank account carries through (scope / optional FK)
# ---------------------------------------------------------------------------

class BankAccountTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter = seed_matter(self.profile)
        self.memo = memo_with_total(self.profile, self.matter, 5000)

    def test_bank_account_id_stored(self):
        bank = BankAccount.objects.create(profile=self.profile, name="HDFC")
        pay = payments.add_payment_to_memo(
            self.profile,
            self.memo.pk,
            {"amount": 100, "date_of_payment": "2026-08-01", "bank_account_id": bank.pk},
        )
        self.assertEqual(pay["bank_account_id"], bank.pk)


# ---------------------------------------------------------------------------
# R-DATA-6: each mutating op bumps data_version once; reads never bump
# ---------------------------------------------------------------------------

class DataVersionTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter = seed_matter(self.profile)
        self.memo = memo_with_total(self.profile, self.matter, 5000)

    def test_add_to_memo_bumps_once(self):
        before = data_version(self.profile)
        payments.add_payment_to_memo(
            self.profile, self.memo.pk, {"amount": 100, "date_of_payment": "2026-08-01"}
        )
        self.assertEqual(data_version(self.profile), before + 1)

    def test_add_bumps_once(self):
        before = data_version(self.profile)
        payments.add_payment(
            self.profile, {"amount": 100, "date_of_payment": "2026-08-01"}
        )
        self.assertEqual(data_version(self.profile), before + 1)

    def test_assign_bumps_once(self):
        pay = payments.add_unaccounted_payment(
            self.profile, {"amount": 100, "date_of_payment": "2026-08-01"}
        )
        before = data_version(self.profile)
        payments.assign_payment_to_memo(self.profile, pay["id"], self.memo.pk)
        self.assertEqual(data_version(self.profile), before + 1)

    def test_update_bumps_once(self):
        pay = payments.add_payment_to_memo(
            self.profile, self.memo.pk, {"amount": 100, "date_of_payment": "2026-08-01"}
        )
        before = data_version(self.profile)
        payments.update_payment(
            self.profile, pay["id"], {"amount": 200, "date_of_payment": "2026-08-02"}
        )
        self.assertEqual(data_version(self.profile), before + 1)

    def test_delete_bumps_once(self):
        pay = payments.add_payment_to_memo(
            self.profile, self.memo.pk, {"amount": 100, "date_of_payment": "2026-08-01"}
        )
        before = data_version(self.profile)
        payments.delete_payment(self.profile, pay["id"])
        self.assertEqual(data_version(self.profile), before + 1)

    def test_reads_do_not_bump(self):
        pay = payments.add_payment_to_memo(
            self.profile, self.memo.pk, {"amount": 100, "date_of_payment": "2026-08-01"}
        )
        before = data_version(self.profile)
        payments.get_payment(self.profile, pay["id"])
        payments.list_payments_for_memo(self.profile, self.memo.pk)
        payments.payees_for_matters(self.profile, [self.matter.pk])
        payments.payment_prefill("full", 100, 10)
        self.assertEqual(data_version(self.profile), before)


# ---------------------------------------------------------------------------
# R-DATA-4: recompute_paid invariant under a seeded random operation sequence
# ---------------------------------------------------------------------------

class RecomputePaidPropertyTests(TestCase):
    """Seeded random sequence (U8: no Hypothesis). After every step the stored
    memo amounts must equal a fresh recompute from the Allocation table."""

    SEED = 72026
    STEPS = 180

    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter = seed_matter(self.profile)
        self.memos = [
            memo_with_total(self.profile, self.matter, 100000, date=f"2026-07-{d:02d}")
            for d in range(10, 15)
        ]
        self.memo_ids = [m.pk for m in self.memos]

    def _assert_invariant(self):
        for memo_id in self.memo_ids:
            self.assertEqual(
                stored(memo_id),
                recomputed_from_allocations(memo_id),
                msg=f"memo {memo_id} stored amounts drifted from allocations",
            )

    def test_stored_amounts_always_match_allocations(self):
        rng = random.Random(self.SEED)
        live_payment_ids = []
        for _step in range(self.STEPS):
            choice = rng.random()
            if choice < 0.4 or not live_payment_ids:
                # add: random allocations across 0..2 memos.
                n = rng.randint(0, 2)
                allocs = []
                for _ in range(n):
                    memo_id = rng.choice(self.memo_ids)
                    allocs.append(
                        {
                            "memo_id": memo_id,
                            "amount": round(rng.uniform(1, 5000), 2),
                            "tds_amount": round(rng.uniform(0, 500), 2),
                        }
                    )
                data = {
                    "amount": round(rng.uniform(1, 10000), 2),
                    "date_of_payment": "2026-08-01",
                }
                if allocs:
                    data["allocations"] = allocs
                pay = payments.add_payment(self.profile, data)
                live_payment_ids.append(pay["id"])
            elif choice < 0.65:
                # update: sometimes with explicit allocations, sometimes omitted.
                pid = rng.choice(live_payment_ids)
                data = {
                    "amount": round(rng.uniform(1, 10000), 2),
                    "date_of_payment": "2026-08-02",
                }
                if rng.random() < 0.6:
                    n = rng.randint(0, 2)
                    data["allocations"] = [
                        {
                            "memo_id": rng.choice(self.memo_ids),
                            "amount": round(rng.uniform(1, 5000), 2),
                            "tds_amount": round(rng.uniform(0, 500), 2),
                        }
                        for _ in range(n)
                    ]
                payments.update_payment(self.profile, pid, data)
            elif choice < 0.8:
                # assign to a random memo.
                pid = rng.choice(live_payment_ids)
                payments.assign_payment_to_memo(
                    self.profile, pid, rng.choice(self.memo_ids)
                )
            else:
                # delete.
                pid = rng.choice(live_payment_ids)
                payments.delete_payment(self.profile, pid)
                live_payment_ids.remove(pid)

            self._assert_invariant()

    def test_memo_losing_last_allocation_returns_to_zero(self):
        memo = self.memos[0]
        pay = payments.add_payment_to_memo(
            self.profile, memo.pk, {"amount": 100, "date_of_payment": "2026-08-01"}
        )
        self.assertEqual(stored(memo.pk)[0], Decimal("100.00"))
        payments.delete_payment(self.profile, pay["id"])
        self.assertEqual(stored(memo.pk), (Decimal("0.00"), Decimal("0.00"), Decimal("0.00")))


# ---------------------------------------------------------------------------
# Property port: aggregate payments drive the paid total (Property 19 style)
# ---------------------------------------------------------------------------

class AggregatePaymentPropertyTests(TestCase):
    SEED = 19019
    RUNS = 150

    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter = seed_matter(self.profile)

    def test_total_paid_equals_sum_of_payments(self):
        rng = random.Random(self.SEED)
        for _ in range(self.RUNS):
            total = rng.randint(1, 100000)
            memo = memo_with_total(self.profile, self.matter, total)
            amounts = [rng.randint(1, 100000) for _ in range(rng.randint(0, 6))]
            for amount in amounts:
                payments.add_payment_to_memo(
                    self.profile,
                    memo.pk,
                    {"amount": amount, "date_of_payment": "2026-08-01"},
                )
            expected = round2(sum(amounts))
            paid = stored(memo.pk)[0]
            self.assertEqual(paid, expected)
            status = memos.get_memo(self.profile, memo.pk)["status"]
            self.assertEqual(status, "Paid" if expected >= round2(total) else "Unpaid")
