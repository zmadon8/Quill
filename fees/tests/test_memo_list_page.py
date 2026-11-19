"""``memo_lists.list_page`` gives exactly what ``list_memos`` + ``paginate`` + ``footer_totals`` give, with the database doing
the counting, adding up and paging. The old functions are the oracle: a seeded random register (overrides, ties in the rounding,
part and over payments, drafts, written-off memos, several years, firms and matters) is compared for every filter and page."""
import random
from decimal import Decimal
from unittest import mock

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from fees.errors import FeesError
from fees.models import FeesSettings, Memo
from fees.services import memo_lists, memos, payments
from fees.tests.test_memo_lists import base_input, fees_profile, seed_matter

AMOUNTS = ["2.20", "10.10", "0", "1234.57", "99999.99", "4500", "17.45"]


def build_register(profile, seed=7, count=70, rate="7.5"):
    FeesSettings.objects.update_or_create(profile=profile, defaults={"default_tds_rate": Decimal(rate), "overdue_days": 30})
    rng = random.Random(seed)
    matters = [seed_matter(profile, f"Firm {n}", f"Matter {n}")[2] for n in range(3)]
    made = []
    for n in range(count):
        data = base_input(
            rng.choice(matters).pk,
            date=f"{rng.choice([2024, 2025, 2026])}-{rng.choice(['04', '08', '11', '02'])}-{rng.randint(10, 28)}",
            num_appearances=rng.randint(0, 3),
            fees_per_appearance=rng.choice([0, 1500, 5000]),
            fees_misc_drafting=rng.choice(AMOUNTS),
        )
        if rng.random() < 0.15:
            data["custom_total_fees"] = rng.choice(["777.77", "250.05", "12000"])
        memo = memos.create_memo(profile, data, is_draft=rng.random() < 0.1)
        made.append(memo)
    for memo in made:
        memo.refresh_from_db()
        if memo.is_draft or rng.random() < 0.35:
            continue
        total = memo.total_fees
        amount = (total * Decimal(rng.choice(["0.2", "0.5", "1", "1.1"]))).quantize(Decimal("0.01"))
        if amount > 0:
            payments.add_payment_to_memo(profile, memo.pk, dict(amount=amount, date_of_payment="2026-12-01"))
    for memo in made[::9]:
        if not memo.is_draft:
            try:
                memos.set_memo_written_off(profile, memo.pk, True)
            except FeesError:
                pass  # a fully paid memo cannot be written off
    return matters


def oracle(profile, filters, draft_mode, page, size):
    items = memo_lists.list_memos(profile, filters, draft_mode=draft_mode)
    page_items, meta = memo_lists.paginate(items, page, size)
    return page_items, meta, memo_lists.footer_totals(items)


class ListPageTests(TestCase):
    def setUp(self):
        self.profile = fees_profile("Page-Fees")
        self.matters = build_register(self.profile)

    def check(self, filters, draft_mode="exclude_drafts", page=1, size=None):
        got = memo_lists.list_page(self.profile, filters, draft_mode, page, size)
        want = oracle(self.profile, filters, draft_mode, page, size)
        label = f"{filters} {draft_mode} page {page} size {size}"
        self.assertEqual(got[1], want[1], label)
        self.assertEqual(got[2], want[2], label)
        self.assertEqual(got[0], want[0], label)

    def test_every_filter_and_page_matches_the_old_functions(self):
        year = Memo.objects.filter(profile=self.profile, is_draft=False).values_list("financial_year", flat=True).first()
        filter_sets = [
            {}, {"unpaid_only": True}, {"financial_year": year}, {"financial_year": year, "unpaid_only": True},
            {"firm_id": self.matters[0].firm_id}, {"matter_id": self.matters[1].pk},
            {"group_id": self.matters[2].group_id, "unpaid_only": True}, {"financial_year": "1999-00"},
        ]
        for filters in filter_sets:
            for mode in ("exclude_drafts", "drafts_only", "all"):
                for page, size in ((1, None), (1, 7), (2, 7), (3, 10), (99, 7), (0, 5)):
                    self.check(filters, mode, page, size)

    def test_totals_do_not_depend_on_the_page(self):
        first = memo_lists.list_page(self.profile, {}, "exclude_drafts", 1, 5)
        last = memo_lists.list_page(self.profile, {}, "exclude_drafts", 99, 5)
        self.assertEqual(first[2], last[2])
        self.assertEqual(first[1]["total"], first[2]["count"])
        self.assertLessEqual(len(first[0]), 5)

    def test_a_tie_in_the_rounding_goes_the_same_way(self):
        # 2.20 at 12.5% TDS is 0.275: half away from zero is 0.28, so net 1.92 (not 1.93).
        FeesSettings.objects.filter(profile=self.profile).update(default_tds_rate=Decimal("12.5"))
        memos.create_memo(self.profile, base_input(self.matters[0].pk, num_appearances=0, num_conferences=0, fees_misc_drafting="2.20", date="2026-12-20"))
        self.check({}, "exclude_drafts", 1, None)
        self.check({"unpaid_only": True}, "exclude_drafts", 1, 3)

    def test_an_empty_list(self):
        page_items, meta, totals = memo_lists.list_page(self.profile, {"financial_year": "1999-00"}, "all", 1, 10)
        self.assertEqual((page_items, meta["total"], meta["total_pages"], totals["count"]), ([], 0, 1, 0))
        self.assertEqual(totals["total_fees"], Decimal("0.00"))

    def test_three_queries_whatever_the_size(self):
        with CaptureQueriesContext(connection) as ctx:
            memo_lists.list_page(self.profile, {}, "exclude_drafts", 1, 10)
        if connection.vendor == "postgresql":
            self.assertEqual(len(ctx), 3)  # settings, the totals, the page's rows
        else:
            self.assertEqual(len(ctx), 2)  # SQLite: the old path (settings, rows)

    def test_a_drifted_stored_total_falls_back_to_the_full_path(self):
        memo = Memo.objects.filter(profile=self.profile, is_draft=False).order_by("is_draft", "-financial_year", "-seq", "-id").first()
        Memo.objects.filter(pk=memo.pk).update(total_fees=Decimal("1.00"))  # no longer what the fee rule gives
        with mock.patch.object(memo_lists, "logger") as log:
            got = memo_lists.list_page(self.profile, {}, "exclude_drafts", 1, 10)
        want = oracle(self.profile, {}, "exclude_drafts", 1, 10)
        self.assertEqual(got, want)
        if connection.vendor == "postgresql":
            self.assertTrue(log.warning.called)

    def test_another_profile_is_not_mixed_in(self):
        other = fees_profile("Page-Other")
        build_register(other, seed=3, count=10)
        mine = memo_lists.list_page(self.profile, {}, "all", 1, None)
        self.assertEqual(mine[2]["count"], Memo.objects.filter(profile=self.profile).count())
