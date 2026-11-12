"""The Overview's breakdown table below the chart: Portfolio value by Type, by Portfolio or by Broker."""
from datetime import date as d, timedelta
from decimal import Decimal as D

from django.urls import reverse

from investments.models import Price
from investments.services import dashboard
from investments.tests.base import InvTestCase

CENT = D("0.01")


class BreakdownTests(InvTestCase):
    def setUp(self):
        super().setUp()
        today = d.today()
        self.buy(today - timedelta(days=40), 10, 100)
        self.buy(today - timedelta(days=30), 20, 50, instrument=self.fund, broker=self.groww)
        Price.objects.create(instrument=self.reliance, date=today, close=D(120), source="api")
        Price.objects.create(instrument=self.fund, date=today, close=D(55), source="api")

    def test_every_way_adds_up_to_the_overview_value(self):
        data = dashboard.load(self.profile)
        value = data["totals"]["value"].quantize(CENT)
        self.assertEqual(value, D("2300.00"))
        for key in ("type", "portfolio", "broker"):
            table = data["breakdown"][key]
            self.assertEqual(table["total"]["value"], value, key)
            self.assertEqual(sum((r["value"] for r in table["rows"]), D(0)), value, key)
            self.assertEqual(table["total"]["invested"], D("2000.00"), key)
            self.assertAlmostEqual(sum(r["share"] for r in table["rows"]), 1.0, places=6)
        self.assertEqual([r["name"] for r in data["breakdown"]["type"]["rows"]], ["Share", "Mutual fund"])
        self.assertEqual([r["name"] for r in data["breakdown"]["portfolio"]["rows"]], ["Main"])
        brokers = {r["name"]: r["value"] for r in data["breakdown"]["broker"]["rows"]}
        self.assertEqual(brokers, {"Zerodha": D("1200.00"), "Groww": D("1100.00")})

    def test_xirr_per_group_and_total(self):
        data = dashboard.load(self.profile)
        for key in ("type", "portfolio", "broker"):
            table = data["breakdown"][key]
            for r in table["rows"]:
                self.assertIsNotNone(r["xirr"], (key, r["name"]))
                self.assertGreater(r["xirr"], 0)
            self.assertEqual(table["total"]["xirr"], data["totals"]["xirr"])
        # One portfolio holds everything, so its XIRR is the total's.
        self.assertAlmostEqual(data["breakdown"]["portfolio"]["rows"][0]["xirr"], data["totals"]["xirr"], places=6)

    def test_xirr_column_is_shown(self):
        self.client.force_login(self.user)
        page = self.client.get(reverse("investments_dashboard") + "?breakdown=broker").content.decode()
        self.assertIn('<th class="r">XIRR</th><th class="r">Share</th>', page)

    def test_switching_renders_each_table(self):
        self.client.force_login(self.user)
        url = reverse("investments_dashboard")
        page = self.client.get(url).content.decode()
        self.assertEqual(page.count('data-table-id="inv-overview-breakdown"'), 1)
        self.assertIn("<td>Share</td>", page)
        self.assertIn("by Portfolio", page)
        self.assertIn("breakdown=broker#breakdown", page)
        page = self.client.get(url + "?breakdown=portfolio").content.decode()
        self.assertIn("<td>Main</td>", page)
        self.assertNotIn("<td>Share</td>", page)
        page = self.client.get(url + "?breakdown=broker").content.decode()
        self.assertIn("<td>Zerodha</td>", page)
        self.assertIn("<td>Groww</td>", page)

    def test_an_unknown_choice_falls_back_to_type(self):
        self.client.force_login(self.user)
        page = self.client.get(reverse("investments_dashboard") + "?breakdown=nonsense").content.decode()
        self.assertIn("<td>Share</td>", page)
        self.assertIn("<td>Mutual fund</td>", page)

    def test_login_is_required(self):
        response = self.client.get(reverse("investments_dashboard") + "?breakdown=broker")
        self.assertEqual(response.status_code, 302)


class BreakdownRoundingTests(InvTestCase):
    @staticmethod
    def fake(kind, value):
        from types import SimpleNamespace as NS

        return NS(blocked=False, instrument=NS(get_kind_display=lambda: kind), cost=D(0), value=D(value), awaiting=D(0), lots=[])

    def test_total_is_the_sum_of_the_rows_as_shown(self):
        held = [self.fake("Share", "0.005"), self.fake("Mutual fund", "0.005"), self.fake("Bond", "0.005")]
        table = dashboard._breakdowns(self.profile, held)["type"]
        self.assertEqual([r["value"] for r in table["rows"]], ["0.00"] * 3)
        self.assertEqual(table["total"]["value"], "0.00")

    def test_rows_add_to_total_with_fractional_values(self):
        held = [self.fake("Share", "10.004"), self.fake("Mutual fund", "10.004"), self.fake("Bond", "10.004")]
        table = dashboard._breakdowns(self.profile, held)["type"]
        self.assertEqual(sum((D(r["value"]) for r in table["rows"]), D(0)), D(table["total"]["value"]))

    def test_cache_key_carries_the_payload_version(self):
        params = dashboard._params(self.profile, None, None, d.today(), True)
        self.assertEqual(params["v"], dashboard.PAYLOAD_VERSION)
