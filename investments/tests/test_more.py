"""Foreign investments, SIP schedules, statement import, search, insights, other reports, alternative interest (plan 6, 9, 11, 22, 24.2)."""
import tempfile
from datetime import date as d, timedelta
from decimal import Decimal as D
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from investments.errors import InvestmentsError
from investments.models import Broker, FxRate, Instrument, ManualFxRate, Portfolio, Price, SipSchedule, Transaction, Transfer
from investments.services import fx, holdings, insights, masters, reports, search, sip, statement_import, transactions as tx
from investments.services.reports import REPORTS
from investments.tests.base import InvTestCase


def csv_file(text, suffix=".csv"):
    h = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False)
    h.write(text)
    h.close()
    return Path(h.name)


class ForeignTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.apple = masters.create_instrument(self.profile, self.user, kind="foreign", name="Apple Inc", code="AAPL", currency="USD")
        FxRate.objects.create(currency="USD", date=d(2024, 1, 2), rate=D("83"))
        FxRate.objects.create(currency="USD", date=d(2025, 1, 2), rate=D("86"))

    def test_rupee_amount_uses_the_days_rate_unless_given(self):
        t = self.buy(d(2024, 1, 3), 10, 180, instrument=self.apple, charges=D(2))
        self.assertEqual((t.fx_rate, t.rupee_amount), (D("83"), D("149566.00")))
        t2 = tx.add_transaction(self.profile, self.user, side="buy", instrument=self.apple, portfolio=self.portfolio, broker=self.zerodha, date=d(2024, 1, 3),
                                units=D(1), price=D(180), rupee_amount=D(15100))
        self.assertEqual(t2.fx_rate, (D(15100) / D(180)).quantize(D("0.000001")))
        with self.assertRaises(InvestmentsError):
            self.buy(d(2023, 1, 3), 1, 100, instrument=self.apple)          # no rate stored that early

    def test_value_uses_the_current_rate_and_currency_effect(self):
        from investments.services import investment_page
        self.buy(d(2024, 1, 3), 10, 180, instrument=self.apple)
        Price.objects.create(instrument=self.apple, date=d(2025, 1, 2), close=D(198), source="api")
        (h,), _ = holdings.compute(self.profile, as_of=d(2025, 1, 3))
        self.assertEqual(h.value, D(10) * D(198) * D(86))
        f = investment_page.foreign_figures(self.profile, self.apple, h, d(2025, 1, 3))
        self.assertAlmostEqual(f["local_pct"], 0.10)
        self.assertAlmostEqual(f["rupee_pct"], (198 * 86) / (180 * 83) - 1)
        self.assertAlmostEqual(f["effect"], f["rupee_pct"] - 0.10)

    def test_manual_rate_wins(self):
        fx.set_manual("USD", d(2025, 1, 2), D("85.5"))
        self.assertEqual(fx.rate_on("USD", d(2025, 1, 5))[1:], (D("85.5"), "manual"))
        self.assertEqual(fx.rate_on("INR", d(2025, 1, 5))[1], D(1))
        self.assertTrue(ManualFxRate.objects.exists())


