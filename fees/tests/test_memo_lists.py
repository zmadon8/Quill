"""Memo listing tests for the Fee Register (T3.1, R-MEMO-7, brief 5.4 to 5.6).

Ports the list / filter parts of ``memoService.test.ts`` (the
``memoService - list & filters`` block and the draft-exclusion assertions from
the drafts block; the create / update / fee / draft-lifecycle / write-off tests
were ported in Phase 2's ``test_memos.py`` and are not duplicated here) and adds
coverage for the web-only read helpers: per-matter listing, drafts-only listing,
recent matters, pagination and the aggregated FOOTER TOTALS.

Every list path asserts a tight ``assertNumQueries`` bound so a regression that
re-introduces a per-row query (an N+1) fails the suite: ``list_memos`` and its
footer totals are two queries (settings + rows), and ``list_recent_matters`` is
two (the grouped aggregate + one ``IN`` query for the latest memo per matter).

These tests use the ORM, so Django ``TestCase`` is used and everything is scoped
to a ``Profile(program="fees")``. Memos are created via ``memos.create_memo`` so
``total_fees`` is stored, and payments via ``payments.add_payment_to_memo`` so
the stored paid columns are maintained; the firm / group / matter helpers mirror
``test_memos.py`` and ``test_payments.py``.
"""
from decimal import Decimal

from django.test import TestCase

from accounts.models import Profile
from accounts.suite import KEY_FEES
from fees.models import Firm, Group, Matter
from fees.services import memo_lists, memos, payments


def fees_profile(name="Ziyad-Fees"):
    return Profile.objects.create(program=KEY_FEES, name=name)


def seed_matter(profile, firm_name="Firm", matter_name="Matter", archived=False):
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


# ---------------------------------------------------------------------------
# list & filters (ports memoService - list & filters)
# ---------------------------------------------------------------------------

class ListMemosTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, self.group, self.matter = seed_matter(self.profile)

    def test_lists_newest_first_and_filters_unpaid(self):
        a = memos.create_memo(self.profile, base_input(self.matter.pk))
        b = memos.create_memo(
            self.profile, base_input(self.matter.pk, date="2026-09-01")
        )
        payments.add_payment_to_memo(
            self.profile,
            b.pk,
            dict(amount=14000, date_of_payment="2026-10-01"),
        )
        all_rows = memo_lists.list_memos(self.profile, {})
        self.assertEqual(
            [row["memo_number"] for row in all_rows],
            ["2026-27/2", "2026-27/1"],
        )
        unpaid = memo_lists.list_memos(self.profile, {"unpaid_only": True})
        self.assertEqual([row["id"] for row in unpaid], [a.pk])

    def test_amount_received_excludes_tds_while_gross_drives_paid(self):
        memo = memos.create_memo(self.profile, base_input(self.matter.pk))  # total 14000
        # Net 12600 received + 1400 TDS = 14000 gross -> fully settles the memo.
        payments.add_payment_to_memo(
            self.profile,
            memo.pk,
            dict(
                amount=12600,
                auto_tds=False,
                tds_amount=1400,
                date_of_payment="2026-08-01",
            ),
        )
        row = memo_lists.list_memos(self.profile, {})[0]
        self.assertEqual(row["amount_paid"], Decimal("14000.00"))  # gross
        self.assertEqual(row["amount_received"], Decimal("12600.00"))  # net
        self.assertEqual(row["amount_tds"], Decimal("1400.00"))
        self.assertEqual(row["amount_due"], Decimal("0.00"))  # total - gross
        self.assertEqual(row["status"], "Paid")  # gross covers the total

    def test_amount_due_is_total_minus_gross_and_can_be_positive(self):
        memo = memos.create_memo(self.profile, base_input(self.matter.pk))  # total 14000
        payments.add_payment_to_memo(
            self.profile,
            memo.pk,
            dict(amount=4000, date_of_payment="2026-08-01"),
        )
        row = memo_lists.list_memos(self.profile, {})[0]
        self.assertEqual(row["amount_due"], Decimal("10000.00"))  # 14000 - 4000 gross
        self.assertEqual(row["amount_tds"], Decimal("0.00"))
        self.assertEqual(row["status"], "Unpaid")

    def test_filter_by_financial_year_firm_and_matter(self):
        _, _, other_matter = seed_matter(
            self.profile, firm_name="Other", matter_name="Other matter"
        )
        here = memos.create_memo(self.profile, base_input(self.matter.pk))
        there = memos.create_memo(self.profile, base_input(other_matter.pk))

        by_fy = memo_lists.list_memos(self.profile, {"financial_year": "2026-27"})
        self.assertEqual({row["id"] for row in by_fy}, {here.pk, there.pk})
        self.assertEqual(memo_lists.list_memos(self.profile, {"financial_year": "1999-00"}), [])

        by_firm = memo_lists.list_memos(self.profile, {"firm_id": self.matter.firm_id})
        self.assertEqual([row["id"] for row in by_firm], [here.pk])

        by_matter = memo_lists.list_memos(self.profile, {"matter_id": other_matter.pk})
        self.assertEqual([row["id"] for row in by_matter], [there.pk])

    def test_filter_by_group_and_selected_matter_ids(self):
        _, _, other_matter = seed_matter(
            self.profile, firm_name="Other", matter_name="Other matter"
        )
        here = memos.create_memo(self.profile, base_input(self.matter.pk))
        there = memos.create_memo(self.profile, base_input(other_matter.pk))

        by_group = memo_lists.list_memos(self.profile, {"group_id": self.group.pk})
        self.assertEqual([row["id"] for row in by_group], [here.pk])

        selected = memo_lists.list_memos(
            self.profile, {"selected_matter_ids": [other_matter.pk]}
        )
        self.assertEqual([row["id"] for row in selected], [there.pk])

        # partner_id is an accepted alias for group_id; "none" is a no-op.
        self.assertEqual(
            {row["id"] for row in memo_lists.list_memos(self.profile, {"partner_id": "none"})},
            {here.pk, there.pk},
        )

    def test_excludes_other_profiles(self):
        other = fees_profile(name="Other-Fees")
        _, _, other_matter = seed_matter(other)
        memos.create_memo(self.profile, base_input(self.matter.pk))
        memos.create_memo(other, base_input(other_matter.pk))
        mine = memo_lists.list_memos(self.profile, {})
        self.assertEqual(len(mine), 1)

    def test_list_query_count_is_two(self):
        for i in range(5):
            m = memos.create_memo(
                self.profile, base_input(self.matter.pk, date=f"2026-0{i + 1}-01")
            )
            payments.add_payment_to_memo(
                self.profile, m.pk, dict(amount=1000, date_of_payment="2026-08-01")
            )
        # One query for settings, one for the rows (no per-row N+1 for firm/matter
        # names or paid columns).
        with self.assertNumQueries(2):
            rows = memo_lists.list_memos(self.profile, {})
            self.assertEqual(len(rows), 5)

    def test_footer_totals_reuse_rows_without_extra_query(self):
        a = memos.create_memo(self.profile, base_input(self.matter.pk))  # total 14000
        memos.create_memo(
            self.profile, base_input(self.matter.pk, date="2026-09-01")
        )  # total 14000
        payments.add_payment_to_memo(
            self.profile,
            a.pk,
            dict(amount=5000, date_of_payment="2026-08-01"),
        )
        # Two queries build the list; the footer totals add none (pure in-memory).
        with self.assertNumQueries(2):
            rows = memo_lists.list_memos(self.profile, {})
        with self.assertNumQueries(0):
            totals = memo_lists.footer_totals(rows)
        self.assertEqual(totals["count"], 2)
        self.assertEqual(totals["total_fees"], Decimal("28000.00"))  # 14000 + 14000
        self.assertEqual(totals["net_of_tds"], Decimal("25200.00"))  # 12600 * 2
        self.assertEqual(totals["amount_received"], Decimal("5000.00"))
        self.assertEqual(totals["amount_tds"], Decimal("0.00"))
        self.assertEqual(totals["amount_due"], Decimal("23000.00"))  # 9000 + 14000

    def test_footer_totals_honour_unpaid_filter(self):
        memos.create_memo(self.profile, base_input(self.matter.pk))  # total 14000
        b = memos.create_memo(
            self.profile, base_input(self.matter.pk, date="2026-09-01")
        )
        payments.add_payment_to_memo(
            self.profile, b.pk, dict(amount=14000, date_of_payment="2026-10-01")
        )
        unpaid = memo_lists.list_memos(self.profile, {"unpaid_only": True})
        totals = memo_lists.footer_totals(unpaid)
        self.assertEqual(totals["count"], 1)
        self.assertEqual(totals["total_fees"], Decimal("14000.00"))
        self.assertEqual(totals["amount_due"], Decimal("14000.00"))


# ---------------------------------------------------------------------------
# drafts, per-matter listing (ports the draft-exclusion assertions)
# ---------------------------------------------------------------------------

class DraftListingTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, self.group, self.matter = seed_matter(self.profile)

    def test_draft_excluded_from_main_list_but_in_drafts(self):
        draft = memos.create_memo(self.profile, base_input(self.matter.pk), is_draft=True)
        self.assertEqual(memo_lists.list_memos(self.profile, {}), [])
        drafts = memo_lists.list_drafts(self.profile)
        self.assertEqual([row["id"] for row in drafts], [draft.pk])
        # A draft shows a placeholder number in the list item.
        self.assertEqual(drafts[0]["memo_number"], "(draft)")
        self.assertTrue(drafts[0]["is_draft"])

    def test_per_matter_lists_both_drafts_and_finalised(self):
        final = memos.create_memo(self.profile, base_input(self.matter.pk))
        draft = memos.create_memo(self.profile, base_input(self.matter.pk), is_draft=True)
        rows = memo_lists.list_memos_for_matter(self.profile, self.matter.pk)
        self.assertEqual({row["id"] for row in rows}, {final.pk, draft.pk})
        # Finalised memos sort before drafts (is_draft ASC).
        self.assertEqual(rows[0]["id"], final.pk)
        self.assertEqual(rows[-1]["id"], draft.pk)

    def test_per_matter_scoped_to_the_matter(self):
        _, _, other_matter = seed_matter(
            self.profile, firm_name="Other", matter_name="Other matter"
        )
        mine = memos.create_memo(self.profile, base_input(self.matter.pk))
        memos.create_memo(self.profile, base_input(other_matter.pk))
        rows = memo_lists.list_memos_for_matter(self.profile, self.matter.pk)
        self.assertEqual([row["id"] for row in rows], [mine.pk])


