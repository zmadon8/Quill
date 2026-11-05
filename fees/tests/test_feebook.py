"""Feebook read-service tests for the Fee Register (T3.2, R-RD-1, brief 6.2).

Ports ``feebookService.test.ts`` (the five tests: Single label and no secret
``payment_details`` key; Multiple label and the sibling memo group; the
unaccounted-only filter; unaccounted rows still shown when a FY filter is active;
and the FY filter keyed on the payment date, not the memo billing year) to
Django ``TestCase``, and adds explicit coverage for the Initial-FY cutoff and for
Q7 (the firm and group filters do NOT hide unaccounted payments).

Every list path asserts a tight ``assertNumQueries`` bound so a regression that
adds a per-row query (an N+1) fails: ``list_feebook`` with allocation rows is
four queries (settings, the per-payment memo-number grouping, the allocation
rows, the unaccounted rows), and two when ``unaccounted_only`` skips the
allocation query.

Everything is scoped to a ``Profile(program="fees")``. Memos are created via
``memos.create_memo`` (so ``total_fees`` is stored), single-memo payments via
``payments.add_payment_to_memo``, split payments via ``payments.add_payment`` and
unaccounted payments via ``payments.add_unaccounted_payment``; the firm / group /
matter helpers mirror ``test_payments.py`` and ``test_memo_lists.py``.
"""
from decimal import Decimal

from django.test import TestCase

