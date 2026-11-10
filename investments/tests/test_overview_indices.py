"""Owner round (2026-11): the Overview's chosen figures and periods, indices (add, delete, sector index per investment), the column
picker switch and the Annual Report's "Fresh investments" line."""
from datetime import date as d, timedelta
from decimal import Decimal as D
from unittest import mock

from django.urls import reverse

from accounts.models import ROLE_READER
from investments.adapters import http
from investments.errors import InvestmentsError
from investments.models import CatalogueHistory, Instrument, InvestmentSettings, PinnedPrice, Price, ProfileInvestment
from investments.services import core, dashboard, indices, masters, overview
from investments.tests.base import InvTestCase, make_user
from investments.tests.fakehttp import FakeNet, fixture


def _prices(inst, start, end, base, rate):
    day = start
    while day <= end:
        Price.objects.create(instrument=inst, date=day, close=D(base) * (D(rate) ** (day - start).days), source="api")
        day += timedelta(days=1)


class OverviewTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.nifty = Instrument.objects.get(code="^NSEI")
        _prices(self.nifty, d(2019, 1, 1), d(2024, 6, 30), 10000, "1.0002")
        _prices(self.reliance, d(2019, 1, 1), d(2024, 6, 30), 100, "1.0004")

    def test_standard_choice_and_cleaning(self):
        row = core.get_settings(self.profile)
        self.assertEqual(overview.choice(row), {"boxes": ["value", "invested", "gain", "xirr", "index_xirr", "alpha"],
                                                "metrics": ["xirr", "index_xirr", "alpha", "fresh", "gain"], "periods": ["all", "5", "3", "1"]})
        self.assertEqual(overview.clean(["count", "bogus"], ["drawdown"], ["1", "7"]), {"boxes": ["count"], "metrics": ["drawdown"], "periods": ["1"]})

    def test_period_figures(self):
        self.buy(d(2019, 1, 1), 10, 100)
        self.buy(d(2022, 6, 1), 10, D(100) * D("1.0004") ** 1247)
        row = core.get_settings(self.profile)
        masters.update_settings(self.profile, self.user, overview=overview.clean([], [m[0] for m in overview.METRICS], ["all", "1"]))
        data = dashboard.load(self.profile, as_of=d(2024, 1, 1))
        table = data["overview"]
        self.assertEqual([p["id"] for p in table["periods"]], ["all", "1"])
        rows = {r["id"]: r["values"] for r in table["rows"]}
        self.assertAlmostEqual(rows["xirr"][1], 1.0004 ** 365 - 1, places=2)       # the price grows 0.04% a day
        self.assertAlmostEqual(rows["index_xirr"][1], 1.0002 ** 365 - 1, places=2)
        self.assertAlmostEqual(rows["alpha"][1], rows["xirr"][1] - rows["index_xirr"][1], places=9)
        self.assertEqual(rows["put_in"][1], D(0))                                   # nothing bought in the last year
        self.assertGreater(rows["put_in"][0], D(1000))
        self.assertEqual(rows["fresh"][0], rows["put_in"][0] - rows["taken_out"][0])
        self.assertEqual(rows["gain"][1], rows["end_value"][1] - rows["start_value"][1] - rows["fresh"][1])
        self.assertEqual(rows["realised"][0], D(0))
        self.assertIsNotNone(rows["twr"][0])
        self.assertGreaterEqual(rows["drawdown"][0], 0)
        self.assertTrue(row.pk)

    def test_customise_is_for_editors_and_the_page_shows_the_choice(self):
        self.buy(d(2023, 1, 2), 10, 100)
        self.client.force_login(self.user)
        page = self.client.get(reverse("investments_dashboard") + "?customise=1")
        self.assertContains(page, "Customise the Overview")
        self.assertContains(page, "Over time")
        self.client.post(reverse("investments_overview_save"), {"box": ["count", "value"], "metric": ["dividends"], "period": ["3"]})
        self.assertEqual(InvestmentSettings.objects.get(profile=self.profile).overview, {"boxes": ["count", "value"], "metrics": ["dividends"], "periods": ["3"]})
        page = self.client.get(reverse("investments_dashboard")).content.decode()
        self.assertIn(">Holdings</div>", page)
        self.assertNotIn(">Portfolio XIRR</div>", page)
        self.assertIn("Dividends received</td>", page)
        self.client.post(reverse("investments_overview_save"), {"standard": "1"})
        self.assertEqual(InvestmentSettings.objects.get(profile=self.profile).overview, {})
        reader, _ = make_user("rd-ov", role=ROLE_READER, profile=self.profile)
        self.client.force_login(reader)
        self.assertEqual(self.client.post(reverse("investments_overview_save"), {"standard": "1"}).status_code, 403)


