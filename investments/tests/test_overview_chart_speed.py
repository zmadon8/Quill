"""Item 4 (owner round): padded Overview cards, no Holdings table on the Overview, one value-against-the-index chart with period
buttons on the Overview and on each investment, and bounded query counts."""
from datetime import date as d, timedelta
from decimal import Decimal as D

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from investments.models import Instrument, Price
from investments.services import masters
from investments.tests.base import InvTestCase


class OverviewChartTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        nifty = Instrument.objects.get(code="^NSEI")
        start = d.today() - timedelta(days=400)
        for n in range(401):
            day = start + timedelta(days=n)
            Price.objects.create(instrument=nifty, date=day, close=D(10000) + n, source="api")
            Price.objects.create(instrument=self.reliance, date=day, close=D(100) + D(n) / 10, source="api")
        self.buy(start + timedelta(days=5), 10, 100)

    def test_no_holdings_table_on_the_overview_but_a_link_to_the_holdings_page(self):
        page = self.client.get(reverse("investments_dashboard")).content.decode()
        self.assertNotIn('data-table-id="inv-dashboard-1"', page)
        self.assertNotIn("Avg cost", page)
        self.assertIn(reverse("investments_holdings"), page)
        self.assertIn('data-table-id="inv-holdings', self.client.get(reverse("investments_holdings")).content.decode())

    def test_cards_are_padded_on_the_left(self):
        css = open("static/css/investments.css").read()
        self.assertNotIn(".strip .f:first-child{border-left:0;padding-left:0}", css)
        self.assertNotIn("padding-left:0}\nbody.inv .strip .f:nth-child(even)", css)
        self.assertIn("body.inv .strip .f{padding:14px 18px", css)

    def test_overview_chart_has_index_line_and_every_period(self):
        page = self.client.get(reverse("investments_dashboard")).content.decode()
        self.assertIn("Same money in", page)
        self.assertIn('aria-label="Chart period"', page)
        for label in ("1M", "3M", "6M", "1Y", "3Y", "5Y", "All"):
            self.assertIn(f">{label}</a>", page)
        self.assertIn('class="on" aria-current="true">All</a>', page)
        page = self.client.get(reverse("investments_dashboard") + "?range=3m").content.decode()
        self.assertIn('class="on" aria-current="true">3M</a>', page)
        self.assertIn("Same money in", page)

    def test_investment_chart_mirrors_the_overview(self):
        url = reverse("investments_investment", args=[self.reliance.pk])
        page = self.client.get(url + "?range=6m").content.decode()
        self.assertIn('aria-label="Chart period"', page)
        self.assertIn("Same money in", page)
        self.assertIn('class="on" aria-current="true">6M</a>', page)
        self.assertIn("Value against the same money in the index", page)


class QueryCountTests(InvTestCase):
    def count(self, name, *args):
        self.client.force_login(self.user)
        self.client.get(reverse(name, args=args))          # warm: the first visit stores the cached figures
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200)
        return len(ctx)

    def test_overview_queries_do_not_grow_with_the_number_of_holdings(self):
        self.buy(d(2024, 1, 2), 10, 100)
        few = self.count("investments_dashboard")
        for n in range(8):
            inst = masters.create_instrument(self.profile, self.user, kind="share", name=f"Extra {n}", code=f"X{n}.NS")
            self.buy(d(2024, 2, 1), 5, 50, instrument=inst)
        self.assertLessEqual(self.count("investments_dashboard"), few + 2)