from accounts.models import Profile
from accounts.suite import KEY_FEES
from fees.models import Firm, Group, Matter
from fees.services import feebook, memos, payments, settings


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
    return memos.create_memo(
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


# ---------------------------------------------------------------------------
# Single vs Multiple, payment_details exclusion (ports the first two tests)
# ---------------------------------------------------------------------------

class FeebookLabelTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, self.group, self.matter = seed_matter(self.profile)

    def test_single_label_and_never_exposes_payment_details(self):
        bank = settings.add_bank_account(self.profile, "HDFC")
        memo = memo_with_total(self.profile, self.matter, 1000)
        payments.add_payment_to_memo(
            self.profile,
            memo.pk,
            dict(
                amount=400,
                date_of_payment="2026-08-01",
                bank_account_id=bank.pk,
                payment_details="secret note",
            ),
        )
        payments.add_payment_to_memo(
            self.profile,
            memo.pk,
            dict(amount=600, date_of_payment="2026-09-01", bank_account_id=bank.pk),
        )
        rows = feebook.list_feebook(self.profile, {})
        self.assertEqual(len(rows), 2)
        # Each payment is allocated to one memo -> Single (regardless of coverage).
        self.assertTrue(all(r["payment_type"] == "Single" for r in rows))
        self.assertTrue(all(r["allocation_count"] == 1 for r in rows))
        self.assertEqual(rows[0]["bank_account_name"], "HDFC")
        self.assertEqual(rows[0]["memo_total"], Decimal("1000.00"))
        # The secret note must not appear on any feebook row.
        for row in rows:
            self.assertNotIn("payment_details", row)

    def test_multiple_label_lists_the_group(self):
        firm, group, m1 = seed_matter(
            self.profile, firm_name="Firm X", matter_name="MA"
        )
        m2 = Matter.objects.create(
            profile=self.profile, firm=firm, group=group, name="MB"
        )
        a = memo_with_total(self.profile, m1, 1000, date="2026-07-15")
        b = memo_with_total(self.profile, m2, 1000, date="2026-07-16")
        # One payment split across both memos.
        payments.add_payment(
            self.profile,
            dict(
                amount=1500,
                date_of_payment="2026-08-01",
                allocations=[
                    {"memo_id": a.pk, "amount": 1000, "tds_amount": 0},
                    {"memo_id": b.pk, "amount": 500, "tds_amount": 0},
                ],
            ),
        )
        rows = feebook.list_feebook(self.profile, {})
        self.assertEqual(len(rows), 2)  # one row per memo-share
        self.assertTrue(all(r["payment_type"] == "Multiple" for r in rows))
        self.assertTrue(all(r["allocation_count"] == 2 for r in rows))
        # Each row lists both memos that were paid together.
        self.assertEqual(
            sorted(rows[0]["group_memo_numbers"]),
            sorted([a.memo_number, b.memo_number]),
        )

    def test_rows_sorted_by_payment_date_then_id_desc(self):
        memo = memo_with_total(self.profile, self.matter, 5000)
        payments.add_payment_to_memo(
            self.profile, memo.pk, dict(amount=100, date_of_payment="2026-08-01")
        )
        payments.add_payment_to_memo(
            self.profile, memo.pk, dict(amount=200, date_of_payment="2026-09-01")
        )
        rows = feebook.list_feebook(self.profile, {})
        self.assertEqual(
            [r["date_of_payment"].isoformat() for r in rows],
            ["2026-09-01", "2026-08-01"],
        )

    def test_query_count_four_with_allocations(self):
        memo = memo_with_total(self.profile, self.matter, 5000)
        for day in range(1, 6):
            payments.add_payment_to_memo(
                self.profile,
                memo.pk,
                dict(amount=100, date_of_payment=f"2026-08-0{day}"),
            )
        # settings + grouping + allocation rows + unaccounted rows.
        with self.assertNumQueries(4):
            rows = feebook.list_feebook(self.profile, {})
            self.assertEqual(len(rows), 5)


# ---------------------------------------------------------------------------
# Unaccounted payments (ports the unaccounted-only and FY-active tests)
# ---------------------------------------------------------------------------

class FeebookUnaccountedTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, self.group, self.matter = seed_matter(self.profile)

    def _add_unaccounted(self, amount, date):
        return payments.add_unaccounted_payment(
            self.profile, dict(amount=amount, date_of_payment=date)
        )

    def test_unaccounted_only_filter(self):
        memo = memo_with_total(self.profile, self.matter, 1000)
        payments.add_payment_to_memo(
            self.profile, memo.pk, dict(amount=500, date_of_payment="2026-08-01")
        )
        self._add_unaccounted(200, "2026-08-05")

        self.assertEqual(len(feebook.list_feebook(self.profile, {})), 2)
        unaccounted = feebook.list_feebook(self.profile, {"unaccounted_only": True})
        self.assertEqual(len(unaccounted), 1)
        self.assertIsNone(unaccounted[0]["memo_number"])
        self.assertIsNone(unaccounted[0]["memo_id"])
        self.assertIsNone(unaccounted[0]["memo_total"])

    def test_unaccounted_shown_even_when_fy_filter_active(self):
        # Regression: a financial-year filter must not hide unaccounted payments,
        # which have no memo and thus no memo financial year (filtered on the
        # payment date instead).
        memo = memo_with_total(self.profile, self.matter, 1000, date="2026-07-15")
        payments.add_payment_to_memo(
            self.profile, memo.pk, dict(amount=500, date_of_payment="2026-08-01")
        )
        self._add_unaccounted(200, "2026-08-05")

        with_fy = feebook.list_feebook(self.profile, {"financial_year": "2026-27"})
        self.assertEqual(len(with_fy), 2)
        self.assertTrue(any(r["memo_id"] is None for r in with_fy))

        unaccounted = feebook.list_feebook(
            self.profile, {"financial_year": "2026-27", "unaccounted_only": True}
        )
        self.assertEqual(len(unaccounted), 1)
        self.assertIsNone(unaccounted[0]["memo_id"])

    def test_query_count_two_when_unaccounted_only(self):
        memo = memo_with_total(self.profile, self.matter, 1000)
        payments.add_payment_to_memo(
            self.profile, memo.pk, dict(amount=500, date_of_payment="2026-08-01")
        )
        self._add_unaccounted(200, "2026-08-05")
        # settings + unaccounted rows = 2 queries (the allocation grouping and
        # rows are skipped under unaccounted_only).
        with self.assertNumQueries(2):
            rows = feebook.list_feebook(self.profile, {"unaccounted_only": True})
            self.assertEqual(len(rows), 1)


# ---------------------------------------------------------------------------
# FY filter uses the payment date, not the memo billing year (ports test 5)
# ---------------------------------------------------------------------------

class FeebookFinancialYearTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter = seed_matter(self.profile)

    def test_fy_filter_uses_payment_date_not_memo_billing_year(self):
        # Memo billed in FY 2025-26 (dated 2026-01-10)...
        memo = memo_with_total(self.profile, self.matter, 5000, date="2026-01-10")
        # ...but paid on 25 Aug 2026, which is FY 2026-27.
        payments.add_payment_to_memo(
            self.profile, memo.pk, dict(amount=5000, date_of_payment="2026-08-25")
        )

        # The payment must NOT appear under the memo's billing year (2025-26)...
        self.assertEqual(
            len(feebook.list_feebook(self.profile, {"financial_year": "2025-26"})), 0
        )
        # ...it belongs to the payment's financial year (2026-27).
        paid_fy = feebook.list_feebook(self.profile, {"financial_year": "2026-27"})
        self.assertEqual(len(paid_fy), 1)
        self.assertEqual(paid_fy[0]["date_of_payment"].isoformat(), "2026-08-25")

        # A Jan-Mar payment maps to the FY that started the previous April: a
        # second payment dated 15 Feb 2027 is still FY 2026-27.
        payments.add_payment_to_memo(
            self.profile, memo.pk, dict(amount=100, date_of_payment="2027-02-15")
        )
        feb = feebook.list_feebook(self.profile, {"financial_year": "2026-27"})
        self.assertTrue(
            any(r["date_of_payment"].isoformat() == "2027-02-15" for r in feb)
        )
        # That Feb payment must NOT fall into FY 2027-28.
        self.assertEqual(
            len(feebook.list_feebook(self.profile, {"financial_year": "2027-28"})), 0
        )


# ---------------------------------------------------------------------------
# Initial-FY cutoff (server-enforced, both kinds of row)
# ---------------------------------------------------------------------------

class FeebookCutoffTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter = seed_matter(self.profile)

    def test_cutoff_hides_payments_before_feebook_start_year(self):
        settings.update_settings(self.profile, {"feebook_start_year": "2026-27"})
        memo = memo_with_total(self.profile, self.matter, 5000, date="2025-05-01")
        # An allocated payment in FY 2025-26 (before the cutoff) is hidden...
        payments.add_payment_to_memo(
            self.profile, memo.pk, dict(amount=500, date_of_payment="2025-06-01")
        )
        # ...an unaccounted payment before the cutoff is hidden too...
        payments.add_unaccounted_payment(
            self.profile, dict(amount=200, date_of_payment="2025-06-05")
        )
        # ...and a payment on or after the cutoff is shown.
        payments.add_payment_to_memo(
            self.profile, memo.pk, dict(amount=600, date_of_payment="2026-08-01")
        )
        rows = feebook.list_feebook(self.profile, {})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["date_of_payment"].isoformat(), "2026-08-01")

        # The cutoff cannot be bypassed by asking for the pre-cutoff FY directly.
        self.assertEqual(
            len(feebook.list_feebook(self.profile, {"financial_year": "2025-26"})), 0
        )


