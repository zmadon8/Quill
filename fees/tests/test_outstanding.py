"""Outstanding read-service tests for the Fee Register (T3.3, R-RD-1, brief 6.3).

Ports ``outstandingService.test.ts`` (lists only unpaid memos grouped by matter
with subtotals; includes memos from archived matters; excludes written-off
unless ``include_written_off``, Req #7; the scope lists only firms / partners
with applicable items and honours the flags; entries carry firm / partner /
written-off status for export columns; each group carries its partner so matters
can be grouped partner-wise; the firm-wise summary honours the partner filter;
and the entries / subtotals carry total, net-of-TDS, paid and due on a partial
payment) to Django ``TestCase``, plus explicit ``assertNumQueries`` bounds on
each list entry point so a per-row (N+1) regression fails the suite.

Everything is scoped to a ``Profile(program="fees")``. Memos are created via
``memos.create_memo`` (so ``total_fees`` is stored) and payments via
``payments.add_payment_to_memo`` (so the stored gross ``amount_paid`` column is
maintained); the firm / group / matter helpers mirror ``test_memo_lists.py`` and
``test_feebook.py``. The TS source calls the grouping "partner"; the model is
``Group``, so ``partner_id`` maps to ``group_id`` and ``partner_name`` to the
group's name.
"""
from decimal import Decimal

from django.test import TestCase

from accounts.models import Profile
from accounts.suite import KEY_FEES
from fees.models import Firm, Group, Matter
from fees.services import matters, memos, outstanding, payments


def fees_profile(name="Ziyad-Fees"):
    return Profile.objects.create(program=KEY_FEES, name=name)


def seed_firm(profile, firm_name="Firm", group_name="P"):
    firm = Firm.objects.create(profile=profile, name=firm_name)
    group = Group.objects.create(profile=profile, firm=firm, name=group_name)
    return firm, group