# ---------------------------------------------------------------------------
# pagination
# ---------------------------------------------------------------------------

class PaginationTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter = seed_matter(self.profile)
        self.created = [
            memos.create_memo(
                self.profile, base_input(self.matter.pk, date=f"2026-{m:02d}-01")
            )
            for m in range(1, 8)  # 7 memos
        ]

    def test_no_page_size_returns_everything(self):
        rows = memo_lists.list_memos(self.profile, {})
        page_items, meta = memo_lists.paginate(rows)
        self.assertEqual(len(page_items), 7)
        self.assertEqual(meta["total"], 7)
        self.assertEqual(meta["total_pages"], 1)
        self.assertFalse(meta["has_prev"])
        self.assertFalse(meta["has_next"])

    def test_first_and_middle_and_last_page(self):
        rows = memo_lists.list_memos(self.profile, {})
        first, meta1 = memo_lists.paginate(rows, page=1, page_size=3)
        self.assertEqual(len(first), 3)
        self.assertEqual(meta1["total_pages"], 3)
        self.assertFalse(meta1["has_prev"])
        self.assertTrue(meta1["has_next"])

        last, meta3 = memo_lists.paginate(rows, page=3, page_size=3)
        self.assertEqual(len(last), 1)  # 7 = 3 + 3 + 1
        self.assertTrue(meta3["has_prev"])
        self.assertFalse(meta3["has_next"])

    def test_page_beyond_last_clamps_to_last(self):
        rows = memo_lists.list_memos(self.profile, {})
        page_items, meta = memo_lists.paginate(rows, page=99, page_size=3)
        self.assertEqual(meta["page"], 3)
        self.assertEqual(len(page_items), 1)

    def test_empty_list_paginates_cleanly(self):
        empty, meta = memo_lists.paginate([], page=1, page_size=10)
        self.assertEqual(empty, [])
        self.assertEqual(meta["total"], 0)
        self.assertEqual(meta["total_pages"], 1)


# ---------------------------------------------------------------------------
# recent matters (brief 5.6, Dashboard)
# ---------------------------------------------------------------------------

class RecentMattersTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter_a = seed_matter(
            self.profile, firm_name="Firm A", matter_name="Matter A"
        )
        _, _, self.matter_b = seed_matter(
            self.profile, firm_name="Firm B", matter_name="Matter B"
        )

    def test_orders_by_latest_memo_date_and_excludes_drafts(self):
        memos.create_memo(self.profile, base_input(self.matter_a.pk, date="2026-05-01"))
        latest_b = memos.create_memo(
            self.profile, base_input(self.matter_b.pk, date="2026-09-01")
        )
        # A draft on matter A must not promote it above matter B.
        memos.create_memo(self.profile, base_input(self.matter_a.pk), is_draft=True)

        recent = memo_lists.list_recent_matters(self.profile)
        self.assertEqual([r["matter_id"] for r in recent], [self.matter_b.pk, self.matter_a.pk])
        top = recent[0]
        self.assertEqual(top["matter_name"], "Matter B")
        self.assertEqual(top["firm_name"], "Firm B")
        self.assertEqual(top["last_memo_id"], latest_b.pk)
        self.assertEqual(top["last_memo_number"], latest_b.memo_number)
        self.assertEqual(top["memo_count"], 1)
        self.assertFalse(top["is_archived"])

    def test_limit_caps_the_result(self):
        memos.create_memo(self.profile, base_input(self.matter_a.pk, date="2026-05-01"))
        memos.create_memo(self.profile, base_input(self.matter_b.pk, date="2026-09-01"))
        self.assertEqual(len(memo_lists.list_recent_matters(self.profile, limit=1)), 1)

    def test_empty_when_only_drafts(self):
        memos.create_memo(self.profile, base_input(self.matter_a.pk), is_draft=True)
        self.assertEqual(memo_lists.list_recent_matters(self.profile), [])

    def test_recent_matters_query_count_is_two(self):
        memos.create_memo(self.profile, base_input(self.matter_a.pk, date="2026-05-01"))
        memos.create_memo(self.profile, base_input(self.matter_b.pk, date="2026-09-01"))
        with self.assertNumQueries(2):
            recent = memo_lists.list_recent_matters(self.profile)
            self.assertEqual(len(recent), 2)