class SipTests(InvTestCase):
    def test_entries_are_made_from_that_days_nav_as_pending_then_confirmed(self):
        s = sip.add(self.profile, self.user, instrument=self.fund, amount=D(5000), day_of_month=5, portfolio=self.portfolio, broker=self.zerodha,
                    start_date=d(2026, 9, 1))
        Price.objects.create(instrument=self.fund, date=d(2026, 9, 7), close=D(50), source="api")       # 5th was a holiday
        self.assertEqual(sip.create_due_entries(today=d(2026, 11, 9)), 1)                              # October waits for its NAV
        t = Transaction.objects.get()
        self.assertEqual((t.status, t.date, t.allotment_date, t.units), ("pending_sip", d(2026, 9, 5), d(2026, 9, 7), D("100.0000")))
        self.assertEqual(holdings.compute(self.profile, as_of=d(2026, 11, 9))[1].invested, 0)          # pending does not count
        tx.confirm_pending(self.profile, self.user, t.pk)
        self.assertEqual(holdings.compute(self.profile, as_of=d(2026, 11, 9))[0][0].units, D(100))
        Price.objects.create(instrument=self.fund, date=d(2026, 10, 5), close=D(40), source="api")
        self.assertEqual(sip.create_due_entries(today=d(2026, 11, 9)), 1)
        s.refresh_from_db()
        self.assertEqual(s.last_done, d(2026, 10, 5))

    def test_final_mode(self):
        masters.update_settings(self.profile, self.user, sip_mode="final")
        sip.add(self.profile, self.user, instrument=self.fund, amount=D(1000), day_of_month=31, portfolio=self.portfolio, broker=self.zerodha, start_date=d(2026, 2, 1))
        Price.objects.create(instrument=self.fund, date=d(2026, 2, 28), close=D(10), source="api")
        sip.create_due_entries(today=d(2026, 3, 1))
        self.assertEqual(Transaction.objects.get().status, "final")
        self.assertEqual(Transaction.objects.get().date, d(2026, 2, 28))

    def test_command_runs(self):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command("create_sip_entries", stdout=out)
        self.assertIn("created", out.getvalue())


