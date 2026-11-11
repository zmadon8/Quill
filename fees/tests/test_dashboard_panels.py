"""Owner round 2026-11: Dashboard 'Billed by month' and 'Who owes the most', the Outstanding ageing cards and share bars,
and status pills."""
import datetime
from decimal import Decimal

from django.urls import reverse

from fees.models import Memo
from fees.services import dashboard_panels, outstanding
from fees.tests.test_ui_pages import UiPageBase


class PanelServiceTests(UiPageBase):
    NOW = datetime.date(2026, 11, 10)

    def test_billed_by_month_is_april_to_march_from_the_stored_totals(self):
        fy, months = dashboard_panels.billed_by_month(self.profile, self.NOW)
        self.assertEqual(fy, "2026-27")
        self.assertEqual([m["label"] for m in months][:3], ["Apr", "May", "Jun"])
        self.assertEqual(len(months), 12)
        expected = {}
        for memo in Memo.objects.filter(profile=self.profile, is_draft=False, financial_year="2026-27"):
            expected[memo.date.month] = expected.get(memo.date.month, Decimal("0")) + memo.total_fees
        for m in months:
            self.assertEqual(Decimal(m["amount"]), expected.get(m["month"], Decimal("0")), m["label"])
        current = [m for m in months if m["is_current"]]
        self.assertEqual([m["label"] for m in current], ["Nov"])
        self.assertTrue(all(m["is_future"] for m in months[8:]))

    def test_panels_list_who_owes_the_most_with_shares(self):
        panels = dashboard_panels.get_panels(self.profile, self.NOW)
        by_firm = outstanding.list_outstanding_by_firm(self.profile, {}, "amount")
        self.assertEqual([o["firm_id"] for o in panels["owers"]], [r["firm_id"] for r in by_firm][:5])
        self.assertEqual(panels["outstanding_total"], sum((r["outstanding"] for r in by_firm), Decimal("0")))
        for o in panels["owers"]:
            self.assertTrue(0 <= o["share"] <= 100)
        self.assertTrue(all(0 <= m["height"] <= 100 for m in panels["months"]))

    def test_home_figures(self):
        figures = dashboard_panels.home_figures(self.profile, self.NOW)
        self.assertEqual(figures["drafts"], Memo.objects.filter(profile=self.profile, is_draft=True).count())
        self.assertEqual(figures["memos_fy"], Memo.objects.filter(profile=self.profile, is_draft=False, financial_year="2026-27").count())

    def test_ageing_buckets(self):
        today = datetime.date(2026, 11, 10)
        self.assertEqual(outstanding.age_bucket(datetime.date(2026, 11, 1), today), 0)
        self.assertEqual(outstanding.age_bucket(datetime.date(2026, 10, 11), today), 0)
        self.assertEqual(outstanding.age_bucket(datetime.date(2026, 10, 10), today), 1)
        self.assertEqual(outstanding.age_bucket(datetime.date(2026, 8, 12), today), 2)
        self.assertEqual(outstanding.age_bucket(datetime.date(2025, 1, 1), today), 3)
        self.assertEqual(outstanding.age_bucket(None, today), 0)
        rows = outstanding.list_outstanding_by_firm(self.profile, {}, "amount", today=today)
        totals = outstanding.ageing_totals(rows)
        self.assertEqual([t["key"] for t in totals], ["0-30", "31-60", "61-90", "90+"])
        self.assertEqual(sum((t["amount"] for t in totals), Decimal("0")), sum((r["outstanding"] for r in rows), Decimal("0")))
        self.assertEqual(sum(t["memo_count"] for t in totals), sum(r["memo_count"] for r in rows))


class PanelPageTests(UiPageBase):
    def test_dashboard_shows_the_chart_and_who_owes_the_most(self):
        text = self.html(self.page("fees_dashboard"))
        self.assertIn('aria-labelledby="billed-heading"', text)
        self.assertIn(">Billed by month</h2>", text)
        self.assertEqual(text.count('<li class="bar'), 12)
        self.assertIn('aria-current="true"', text)
        self.assertIn(">Who owes the most</h2>", text)
        self.assertIn(reverse("fees_outstanding_detail") + "?firm=", text)

    def test_outstanding_shows_ageing_cards_and_share_bars(self):
        text = self.html(self.page("fees_outstanding"))
        self.assertIn('aria-label="Outstanding by age of the memo"', text)
        for label in ("0-30 days", "31-60 days", "61-90 days", "Over 90 days"):
            self.assertIn(label, text)
        self.assertIn(">Share of total</th>", text)
        self.assertIn('class="share-bar"', text)
