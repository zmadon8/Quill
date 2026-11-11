"""Owner round (2026-11): the Overview cards and Home XIRR can use a chosen period (User.investments_period)."""
from datetime import date as d, timedelta
from decimal import Decimal as D

from investments.models import Instrument, Price
from investments.services import core, dashboard, holdings, overview, performance
from investments.tests.base import InvTestCase


class CardPeriodTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.nifty = Instrument.objects.get(code="^NSEI")
        day = d(2022, 1, 1)
        while day <= d(2024, 6, 30):
            n = (day - d(2022, 1, 1)).days
            Price.objects.create(instrument=self.nifty, date=day, close=D(10000) * (D("1.0002") ** n), source="api")
            Price.objects.create(instrument=self.reliance, date=day, close=D(100) * (D("1.0004") ** n), source="api")
            day += timedelta(days=1)
        self.buy(d(2022, 1, 1), 10, 100)
        self.as_of = d(2024, 1, 1)
        self.settings_row = core.get_settings(self.profile, create=False)
        _rows, self.totals = holdings.compute(self.profile, as_of=self.as_of, settings=self.settings_row)
        self.index = performance._default_index(self.profile, self.settings_row)

    def figures(self, key):
        return overview.period_figures(self.profile, portfolio=None, broker=None, as_of=self.as_of, include_dividends=None,
                                       settings_row=self.settings_row, totals=self.totals, period_key=key, index=self.index)

    def test_all_has_no_override(self):
        self.assertIsNone(self.figures("all"))

    def test_period_longer_than_history_equals_the_whole_history(self):
        fig = self.figures("5y")
        self.assertEqual(fig["gain"], self.totals.gain)
        self.assertAlmostEqual(fig["xirr"], self.totals.xirr, places=6)

    def test_short_period_uses_the_opening_value(self):
        fig = self.figures("1y")
        start = self.as_of - timedelta(days=365)
        opening = holdings.compute(self.profile, as_of=start, settings=self.settings_row)[1].value
        self.assertEqual(fig["start"], start)
        self.assertEqual(fig["gain"], self.totals.value - opening)
        self.assertAlmostEqual(fig["xirr"], 1.0004 ** 365 - 1, places=3)
        self.assertGreater(fig["alpha"], 0)

    def test_cache_keeps_periods_apart(self):
        self.assertNotEqual(dashboard._params(self.profile, None, None, self.as_of, None, "1y"),
                            dashboard._params(self.profile, None, None, self.as_of, None, "3m"))
        self.assertEqual(dashboard._params(self.profile, None, None, self.as_of, None),
                         dashboard._params(self.profile, None, None, self.as_of, None, "all"))
        whole = dashboard.load(self.profile, as_of=self.as_of)
        year = dashboard.load(self.profile, as_of=self.as_of, period="1y")
        self.assertNotIn("period_totals", whole)
        self.assertEqual(year["period_totals"]["start"], self.as_of - timedelta(days=365))
        self.assertEqual(year["totals"]["gain"], whole["totals"]["gain"])