class IndexTests(InvTestCase):
    def net(self):
        net = FakeNet()
        net.add("CNXAUTO", fixture("yahoo_chart_reliance.json"))
        return mock.patch.object(http, "_urlopen", net), mock.patch.object(http, "sleep", lambda s: None)

    def test_add_an_index_by_its_yahoo_symbol_and_refuse_an_unknown_one(self):
        a, b = self.net()
        with a, b:
            inst, n = indices.add_index(self.user, "Nifty Auto", "^cnxauto", today=d(2026, 11, 9))
            with self.assertRaises(InvestmentsError) as cm:
                indices.add_index(self.user, "Again", "^CNXAUTO", today=d(2026, 11, 9))
            self.assertEqual(cm.exception.code, "EXISTS")
            with self.assertRaises(InvestmentsError):
                indices.add_index(self.user, "Nothing", "^NOSUCH", today=d(2026, 11, 9))
        self.assertEqual((inst.kind, inst.code, inst.price_source), ("index", "^CNXAUTO", "yahoo"))
        self.assertGreater(n, 0)
        self.assertFalse(Instrument.objects.filter(code="^NOSUCH").exists())
        self.assertTrue(CatalogueHistory.objects.filter(record_type="index_added").exists())

    def test_delete_refuses_built_in_and_needs_the_name_while_in_use(self):
        masters.ensure_builtin_indices()
        with self.assertRaises(InvestmentsError):
            indices.delete_index(self.user, Instrument.objects.get(code="^NSEI"))
        auto = Instrument.objects.create(profile=None, kind="index", name="Nifty Auto", code="^CNXAUTO", price_source="yahoo")
        masters.update_settings(self.profile, self.user, default_index=auto)
        with self.assertRaises(InvestmentsError) as cm:
            indices.delete_index(self.user, auto)
        self.assertEqual(cm.exception.code, "CONFIRM_NAME")
        self.assertEqual(indices.delete_index(self.user, auto, confirm_name="Nifty Auto"), 1)
        self.assertIsNone(InvestmentSettings.objects.get(profile=self.profile).default_index_id)
        self.assertEqual(masters.default_index_for(self.profile).code, "^NSEI")

    def test_sector_index_from_the_investment_page_and_in_bulk_pins_it(self):
        bank = Instrument.objects.create(profile=None, kind="index", name="Nifty Bank", code="^NSEBANK", price_source="yahoo", price_basis="split_adjusted")
        Price.objects.create(instrument=bank, date=d(2024, 1, 2), close=D(45000), source="api")
        self.buy(d(2024, 1, 2), 10, 100)
        self.client.force_login(self.user)
        page = self.client.get(reverse("investments_investment", args=[self.reliance.pk]))
        self.assertContains(page, 'name="sectoral_index"')
        self.client.post(reverse("investments_investment_details", args=[self.reliance.pk]), {"action": "save", "sectoral_index": bank.pk, "notes": "", "links": ""})
        self.assertEqual(ProfileInvestment.objects.get(profile=self.profile, instrument=self.reliance).sectoral_index, bank)
        self.assertTrue(PinnedPrice.objects.filter(instrument=bank, asked_date=d(2024, 1, 2), reason="transaction").exists())
        self.assertContains(self.client.get(reverse("investments_settings_indices")), f'name="sector_{self.reliance.pk}"')
        self.client.post(reverse("investments_indices_action"), {"action": "sectors", f"sector_{self.reliance.pk}": ""})
        self.assertIsNone(ProfileInvestment.objects.get(profile=self.profile, instrument=self.reliance).sectoral_index)


class SmallerChangesTests(InvTestCase):
    def test_column_picker_switch_loads_the_fee_register_menu(self):
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get(reverse("investments_holdings")), "js/fees/columns.js")
        masters.update_settings(self.profile, self.user, column_picker=True)
        self.assertContains(self.client.get(reverse("investments_holdings")), "js/fees/columns.js")
        self.assertContains(self.client.get(reverse("investments_settings_display")), 'name="column_picker"')

    def test_annual_report_says_fresh_investments(self):
        self.client.force_login(self.user)
        page = self.client.get(reverse("investments_annual"))
        self.assertContains(page, "Fresh investments")
        self.assertNotContains(page, "re-invested")


class BuiltInAndDecimalsTests(InvTestCase):
    def test_nifty_50_is_the_only_built_in_index(self):
        masters.ensure_builtin_indices()
        self.assertEqual(list(Instrument.objects.filter(kind="index").values_list("code", flat=True)), ["^NSEI"])
        self.assertTrue(indices.is_builtin(Instrument.objects.get(code="^NSEI")))
        self.assertIn(("Sensex", "^BSESN"), indices.SUGGESTED)

    def test_decimals_chosen_in_settings_change_only_the_display(self):
        self.buy(d(2024, 1, 2), "4820.5126", "100.5")
        self.client.force_login(self.user)
        r = self.client.post(reverse("investments_settings_display"), {"my_money": "auto", "money_default": "auto", "default_exchange": "NS",
                                                                        "units_decimals": "2", "rupee_decimals": "2"})
        self.assertEqual(r.status_code, 302)
        row = InvestmentSettings.objects.get(profile=self.profile)
        self.assertEqual((row.units_decimals, row.rupee_decimals), (2, 2))
        html = self.client.get(reverse("investments_transactions")).content.decode()
        self.assertIn("4,820.51", html)
        self.assertNotIn("4,820.5126", html)
        self.assertIn('data-full="₹4,84,461.52"', html)                # 4820.5126 x 100.5 = 484461.5163, two decimals
        self.client.post(reverse("investments_settings_display"), {"my_money": "auto", "money_default": "auto", "default_exchange": "NS",
                                                                    "units_decimals": "", "rupee_decimals": ""})
        html = self.client.get(reverse("investments_transactions")).content.decode()
        self.assertIn("4,820.5126", html)