def seed_matter(profile, firm, group, matter_name="Matter", archived=False):
    return Matter.objects.create(
        profile=profile,
        firm=firm,
        group=group,
        name=matter_name,
        is_archived=archived,
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
# listOutstanding: unpaid, grouped, subtotals; archived; written-off
# ---------------------------------------------------------------------------

class ListOutstandingTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        self.firm, self.group = seed_firm(self.profile)
        self.m1 = seed_matter(self.profile, self.firm, self.group, "Alpha")
        self.m2 = seed_matter(self.profile, self.firm, self.group, "Beta")

    def test_lists_only_unpaid_grouped_by_matter_with_subtotals(self):
        memo_with_total(self.profile, self.m1, 1000)
        memo_with_total(self.profile, self.m1, 500)
        paid = memo_with_total(self.profile, self.m2, 800)
        # Fully paid -> excluded.
        payments.add_payment_to_memo(
            self.profile, paid.pk, dict(amount=800, date_of_payment="2026-08-01")
        )

        groups = outstanding.list_outstanding(self.profile, {})
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["matter_name"], "Alpha")
        self.assertEqual(len(groups[0]["entries"]), 2)
        self.assertEqual(groups[0]["subtotal"], Decimal("1500.00"))
        self.assertEqual(
            outstanding.outstanding_grand_total(groups), Decimal("1500.00")
        )

    def test_includes_memos_from_archived_matters(self):
        # A matter accrues memos while active, then is archived later; the
        # Outstanding view must still include its unpaid memos.
        matter = seed_matter(self.profile, self.firm, self.group, "Gamma")
        memo_with_total(self.profile, matter, 1000)
        matters.archive_matter(self.profile, matter.pk)
        groups = outstanding.list_outstanding(self.profile, {})
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["subtotal"], Decimal("1000.00"))

    def test_excludes_written_off_unless_included(self):
        keep = memo_with_total(self.profile, self.m1, 1000)
        off = memo_with_total(self.profile, self.m1, 700)
        memos.set_memo_written_off(self.profile, off.pk, True)

        # Default: the written-off memo is hidden.
        default = outstanding.list_outstanding(self.profile, {})
        self.assertEqual(len(default), 1)
        self.assertEqual(default[0]["subtotal"], Decimal("1000.00"))
        self.assertTrue(
            all(e["memo_id"] != off.pk for e in default[0]["entries"])
        )
        self.assertGreater(keep.pk, 0)

        # With include_written_off, both appear.
        incl = outstanding.list_outstanding(
            self.profile, {"include_written_off": True}
        )
        self.assertEqual(len(incl[0]["entries"]), 2)
        self.assertEqual(incl[0]["subtotal"], Decimal("1700.00"))

    def test_entries_carry_firm_partner_and_written_off_status(self):
        firm, group = seed_firm(self.profile, "Acme & Co", "Jane")
        mt = seed_matter(self.profile, firm, group, "AlphaCo")
        keep = memo_with_total(self.profile, mt, 1000)
        off = memo_with_total(self.profile, mt, 500)
        memos.set_memo_written_off(self.profile, off.pk, True)

        groups = outstanding.list_outstanding(
            self.profile, {"firm_id": firm.pk, "include_written_off": True}
        )
        entries = [e for g in groups for e in g["entries"]]
        keep_e = next(e for e in entries if e["memo_id"] == keep.pk)
        off_e = next(e for e in entries if e["memo_id"] == off.pk)
        self.assertEqual(keep_e["firm_name"], "Acme & Co")
        self.assertEqual(keep_e["partner_name"], "Jane")
        self.assertFalse(keep_e["is_written_off"])
        self.assertTrue(off_e["is_written_off"])

    def test_each_group_carries_its_partner(self):
        firm, group_a = seed_firm(self.profile, "Firm2", "PA")
        group_b = Group.objects.create(profile=self.profile, firm=firm, name="PB")
        ma = seed_matter(self.profile, firm, group_a, "AlphaX")
        mb = seed_matter(self.profile, firm, group_b, "BetaX")
        memo_with_total(self.profile, ma, 1000)
        memo_with_total(self.profile, mb, 400)

        groups = outstanding.list_outstanding(self.profile, {"firm_id": firm.pk})
        alpha = next(g for g in groups if g["matter_name"] == "AlphaX")
        beta = next(g for g in groups if g["matter_name"] == "BetaX")
        self.assertEqual(alpha["partner_name"], "PA")
        self.assertEqual(alpha["partner_id"], group_a.pk)
        self.assertEqual(beta["partner_name"], "PB")
        self.assertEqual(beta["partner_id"], group_b.pk)

    def test_entries_and_subtotals_carry_total_net_paid_due_on_partial(self):
        part = memo_with_total(self.profile, self.m1, 1000)  # net of 10% = 900
        payments.add_payment_to_memo(
            self.profile, part.pk, dict(amount=300, date_of_payment="2026-08-01")
        )
        memo_with_total(self.profile, self.m1, 500)  # unpaid; net = 450

        groups = outstanding.list_outstanding(self.profile, {})
        self.assertEqual(len(groups), 1)
        group = groups[0]
        entry = next(e for e in group["entries"] if e["memo_id"] == part.pk)
        self.assertEqual(entry["total_fees"], Decimal("1000.00"))
        self.assertEqual(entry["net_of_tds"], Decimal("900.00"))
        self.assertEqual(entry["amount_paid"], Decimal("300.00"))
        self.assertEqual(entry["due"], Decimal("700.00"))

        # Subtotals: total 1500, net 1350, paid 300, due 1200.
        self.assertEqual(group["subtotal_total"], Decimal("1500.00"))
        self.assertEqual(group["subtotal_net_of_tds"], Decimal("1350.00"))
        self.assertEqual(group["subtotal_paid"], Decimal("300.00"))
        self.assertEqual(group["subtotal"], Decimal("1200.00"))

    def test_groups_ordered_by_partner_then_matter_name(self):
        # Two groups, inserted so the alphabetic order differs from creation.
        firm, group_z = seed_firm(self.profile, "FirmZ", "Zed")
        group_a = Group.objects.create(profile=self.profile, firm=firm, name="Able")
        mz = seed_matter(self.profile, firm, group_z, "Mango")
        ma = seed_matter(self.profile, firm, group_a, "Nectarine")
        memo_with_total(self.profile, mz, 100)
        memo_with_total(self.profile, ma, 100)

        groups = outstanding.list_outstanding(self.profile, {"firm_id": firm.pk})
        self.assertEqual(
            [g["partner_name"] for g in groups], ["Able", "Zed"]
        )

    def test_overdue_only_filter(self):
        # overdue_days defaults to 0, so nothing is ever overdue -> no rows.
        memo_with_total(self.profile, self.m1, 1000)
        groups = outstanding.list_outstanding(self.profile, {"overdue_only": True})
        self.assertEqual(groups, [])

    def test_excludes_other_profiles(self):
        other = fees_profile(name="Other-Fees")
        ofirm, ogroup = seed_firm(other)
        omatter = seed_matter(other, ofirm, ogroup, "Other")
        memo_with_total(self.profile, self.m1, 1000)
        memo_with_total(other, omatter, 500)
        mine = outstanding.list_outstanding(self.profile, {})
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["subtotal"], Decimal("1000.00"))

    def test_query_count_is_two(self):
        for i in range(5):
            memo_with_total(
                self.profile, self.m1, 1000, date=f"2026-0{i + 1}-01"
            )
        # One query for settings, one for the rows (no per-row N+1 for the
        # firm / matter / group names or the gross paid column).
        with self.assertNumQueries(2):
            groups = outstanding.list_outstanding(self.profile, {})
            self.assertEqual(len(groups), 1)
            self.assertEqual(len(groups[0]["entries"]), 5)