class ImportTests(InvTestCase):
    HEADER = "Trade Date,Scrip,Type,Quantity,Price,Brokerage,Folio\n"

    def test_review_matches_and_marks_problems(self):
        masters.update_shared_details(self.profile, self.user, self.reliance, isin="INE002A01018")
        path = csv_file(self.HEADER + "02/01/2024,INE002A01018,Buy,10,2500,20,\n05/01/2024,RELIANCE,SELL,4,2600,10,\n06/01/2024,UNKNOWN CO,Buy,1,1,0,\n")
        r = statement_import.review(self.profile, path)
        self.assertEqual([l.side for l in r.lines], ["buy", "sell", "buy"])
        self.assertEqual(r.lines[0].instrument, self.reliance)
        self.assertEqual(r.lines[1].instrument, self.reliance)            # RELIANCE matches RELIANCE.NS
        self.assertIn("not in the program yet", r.lines[2].problem)
        self.assertEqual([m["text"] for m in r.missing], ["UNKNOWN CO"])
        with self.assertRaises(InvestmentsError):
            statement_import.apply(self.profile, self.user, path, portfolio=self.portfolio, broker=self.zerodha)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_apply_saves_in_date_order_skips_duplicates_and_completes_awaiting(self):
        a = tx.add_transaction(self.profile, self.user, side="buy", instrument=self.fund, portfolio=self.portfolio, broker=self.zerodha, date=d(2024, 11, 4),
                               awaiting=True, amount=D(50000))
        self.buy(d(2024, 1, 2), 10, 2500)
        path = csv_file("Date,Scheme Code,Type,Units,NAV,Folio\n05/11/2024,122639,Purchase,1000,50,F-1\n02/01/2024,RELIANCE.NS,Buy,10,2500,\n03/01/2024,RELIANCE.NS,Sell,5,2600,\n")
        r = statement_import.review(self.profile, path)
        self.assertEqual(r.lines[0].completes, a)
        self.assertTrue(r.lines[1].duplicate)
        made, completed, skipped = statement_import.apply(self.profile, self.user, path, portfolio=self.portfolio, broker=self.zerodha)
        self.assertEqual((made, completed, skipped), (1, 1, 1))
        a.refresh_from_db()
        self.assertEqual((a.status, a.units, a.folio_id is None), ("final", D(1000), True))

    def test_a_sale_beyond_holdings_stops_the_whole_file(self):
        path = csv_file(self.HEADER + "02/01/2024,RELIANCE.NS,Buy,1,2500,0,\n03/01/2024,RELIANCE.NS,Sell,5,2600,0,\n")
        with self.assertRaises(InvestmentsError):
            statement_import.apply(self.profile, self.user, path, portfolio=self.portfolio, broker=self.zerodha)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_page_review_then_save(self):
        self.client.force_login(self.user)
        body = (self.HEADER + "02/01/2024,RELIANCE.NS,Buy,10,2500,20,\n").encode()
        r = self.client.post(reverse("investments_import_statement"), {"file": SimpleUploadedFile("s.csv", body), "portfolio": self.portfolio.pk, "broker": self.zerodha.pk})
        self.assertContains(r, "New entry")
        self.assertEqual(Transaction.objects.count(), 0)
        r = self.client.post(reverse("investments_import_statement"), {"apply": "1", "token": r.context["token"], "portfolio": self.portfolio.pk, "broker": self.zerodha.pk})
        self.assertRedirects(r, reverse("investments_transactions"))
        self.assertEqual(Transaction.objects.get().charges, D(20))


    def test_missing_investments_are_proposed_from_the_file_and_the_amfi_list(self):
        from investments.models import AmfiScheme

        AmfiScheme.objects.create(code="120503", name="Axis ELSS Tax Saver Fund - Direct Plan - Growth", isin="INF846K01EW2")
        path = csv_file("Date,ISIN,Security Name,Type,Quantity,Price\n02/01/2024,INF846K01EW2,Axis ELSS,Buy,10,80\n"
                        "03/01/2024,INE467B01029,Tata Consultancy Services,Buy,2,3500\n04/01/2024,INE467B01029,Tata Consultancy Services,Buy,1,3600\n")
        r = statement_import.review(self.profile, path)
        fund, share = r.missing          # one proposal per investment, however many lines it has
        self.assertEqual((fund["kind"], fund["code"], fund["name"]), ("fund", "120503", "Axis ELSS Tax Saver Fund - Direct Plan - Growth"))
        self.assertEqual((share["kind"], share["code"], share["name"], share["isin"]), ("share", "", "Tata Consultancy Services", "INE467B01029"))
        self.assertEqual(statement_import.propose("HDFCBANK")["code"], "HDFCBANK.NS")
        self.assertEqual(statement_import.propose("500180.BO")["code"], "500180.BO")

    def test_adding_the_missing_investments_then_saving(self):
        self.client.force_login(self.user)
        url = reverse("investments_import_statement")
        body = b"Date,Symbol,Name,Type,Quantity,Price\n02/01/2024,TCS,Tata Consultancy,Buy,2,3500\n03/01/2024,RELIANCE.NS,Reliance,Buy,1,2500\n"
        r = self.client.post(url, {"file": SimpleUploadedFile("s.csv", body), "portfolio": self.portfolio.pk, "broker": self.zerodha.pk})
        self.assertContains(r, "Not in the program yet")
        self.assertNotContains(r, ">Save ")                   # cannot save while an investment is missing
        token = r.context["token"]
        base = {"token": token, "portfolio": self.portfolio.pk, "broker": self.zerodha.pk}
        r = self.client.post(url, dict(base, create="1", missing_count="1", add_0="1", text_0="TCS", kind_0="share", name_0="Tata Consultancy Services",
                                       code_0="TCS.NS", isin_0="", currency_0="INR"))
        tcs = Instrument.objects.get(code="TCS.NS")
        self.assertEqual((tcs.name, tcs.profile_id, tcs.price_source), ("Tata Consultancy Services", None, "yahoo"))
        self.assertEqual(r.context["review"].lines[0].instrument, tcs)   # matched through the alias although the name was corrected
        self.assertFalse(r.context["review"].missing)
        self.assertContains(r, "Save 2 lines")
        r = self.client.post(url, dict(base, apply="1"))
        self.assertRedirects(r, reverse("investments_transactions"))
        self.assertEqual(Transaction.objects.filter(instrument=tcs).count(), 1)

    def test_a_missing_investment_needs_a_code_and_an_existing_one_is_reused(self):
        with self.assertRaises(InvestmentsError):
            statement_import.create_missing(self.profile, self.user, [{"text": "X", "kind": "share", "name": "X Ltd", "code": ""}])
        aliases = statement_import.create_missing(self.profile, self.user, [{"text": "Reliance Inds", "kind": "share", "name": "Reliance Inds", "code": "RELIANCE.NS"}])
        self.assertEqual(aliases, {"Reliance Inds": self.reliance.pk})
        self.assertEqual(Instrument.objects.filter(code="RELIANCE.NS").count(), 1)

    def test_import_is_linked_from_holdings_and_transactions(self):
        self.client.force_login(self.user)
        link = 'href="%s"' % reverse("investments_import_statement")
        for name in ("investments_holdings", "investments_transactions"):
            self.assertContains(self.client.get(reverse(name)), link)

