"""Ledger and Statement read-service tests for the Fee Register (T3.4, R-RD-1, brief 6.5).

Ports the ``ledgerService`` and "ledger scopes" describe blocks from
``ledgerService.test.ts`` (the running balance with memos before payments on the
same day; the particulars string; the ``paymentParticulars`` omit test; and the
firm / partner / chosen-matter / single-matter scopes) to Django ``TestCase``,
plus coverage of ``build_statement`` (rows, outstanding floored at 0, the
Written Off status override, the totals summary) and explicit ``assertNumQueries``
bounds on ``build_ledger`` and ``build_statement`` so a per-row (N+1) regression
fails the suite.

The TS "partnerId" maps to the Django ``group_id`` (the ``Group`` model). Memos
are created via ``memos.create_memo`` (so ``total_fees`` is stored) and payments
via ``payments.add_payment_to_memo`` (so the stored gross ``amount_paid`` column
is maintained). Setup mirrors ``test_outstanding.py``.
"""
from decimal import Decimal

from django.test import TestCase

from accounts.models import Profile
from accounts.suite import KEY_FEES
from fees.models import Firm, Group, Matter
from fees.services import ledger, memos, payments


def fees_profile(name="Ziyad-Fees"):
    return Profile.objects.create(program=KEY_FEES, name=name)


def seed_firm(profile, firm_name="Firm", group_name="P"):
    firm = Firm.objects.create(profile=profile, name=firm_name)
    group = Group.objects.create(profile=profile, firm=firm, name=group_name)
    return firm, group


def seed_matter(profile, firm, group, matter_name="Matter"):
    return Matter.objects.create(
        profile=profile, firm=firm, group=group, name=matter_name
    )


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
# paymentParticulars: omits missing parts
# ---------------------------------------------------------------------------

class PaymentParticularsTests(TestCase):
    def test_omits_missing_payee_and_mode(self):
        self.assertEqual(
            ledger.payment_particulars(None, None, "5 of 2026-27"),
            "Payment against Memo 5 of 2026-27",
        )
        self.assertEqual(
            ledger.payment_particulars("X", None, "1"),
            "Payment by X against Memo 1",
        )

    def test_includes_both_payee_and_mode_when_present(self):
        self.assertEqual(
            ledger.payment_particulars("Acme", "NEFT", "7"),
            "Payment by Acme by NEFT against Memo 7",
        )

    def test_blank_and_whitespace_parts_are_omitted_and_trimmed(self):
        self.assertEqual(
            ledger.payment_particulars("  ", "  ", "3"),
            "Payment against Memo 3",
        )
        self.assertEqual(
            ledger.payment_particulars("  Acme  ", None, "3"),
            "Payment by Acme against Memo 3",
        )

    def test_none_memo_number_renders_as_draft(self):
        self.assertEqual(
            ledger.payment_particulars(None, None, None),
            "Payment against Memo (draft)",
        )


# ---------------------------------------------------------------------------
# buildLedger: running balance, memos before payments on the same day
# ---------------------------------------------------------------------------

class BuildLedgerTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        self.firm, self.group = seed_firm(self.profile)
        self.matter = seed_matter(self.profile, self.firm, self.group, "Matter One")

    def test_running_balance_memos_before_payments_same_day(self):
        a = memo_with_total(self.profile, self.matter, 1000, date="2026-07-01")
        b = memo_with_total(self.profile, self.matter, 500, date="2026-08-01")
        # Payment on the same day as memo b: net 600 + TDS 100 (auto_tds off).
        payments.add_payment_to_memo(
            self.profile,
            a.pk,
            dict(
                amount=600,
                auto_tds=False,
                tds_amount=100,
                date_of_payment="2026-08-01",
                payee="Acme",
                payment_mode="NEFT",
            ),
        )

        rows = ledger.build_ledger(self.profile, {"matter_id": self.matter.pk})
        self.assertEqual(len(rows), 3)

        self.assertEqual(rows[0]["memo_amount"], Decimal("1000.00"))
        self.assertEqual(rows[0]["balance"], Decimal("1000.00"))

        # Same day: memo b (debit) comes before the payment (credit).
        self.assertEqual(rows[1]["memo_amount"], Decimal("500.00"))
        self.assertIsNone(rows[1]["payment_amount"])
        self.assertEqual(rows[1]["balance"], Decimal("1500.00"))

        self.assertIsNone(rows[2]["memo_amount"])
        self.assertEqual(rows[2]["payment_amount"], Decimal("600.00"))
        self.assertEqual(rows[2]["tds"], Decimal("100.00"))
        self.assertEqual(rows[2]["balance"], Decimal("800.00"))
        self.assertEqual(
            rows[2]["particulars"],
            f"Payment by Acme by NEFT against Memo {a.memo_number}",
        )
        self.assertTrue(b.memo_number)

    def test_memo_row_particulars_and_written_off_suffix(self):
        memo = memo_with_total(self.profile, self.matter, 1000, date="2026-07-01")
        off = memo_with_total(self.profile, self.matter, 500, date="2026-07-02")
        memos.set_memo_written_off(self.profile, off.pk, True)

        rows = ledger.build_ledger(self.profile, {"matter_id": self.matter.pk})
        self.assertEqual(rows[0]["particulars"], f"Memo {memo.memo_number}")
        self.assertEqual(
            rows[1]["particulars"], f"Memo {off.memo_number} (written off)"
        )
        self.assertEqual(rows[0]["matter_name"], "Matter One")

    def test_drafts_are_excluded(self):
        memo_with_total(self.profile, self.matter, 1000, date="2026-07-01")
        memos.create_memo(
            self.profile,
            dict(
                date="2026-07-02",
                matter_id=self.matter.pk,
                addressee_line1="A",
                num_appearances=0,
                fees_per_appearance=0,
                num_conferences=0,
                fees_per_conference=0,
                fees_misc_drafting=9999,
            ),
            is_draft=True,
        )
        rows = ledger.build_ledger(self.profile, {"matter_id": self.matter.pk})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["balance"], Decimal("1000.00"))

    def test_no_scope_lists_every_non_draft_memo(self):
        memo_with_total(self.profile, self.matter, 100, date="2026-07-01")
        rows = ledger.build_ledger(self.profile)
        self.assertEqual(len(rows), 1)

    def test_excludes_other_profiles(self):
        other = fees_profile(name="Other-Fees")
        ofirm, ogroup = seed_firm(other)
        omatter = seed_matter(other, ofirm, ogroup, "Other")
        memo_with_total(self.profile, self.matter, 1000, date="2026-07-01")
        memo_with_total(other, omatter, 500, date="2026-07-01")
        rows = ledger.build_ledger(self.profile)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["balance"], Decimal("1000.00"))

    def test_query_count_is_two(self):
        a = memo_with_total(self.profile, self.matter, 1000, date="2026-07-01")
        for i in range(4):
            memo_with_total(
                self.profile, self.matter, 100, date=f"2026-08-0{i + 1}"
            )
        payments.add_payment_to_memo(
            self.profile, a.pk, dict(amount=100, date_of_payment="2026-09-01")
        )
        # One query for the memo rows, one for the payment allocations.
        with self.assertNumQueries(2):
            rows = ledger.build_ledger(self.profile, {"matter_id": self.matter.pk})
            self.assertEqual(len(rows), 6)


# ---------------------------------------------------------------------------
# ledger scopes: firm, partner, chosen matterIds, single matter
# ---------------------------------------------------------------------------

class LedgerScopeTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        self.firm = Firm.objects.create(profile=self.profile, name="Firm")
        self.p1 = Group.objects.create(
            profile=self.profile, firm=self.firm, name="Alpha"
        )
        self.p2 = Group.objects.create(
            profile=self.profile, firm=self.firm, name="Beta"
        )
        self.m1 = Matter.objects.create(
            profile=self.profile, firm=self.firm, group=self.p1, name="M1"
        )
        self.m2 = Matter.objects.create(
            profile=self.profile, firm=self.firm, group=self.p2, name="M2"
        )
        self.m3 = Matter.objects.create(
            profile=self.profile, firm=self.firm, group=self.p2, name="M3"
        )
        memo_with_total(self.profile, self.m1, 100, date="2026-07-01")
        memo_with_total(self.profile, self.m2, 200, date="2026-07-02")
        memo_with_total(self.profile, self.m3, 400, date="2026-07-03")

    def _final_balance(self, scope):
        rows = ledger.build_ledger(self.profile, scope)
        return rows[-1]["balance"]

    def test_whole_firm(self):
        self.assertEqual(
            self._final_balance({"firm_id": self.firm.pk}), Decimal("700.00")
        )

    def test_one_partner(self):
        self.assertEqual(
            self._final_balance({"firm_id": self.firm.pk, "partner_id": self.p2.pk}),
            Decimal("600.00"),
        )

    def test_chosen_matter_ids(self):
        self.assertEqual(
            self._final_balance(
                {"firm_id": self.firm.pk, "matter_ids": [self.m1.pk, self.m3.pk]}
            ),
            Decimal("500.00"),
        )

    def test_single_matter_in_matter_ids(self):
        rows = ledger.build_ledger(
            self.profile, {"firm_id": self.firm.pk, "matter_ids": [self.m2.pk]}
        )
        self.assertEqual(len(rows), 1)

    def test_partner_none_is_a_no_op(self):
        self.assertEqual(
            self._final_balance({"firm_id": self.firm.pk, "partner_id": "none"}),
            Decimal("700.00"),
        )


# ---------------------------------------------------------------------------
# build_statement: rows, outstanding floored at 0, Written Off override, totals
# ---------------------------------------------------------------------------

class BuildStatementTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        self.firm, self.group = seed_firm(self.profile, "Acme & Co", "Jane")
        self.matter = seed_matter(self.profile, self.firm, self.group, "Alpha")

    def test_rows_totals_and_status(self):
        a = memo_with_total(self.profile, self.matter, 1000, date="2026-07-01")
        memo_with_total(self.profile, self.matter, 500, date="2026-07-02")
        payments.add_payment_to_memo(
            self.profile, a.pk, dict(amount=400, date_of_payment="2026-08-01")
        )

        data = ledger.build_statement(self.profile, {"matter_id": self.matter.pk})
        rows = data["rows"]
        self.assertEqual(len(rows), 2)

        paid_row = next(r for r in rows if r["memo_number"] == a.memo_number)
        self.assertEqual(paid_row["total"], Decimal("1000.00"))
        self.assertEqual(paid_row["paid"], Decimal("400.00"))
        self.assertEqual(paid_row["outstanding"], Decimal("600.00"))
        self.assertEqual(paid_row["status"], "Unpaid")
        self.assertEqual(paid_row["matter_name"], "Alpha")

        totals = data["totals"]
        self.assertEqual(totals["total_billed"], Decimal("1500.00"))
        self.assertEqual(totals["total_paid"], Decimal("400.00"))
        self.assertEqual(totals["total_outstanding"], Decimal("1100.00"))
        self.assertEqual(totals["count"], 2)

    def test_outstanding_floored_at_zero_on_overpayment(self):
        memo = memo_with_total(self.profile, self.matter, 500, date="2026-07-01")
        # Pay more than the total: outstanding must floor at 0, status Paid.
        payments.add_payment_to_memo(
            self.profile, memo.pk, dict(amount=800, date_of_payment="2026-08-01")
        )
        data = ledger.build_statement(self.profile, {"matter_id": self.matter.pk})
        row = data["rows"][0]
        self.assertEqual(row["outstanding"], Decimal("0.00"))
        self.assertEqual(row["status"], "Paid")
        self.assertEqual(data["totals"]["total_outstanding"], Decimal("0.00"))

    def test_written_off_overrides_status(self):
        memo = memo_with_total(self.profile, self.matter, 500, date="2026-07-01")
        memos.set_memo_written_off(self.profile, memo.pk, True)
        data = ledger.build_statement(self.profile, {"matter_id": self.matter.pk})
        self.assertEqual(data["rows"][0]["status"], "Written Off")

    def test_title_for_single_matter(self):
        memo_with_total(self.profile, self.matter, 100, date="2026-07-01")
        data = ledger.build_statement(self.profile, {"matter_id": self.matter.pk})
        self.assertEqual(data["title"], "Statement - Alpha")
        self.assertEqual(data["subtitle"], "Acme & Co")

    def test_title_for_firm(self):
        memo_with_total(self.profile, self.matter, 100, date="2026-07-01")
        data = ledger.build_statement(self.profile, {"firm_id": self.firm.pk})
        self.assertEqual(data["title"], "Statement - Acme & Co")
        self.assertEqual(data["subtitle"], "")

    def test_title_plain_without_scope(self):
        memo_with_total(self.profile, self.matter, 100, date="2026-07-01")
        data = ledger.build_statement(self.profile)
        self.assertEqual(data["title"], "Statement")

    def test_drafts_excluded(self):
        memo_with_total(self.profile, self.matter, 100, date="2026-07-01")
        memos.create_memo(
            self.profile,
            dict(
                date="2026-07-02",
                matter_id=self.matter.pk,
                addressee_line1="A",
                num_appearances=0,
                fees_per_appearance=0,
                num_conferences=0,
                fees_per_conference=0,
                fees_misc_drafting=9999,
            ),
            is_draft=True,
        )
        data = ledger.build_statement(self.profile, {"matter_id": self.matter.pk})
        self.assertEqual(data["totals"]["count"], 1)

    def test_excludes_other_profiles(self):
        other = fees_profile(name="Other-Fees")
        ofirm, ogroup = seed_firm(other)
        omatter = seed_matter(other, ofirm, ogroup, "Other")
        memo_with_total(self.profile, self.matter, 100, date="2026-07-01")
        memo_with_total(other, omatter, 500, date="2026-07-01")
        data = ledger.build_statement(self.profile, {"firm_id": self.firm.pk})
        self.assertEqual(data["totals"]["count"], 1)

    def test_query_count_is_two_with_matter_scope(self):
        for i in range(5):
            memo_with_total(
                self.profile, self.matter, 100, date=f"2026-0{i + 1}-01"
            )
        # One query to resolve the matter title name, one for the memo rows.
        with self.assertNumQueries(2):
            data = ledger.build_statement(
                self.profile, {"matter_id": self.matter.pk}
            )
            self.assertEqual(data["totals"]["count"], 5)

    def test_query_count_is_one_without_scope(self):
        for i in range(5):
            memo_with_total(
                self.profile, self.matter, 100, date=f"2026-0{i + 1}-01"
            )
        # No scope: no title name to resolve, just the one memo-rows query.
        with self.assertNumQueries(1):
            data = ledger.build_statement(self.profile)
            self.assertEqual(data["totals"]["count"], 5)