# ---------------------------------------------------------------------------
# Q7: firm and group filters do NOT hide unaccounted payments
# ---------------------------------------------------------------------------

class FeebookQ7Tests(TestCase):
    """Q7 (brief): the Feebook firm and group filters are deliberately NOT applied
    to unaccounted payments, which are not tied to any firm, so an unaccounted
    payment still appears under any firm or partner filter while the allocation
    rows are narrowed."""

    def setUp(self):
        self.profile = fees_profile()
        self.firm, self.group, self.matter = seed_matter(self.profile)
        # A second firm/group, so a firm/partner filter can exclude it.
        self.other_firm, self.other_group, self.other_matter = seed_matter(
            self.profile, firm_name="Other", matter_name="Other matter"
        )

    def test_firm_filter_keeps_unaccounted_but_narrows_allocations(self):
        here = memo_with_total(self.profile, self.matter, 1000)
        there = memo_with_total(self.profile, self.other_matter, 1000)
        payments.add_payment_to_memo(
            self.profile, here.pk, dict(amount=100, date_of_payment="2026-08-01")
        )
        payments.add_payment_to_memo(
            self.profile, there.pk, dict(amount=200, date_of_payment="2026-08-02")
        )
        payments.add_unaccounted_payment(
            self.profile, dict(amount=50, date_of_payment="2026-08-03")
        )

        rows = feebook.list_feebook(self.profile, {"firm_id": self.firm.pk})
        # The "other firm" allocation is filtered out; this firm's allocation and
        # the firm-less unaccounted payment both remain.
        memo_ids = [r["memo_id"] for r in rows]
        self.assertIn(here.pk, memo_ids)
        self.assertNotIn(there.pk, memo_ids)
        self.assertTrue(any(r["memo_id"] is None for r in rows))
        self.assertEqual(len(rows), 2)

    def test_partner_filter_keeps_unaccounted_and_none_is_noop(self):
        here = memo_with_total(self.profile, self.matter, 1000)
        there = memo_with_total(self.profile, self.other_matter, 1000)
        payments.add_payment_to_memo(
            self.profile, here.pk, dict(amount=100, date_of_payment="2026-08-01")
        )
        payments.add_payment_to_memo(
            self.profile, there.pk, dict(amount=200, date_of_payment="2026-08-02")
        )
        payments.add_unaccounted_payment(
            self.profile, dict(amount=50, date_of_payment="2026-08-03")
        )

        by_partner = feebook.list_feebook(
            self.profile, {"partner_id": self.group.pk}
        )
        memo_ids = [r["memo_id"] for r in by_partner]
        self.assertIn(here.pk, memo_ids)
        self.assertNotIn(there.pk, memo_ids)
        # The unaccounted payment is not tied to a group, so it still appears.
        self.assertTrue(any(r["memo_id"] is None for r in by_partner))

        # A partner_id of "none" is a no-op: every row is returned.
        all_rows = feebook.list_feebook(self.profile, {"partner_id": "none"})
        self.assertEqual(len(all_rows), 3)