class SearchTests(InvTestCase):
    def test_kinds_and_rules(self):
        self.buy(d(2024, 1, 2), 10, 2500, reference="ORD-77")
        masters.add_folio(self.profile, self.user, instrument=self.fund, portfolio=self.portfolio, number="12_34%")
        kinds = {r["kind"] for r in search.search(self.profile, "rel")}
        self.assertEqual(kinds, {"Investments", "Transactions"})
        self.assertEqual(search.search(self.profile, "r"), [])
        self.assertEqual([r["title"] for r in search.search(self.profile, "_34%")], ["12_34%"])         # wildcards match literally
        self.assertEqual(search.search(self.profile, "ord-77")[0]["kind"], "Transactions")
        self.assertIn("Brokers", {r["kind"] for r in search.search(self.profile, "zero")})
        self.assertIn("Pages", {r["kind"] for r in search.search(self.profile, "annual")})
        self.assertNotIn("Pages", {r["kind"] for r in search.search(self.profile, "annual", hidden={"annual"})})

    def test_page(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse("investments_search") + "?q=parag")
        self.assertContains(r, "Parag Parikh")
        self.assertEqual(self.client.get(reverse("investments_search") + "?q=parag&format=json").json()["results"][0]["kind"], "Investments")


class ReportsAndInsightsTests(InvTestCase):
    def setUp(self):
        super().setUp()
        nifty = __import__("investments.models", fromlist=["Instrument"]).Instrument.objects.get(code="^NSEI")
        day = d.today() - timedelta(days=800)
        while day <= d.today():
            n = (day - (d.today() - timedelta(days=800))).days
            Price.objects.create(instrument=nifty, date=day, close=D(10000) + n, source="api")
            Price.objects.create(instrument=self.reliance, date=day, close=D(100) - D(n) / 20, source="api")
            day += timedelta(days=7)
        self.buy(d.today() - timedelta(days=700), 10, 100)
        self.buy(d.today() - timedelta(days=340), 5, 80)

    def test_every_report_builds_and_renders_and_exports(self):
        self.client.force_login(self.user)
        for slug in REPORTS:
            with self.subTest(slug=slug):
                r = self.client.get(reverse("investments_report", args=[slug]))
                self.assertEqual(r.status_code, 200)
        self.assertContains(self.client.get(reverse("investments_reports")), "Index scoreboard")

    def test_turning_long_and_unrealised(self):
        soon = reports.turning_long(self.profile, days=60)
        self.assertEqual(len(soon.rows), 1)
        self.assertEqual(soon.rows[0][5], 26)
        un = reports.unrealised_lots(self.profile)
        self.assertEqual({r[6] for r in un.rows}, {"Short-term", "Long-term"})

    def test_insights_rules_and_dismiss(self):
        found = {i["kind"]: i for i in insights.compute(self.profile)}
        self.assertIn("vs_index", found)
        self.assertIn("below_cost", found)
        self.assertIn("turning_long", found)
        self.assertIn("concentration", found)
        insights.dismiss(self.profile, found["below_cost"]["key"])
        self.assertNotIn("below_cost", {i["kind"] for i in insights.compute(self.profile)})
        masters.update_settings(self.profile, self.user, insights_off=["vs_index"])
        self.assertNotIn("vs_index", {i["kind"] for i in insights.compute(self.profile)})
        self.assertTrue(all("buy" not in i["text"].lower().split() and "sell" not in i["text"].lower().split() for i in insights.compute(self.profile)))

    def test_compare_brokers_counts_a_transfer_at_market_value(self):
        tx.add_transfer(self.profile, self.user, instrument=self.reliance, date=d.today() - timedelta(days=100), units=D(5), from_portfolio=self.portfolio,
                        from_broker=self.zerodha, to_portfolio=self.portfolio, to_broker=self.groww)
        rows, totals = holdings.compute(self.profile, broker=self.groww.pk)
        (h,) = rows
        self.assertEqual(h.units, D(5))
        self.assertEqual(len(h.flows), 1)
        self.assertLess(h.flows[0][1], 0)                        # money arriving at Groww, at the market value then
        rows_z, _ = holdings.compute(self.profile, broker=self.zerodha.pk)
        self.assertTrue(any(a > 0 for _d, a in rows_z[0].flows))
        t = reports.compare_brokers(self.profile, years=3)
        self.assertEqual([r[0] for r in t.rows], ["Groww", "Zerodha", "All holdings"])          # brokers in name order
        self.assertTrue(Transfer.objects.exists())