# ---------------------------------------------------------------------------
# listOutstandingByFirm: one row per firm, honours filters and sort
# ---------------------------------------------------------------------------

class ListOutstandingByFirmTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()

    def test_firm_wise_summary_honours_the_partner_filter(self):
        firm, group_a = seed_firm(self.profile, "Multi", "PA")
        group_b = Group.objects.create(profile=self.profile, firm=firm, name="PB")
        ma = seed_matter(self.profile, firm, group_a, "MA")
        mb = seed_matter(self.profile, firm, group_b, "MB")
        memo_with_total(self.profile, ma, 1000)
        memo_with_total(self.profile, mb, 400)

        all_rows = outstanding.list_outstanding_by_firm(self.profile, {})
        self.assertEqual(
            next(r for r in all_rows if r["firm_id"] == firm.pk)["outstanding"],
            Decimal("1400.00"),
        )

        only_pa = outstanding.list_outstanding_by_firm(
            self.profile, {"partner_id": group_a.pk}
        )
        self.assertEqual(
            next(r for r in only_pa if r["firm_id"] == firm.pk)["outstanding"],
            Decimal("1000.00"),
        )

    def test_sort_by_amount_desc_then_by_name(self):
        firm_a, group_a = seed_firm(self.profile, "Aardvark", "GA")
        firm_z, group_z = seed_firm(self.profile, "Zulu", "GZ")
        ma = seed_matter(self.profile, firm_a, group_a, "MA")
        mz = seed_matter(self.profile, firm_z, group_z, "MZ")
        memo_with_total(self.profile, ma, 100)
        memo_with_total(self.profile, mz, 900)

        by_amount = outstanding.list_outstanding_by_firm(
            self.profile, {}, sort="amount"
        )
        self.assertEqual([r["firm_name"] for r in by_amount], ["Zulu", "Aardvark"])

        by_name = outstanding.list_outstanding_by_firm(
            self.profile, {}, sort="name"
        )
        self.assertEqual([r["firm_name"] for r in by_name], ["Aardvark", "Zulu"])

    def test_memo_count_and_excludes_fully_paid(self):
        firm, group = seed_firm(self.profile, "Firm", "G")
        mt = seed_matter(self.profile, firm, group, "M")
        memo_with_total(self.profile, mt, 1000)
        paid = memo_with_total(self.profile, mt, 500)
        payments.add_payment_to_memo(
            self.profile, paid.pk, dict(amount=500, date_of_payment="2026-08-01")
        )
        rows = outstanding.list_outstanding_by_firm(self.profile, {})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["memo_count"], 1)
        self.assertEqual(rows[0]["outstanding"], Decimal("1000.00"))

    def test_query_count_is_two(self):
        firm, group = seed_firm(self.profile, "Firm", "G")
        mt = seed_matter(self.profile, firm, group, "M")
        for i in range(5):
            memo_with_total(self.profile, mt, 1000, date=f"2026-0{i + 1}-01")
        with self.assertNumQueries(2):
            rows = outstanding.list_outstanding_by_firm(self.profile, {})
            self.assertEqual(rows[0]["memo_count"], 5)