class AlternativeInterestTests(InvTestCase):
    def test_fixed_interest_rate_grows_each_lot(self):
        fdep = masters.create_instrument(self.profile, self.user, kind="alternative", name="FD 7%", interest_rate=D(7), asset_class="debt")
        tx.add_transaction(self.profile, self.user, side="buy", instrument=fdep, portfolio=self.portfolio, broker=self.zerodha, date=d(2024, 1, 1), units=D(1),
                           price=D(100000))
        (h,), _ = holdings.compute(self.profile, as_of=d(2024, 12, 31))
        self.assertAlmostEqual(float(h.value), 100000 * 1.07 ** (365 / 365), places=0)


class SettingsPagesTests(InvTestCase):
    def test_display_and_insights_pages(self):
        self.client.force_login(self.user)
        r = self.client.post(reverse("investments_settings_display"), {"my_money": "full", "money_default": "auto", "default_exchange": "BO", "compact_tables": "on"})
        self.assertEqual(r.status_code, 302)
        self.assertContains(self.client.get(reverse("investments_dashboard")), "compact")
        r = self.client.post(reverse("investments_settings_insights"), {"on": ["stale"], "limit": "25"})
        self.assertEqual(r.status_code, 302)
        row = masters.core.get_settings(self.profile)
        self.assertEqual((row.concentration_limit, "vs_index" in row.insights_off), (D(25), True))
        self.assertEqual(Portfolio.objects.count() + Broker.objects.count() >= 3, True)
        self.assertFalse(SipSchedule.objects.exists())


class AddInvestmentSearchTests(InvTestCase):
    def test_fund_plan_search_and_pick_and_confirm_check(self):
        from investments.models import AmfiScheme
        from investments.services import schemes
        from investments.tests.fakehttp import FakeNet, fixture
        from unittest import mock
        from investments.adapters import http as h
        net = FakeNet()
        net.add("NAVAll", fixture("amfi_navall.txt"))
        with mock.patch.object(h, "_urlopen", net):
            self.assertEqual(schemes.refresh(force=True), 5)
        self.assertEqual(schemes.refresh(), 0)                     # not due again for a week
        self.client.force_login(self.user)
        r = self.client.get(reverse("investments_add_2") + "?kind=fund&q=parag direct")
        self.assertContains(r, "Parag Parikh Flexi Cap Fund - Direct Plan - Growth")
        self.assertNotContains(r, "Regular Plan")
        r = self.client.post(reverse("investments_add_2"), {"kind": "fund", "name": "PPFAS Flexi Direct", "code": "122640", "currency": "INR", "asset_class": "equity"})
        self.assertContains(r, "Latest price check")
        self.assertTrue(AmfiScheme.objects.filter(code="122640").exists())

    def test_share_search_failure_lets_the_code_be_typed(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse("investments_add_2") + "?kind=share&q=infosys")
        self.assertContains(r, "Type the code instead")
        r = self.client.post(reverse("investments_add_2"), {"kind": "share", "name": "Infosys", "code": "INFY.NS", "currency": "INR", "asset_class": "equity"})
        self.assertContains(r, "No price data, check the code")