# ---------------------------------------------------------------------------
# listOutstandingScope: firms / partners with applicable items
# ---------------------------------------------------------------------------

class ListOutstandingScopeTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()

    def test_scope_lists_only_firms_partners_with_applicable_items(self):
        f1, p1 = seed_firm(self.profile, "Firm One", "P1")
        m1 = seed_matter(self.profile, f1, p1, "A")
        memo_with_total(self.profile, m1, 1000)  # outstanding

        # A second firm whose only memo is written off.
        f2, p2 = seed_firm(self.profile, "Firm Two", "P2")
        m2 = seed_matter(self.profile, f2, p2, "B")
        off = memo_with_total(self.profile, m2, 500)
        memos.set_memo_written_off(self.profile, off.pk, True)

        base = outstanding.list_outstanding_scope(self.profile, {})
        self.assertEqual([f["name"] for f in base["firms"]], ["Firm One"])

        incl = outstanding.list_outstanding_scope(
            self.profile, {"include_written_off": True}
        )
        self.assertEqual(
            sorted(f["name"] for f in incl["firms"]), ["Firm One", "Firm Two"]
        )

    def test_scope_partners_sorted_and_carry_firm_id(self):
        f1, p1 = seed_firm(self.profile, "Zeta", "Yankee")
        f2, p2 = seed_firm(self.profile, "Alpha", "Bravo")
        m1 = seed_matter(self.profile, f1, p1, "M1")
        m2 = seed_matter(self.profile, f2, p2, "M2")
        memo_with_total(self.profile, m1, 100)
        memo_with_total(self.profile, m2, 100)

        scope = outstanding.list_outstanding_scope(self.profile, {})
        self.assertEqual([f["name"] for f in scope["firms"]], ["Alpha", "Zeta"])
        self.assertEqual([p["name"] for p in scope["partners"]], ["Bravo", "Yankee"])
        bravo = next(p for p in scope["partners"] if p["name"] == "Bravo")
        self.assertEqual(bravo["firm_id"], f2.pk)
        self.assertEqual(bravo["id"], p2.pk)

    def test_scope_excludes_fully_paid(self):
        f, p = seed_firm(self.profile, "Firm", "G")
        m = seed_matter(self.profile, f, p, "M")
        paid = memo_with_total(self.profile, m, 500)
        payments.add_payment_to_memo(
            self.profile, paid.pk, dict(amount=500, date_of_payment="2026-08-01")
        )
        scope = outstanding.list_outstanding_scope(self.profile, {})
        self.assertEqual(scope["firms"], [])
        self.assertEqual(scope["partners"], [])

    def test_query_count_is_two(self):
        f, p = seed_firm(self.profile, "Firm", "G")
        m = seed_matter(self.profile, f, p, "M")
        for i in range(5):
            memo_with_total(self.profile, m, 1000, date=f"2026-0{i + 1}-01")
        with self.assertNumQueries(2):
            scope = outstanding.list_outstanding_scope(self.profile, {})
            self.assertEqual(len(scope["firms"]), 1)
