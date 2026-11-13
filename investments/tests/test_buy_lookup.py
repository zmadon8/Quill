"""Buy and Opening balance: the Investment box searches the profile's investments and the stored NSE / AMFI lists; a share or fund picked from
the lists becomes an Instrument only when the Buy is saved."""
from datetime import date as d
from decimal import Decimal as D

from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.models import ROLE_READER
from investments.models import AmfiScheme, Instrument, NseSecurity, Price, Transaction
from investments.services import instrument_search
from investments.tests.base import InvTestCase, make_user


class LookupBase(InvTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.client.force_login(self.user)
        # The stored lists are seeded directly, so no test reaches the network.
        NseSecurity.objects.create(symbol="TATASTEEL", name="Tata Steel Limited", isin="INE081A01020", series="EQ")
        NseSecurity.objects.create(symbol="RELIANCE", name="Reliance Industries Limited", isin="INE002A01018", series="EQ")
        AmfiScheme.objects.create(code="119551", name="Axis Bluechip Fund - Direct Plan - Growth", isin="INF846K01DP8",
                                  plan="Direct", option="Growth", nav=D("55.1000"), nav_date=d(2026, 11, 6))
        self.url = reverse("investments_txn_lookup")

    def get(self, **params):
        return self.client.get(self.url, params).json()

    def card(self, prefix, day, units, price, **extra):
        p = prefix + "-" if prefix else ""
        return {p + "date": day, p + "portfolio": self.portfolio.pk, p + "broker": self.zerodha.pk, p + "units": units,
                p + "price": price, p + "charges": "0", **{p + k: v for k, v in extra.items()}}


class LookupEndpointTests(LookupBase):
    def test_held_on_lists_only_held_investments_with_units(self):
        self.buy(d(2024, 1, 1), 120, 100)
        out = self.get(q="", held="1")
        self.assertEqual([r["code"] for r in out["in_quill"]], ["RELIANCE.NS"])
        self.assertEqual(out["in_quill"][0]["units"], "120")
        self.assertEqual(out["nse_amfi"], [])

    def test_held_on_filters_by_the_text_typed(self):
        self.buy(d(2024, 1, 1), 10, 100)
        self.buy(d(2024, 1, 1), 5, 50, instrument=self.fund)
        self.assertEqual([r["code"] for r in self.get(q="parag", held="1")["in_quill"]], ["122639"])
        self.assertEqual(self.get(q="zzz", held="1")["in_quill"], [])

    def test_held_on_leaves_out_sold_out_and_never_bought(self):
        self.buy(d(2024, 1, 1), 10, 100)
        self.sell(d(2024, 2, 1), 10, 110)
        self.assertEqual(self.get(held="1")["in_quill"], [])

    def test_held_off_needs_two_characters(self):
        out = self.get(q="t", held="0")
        self.assertEqual((out["in_quill"], out["nse_amfi"]), ([], []))

    def test_held_off_groups_in_quill_and_nse_amfi_and_drops_duplicates(self):
        self.buy(d(2024, 1, 1), 10, 100)
        self.buy(d(2024, 1, 1), 10, 100, instrument=self.fund)
        self.sell(d(2024, 2, 1), 10, 110, instrument=self.fund)
        out = self.get(q="reliance", held="0")
        self.assertEqual([(r["code"], r["tag"]) for r in out["in_quill"]], [("RELIANCE.NS", "")])
        self.assertEqual(out["nse_amfi"], [])      # already in Quill, so only under In Quill
        out = self.get(q="parag", held="0")
        self.assertEqual([(r["code"], r["tag"]) for r in out["in_quill"]], [("122639", "sold")])
        out = self.get(q="tata", held="0")
        self.assertEqual(out["in_quill"], [])
        self.assertEqual([(r["source"], r["code"], r["isin"]) for r in out["nse_amfi"]], [("nse", "TATASTEEL.NS", "INE081A01020")])
        self.assertEqual(self.get(q="axis", held="0")["nse_amfi"][0]["code"], "119551")
        self.assertIn("55.10", self.get(q="axis", held="0")["nse_amfi"][0]["price_text"])
        self.assertTrue(out["add_url"].endswith(reverse("investments_add_1")))

    def test_not_held_tag_and_last_price_text(self):
        Price.objects.create(instrument=self.reliance, date=d(2024, 11, 12), close=D("148.20"))
        out = self.get(q="reliance", held="0")
        self.assertEqual(out["in_quill"][0]["tag"], "not held")
        self.assertEqual(out["in_quill"][0]["price_text"], "Last price \u20b9148.20 on 12 Nov")

    def test_lookup_switched_off_searches_only_in_quill(self):
        instrument_search.set_lookup_enabled(False)
        out = self.get(q="reliance", held="0")
        self.assertEqual([r["code"] for r in out["in_quill"]], ["RELIANCE.NS"])
        self.assertEqual(self.get(q="tata", held="0")["nse_amfi"], [])
        self.assertFalse(out["lookup"])

    def test_readers_and_anonymous_are_refused(self):
        reader, _ = make_user("reader1", role=ROLE_READER, profile=self.profile)
        self.client.logout()
        self.assertNotEqual(self.client.get(self.url, {"q": "tata", "held": "0"}).status_code, 200)
        self.client.force_login(reader)
        self.assertNotEqual(self.client.get(self.url, {"q": "tata", "held": "0"}).status_code, 200)


class BuyPickTests(LookupBase):
    buy_url = property(lambda self: reverse("investments_txn_new_buy"))

    def test_new_nse_pick_creates_one_correct_instrument_at_save(self):
        r = self.client.post(self.buy_url, self.card("", "2024-01-01", "10", "100", new_source="nse", new_code="TATASTEEL.NS"))
        self.assertRedirects(r, reverse("investments_transactions"))
        inst = Instrument.objects.get(code="TATASTEEL.NS")
        self.assertEqual((inst.kind, inst.name, inst.isin, inst.price_source), ("share", "Tata Steel Limited", "INE081A01020", "yahoo"))
        self.assertEqual(Transaction.objects.get().instrument_id, inst.pk)

    def test_new_amfi_pick_creates_a_fund_with_the_standard_name(self):
        self.client.post(self.buy_url, self.card("", "2024-01-01", "10", "55", new_source="amfi", new_code="119551"))
        inst = Instrument.objects.get(code="119551")
        self.assertEqual((inst.kind, inst.isin, inst.price_source), ("fund", "INF846K01DP8", "amfi"))
        self.assertEqual(inst.name, AmfiScheme.objects.get(code="119551").display_name)
        self.assertEqual(Transaction.objects.count(), 1)

    def test_posted_name_and_isin_are_never_trusted(self):
        self.client.post(self.buy_url, self.card("", "2024-01-01", "10", "100", new_source="nse", new_code="TATASTEEL.NS",
                                                 new_name="Evil", new_isin="XX"))
        self.assertEqual(Instrument.objects.get(code="TATASTEEL.NS").name, "Tata Steel Limited")

    def test_two_cards_with_the_same_new_pick_make_one_instrument(self):
        post = {**self.card("", "2024-01-01", "10", "100", new_source="nse", new_code="TATASTEEL.NS"), "extra_rows": "1",
                **self.card("x1", "2024-02-01", "5", "110", new_source="nse", new_code="TATASTEEL.NS")}
        self.assertRedirects(self.client.post(self.buy_url, post), reverse("investments_transactions"))
        self.assertEqual(Instrument.objects.filter(code="TATASTEEL.NS").count(), 1)
        self.assertEqual(Transaction.objects.count(), 2)

    def test_pick_of_something_already_in_quill_reuses_it(self):
        before = Instrument.objects.count()
        self.client.post(self.buy_url, self.card("", "2024-01-01", "10", "100", new_source="nse", new_code="RELIANCE.NS"))
        self.assertEqual(Instrument.objects.count(), before)
        self.assertEqual(Transaction.objects.get().instrument_id, self.reliance.pk)

    def test_pick_matched_by_isin_reuses_the_existing_fund(self):
        existing = Instrument.objects.create(name="Axis Bluechip", kind="fund", code="OLD1", isin="INF846K01DP8", price_source="amfi")
        before = Instrument.objects.count()
        self.client.post(self.buy_url, self.card("", "2024-01-01", "10", "55", new_source="amfi", new_code="119551"))
        self.assertEqual(Instrument.objects.count(), before)
        self.assertEqual(Transaction.objects.get().instrument_id, existing.pk)

    def test_tampered_or_unknown_code_is_a_form_error_and_creates_nothing(self):
        before = Instrument.objects.count()
        for source, code in (("nse", "NOPE.NS"), ("nse", "TATASTEEL"), ("amfi", "999999"), ("bse", "TATASTEEL.NS")):
            r = self.client.post(self.buy_url, self.card("", "2024-01-01", "10", "100", new_source=source, new_code=code))
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, "not in the NSE / AMFI list")
        self.assertEqual(Instrument.objects.count(), before)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_no_investment_and_no_pick_is_required_error(self):
        r = self.client.post(self.buy_url, self.card("", "2024-01-01", "10", "100"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "This field is required.")
        self.assertEqual(Transaction.objects.count(), 0)

    def test_invalid_card_creates_no_instrument(self):
        before = Instrument.objects.count()
        r = self.client.post(self.buy_url, self.card("", "2024-01-01", "", "100", new_source="nse", new_code="TATASTEEL.NS"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Instrument.objects.count(), before)

    def test_a_refused_card_rolls_back_the_new_instrument(self):
        before = Instrument.objects.count()
        post = {**self.card("", "2024-01-01", "10", "100", new_source="nse", new_code="TATASTEEL.NS"), "extra_rows": "1",
                **self.card("x1", "2024-02-01", "5", "50", instrument=self.reliance.pk)}
        post["x1-date"] = "2999-01-01"      # a date in the future is refused when saving
        self.client.post(self.buy_url, post)
        self.assertEqual(Instrument.objects.count(), before)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_lookup_switched_off_rejects_a_pick(self):
        instrument_search.set_lookup_enabled(False)
        r = self.client.post(self.buy_url, self.card("", "2024-01-01", "10", "100", new_source="nse", new_code="TATASTEEL.NS"))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Instrument.objects.filter(code="TATASTEEL.NS").exists())

    def test_choosing_an_existing_investment_still_works(self):
        post = self.card("", "2024-01-01", "10", "100", instrument=self.reliance.pk)
        self.assertRedirects(self.client.post(self.buy_url, post), reverse("investments_transactions"))

    def test_sell_page_has_no_pick_fields(self):
        html = self.client.get(reverse("investments_txn_new_sell")).content.decode()
        self.assertNotIn('name="new_code"', html)
        self.assertIn('name="new_code"', self.client.get(self.buy_url).content.decode())


class OpeningPickTests(LookupBase):
    def test_opening_balance_with_a_new_pick_creates_the_instrument(self):
        post = {"portfolio": self.portfolio.pk, "broker": self.zerodha.pk, "new_source": "nse", "new_code": "TATASTEEL.NS",
                "date_0": "2023-04-01", "units_0": "10", "cost_0": "90"}
        r = self.client.post(reverse("investments_txn_opening"), post)
        self.assertRedirects(r, reverse("investments_transactions"))
        inst = Instrument.objects.get(code="TATASTEEL.NS")
        self.assertEqual(Transaction.objects.get().instrument_id, inst.pk)

    def test_opening_balance_tampered_pick_creates_nothing(self):
        before = Instrument.objects.count()
        post = {"portfolio": self.portfolio.pk, "broker": self.zerodha.pk, "new_source": "nse", "new_code": "NOPE.NS",
                "date_0": "2023-04-01", "units_0": "10", "cost_0": "90"}
        self.assertEqual(self.client.post(reverse("investments_txn_opening"), post).status_code, 200)
        self.assertEqual(Instrument.objects.count(), before)
        self.assertEqual(Transaction.objects.count(), 0)


class AwaitingBuyPickTests(LookupBase):
    """The Investment box on "Add a purchase awaiting allotment" is the same combobox as on Buy."""

    url_awaiting = property(lambda self: reverse("investments_txn_new_awaiting"))

    def post_card(self, **extra):
        return {"date": "2024-11-04", "portfolio": self.portfolio.pk, "broker": self.zerodha.pk, "amount": "5000", "charges": "0", **extra}

    def test_the_form_has_the_combobox_and_the_pick_fields(self):
        html = self.client.get(self.url_awaiting).content.decode()
        self.assertIn("data-combo", html)
        self.assertIn('name="new_source"', html)
        self.assertIn('name="new_code"', html)
        self.assertIn(reverse("investments_txn_lookup"), html)

    def test_a_new_amfi_pick_is_made_at_save_and_the_entry_is_awaiting(self):
        r = self.client.post(self.url_awaiting, self.post_card(new_source="amfi", new_code="119551"))
        self.assertRedirects(r, reverse("investments_transactions"))
        txn = Transaction.objects.get()
        self.assertEqual(txn.instrument.code, "119551")
        self.assertEqual(txn.status, "awaiting")

    def test_a_tampered_pick_makes_nothing(self):
        before = Instrument.objects.count()
        r = self.client.post(self.url_awaiting, self.post_card(new_source="amfi", new_code="000000"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual((Instrument.objects.count(), Transaction.objects.count()), (before, 0))

    def test_the_lookup_serves_the_awaiting_form_too(self):
        out = self.get(q="axis", held="0")
        self.assertEqual([r["code"] for r in out["nse_amfi"]], ["119551"])


class PickNameAfterErrorTests(LookupBase):
    def test_the_combobox_gets_the_stored_name_when_the_page_is_shown_again(self):
        # Units left out: a validation error, so the form is shown again with the pick still in it.
        post = {"date": "2024-01-01", "portfolio": self.portfolio.pk, "broker": self.zerodha.pk, "price": "100", "new_source": "nse", "new_code": "TATASTEEL.NS"}
        r = self.client.post(reverse("investments_txn_new_buy"), post)
        self.assertEqual(r.status_code, 200)
        self.assertIn('data-pick-name="Tata Steel Limited"', r.content.decode())
        self.assertEqual(Instrument.objects.filter(code="TATASTEEL.NS").count(), 0)

    def test_an_unknown_code_gives_no_name(self):
        post = {"date": "2024-01-01", "portfolio": self.portfolio.pk, "broker": self.zerodha.pk, "price": "100", "new_source": "nse", "new_code": "NOPE.NS"}
        self.assertIn('data-pick-name=""', self.client.post(reverse("investments_txn_new_buy"), post).content.decode())


class FundAssetClassTests(LookupBase):
    def pick(self, code, category, name):
        AmfiScheme.objects.create(code=code, name=name, isin="INF" + code, plan="Direct", option="Growth", category=category)
        self.client.post(reverse("investments_txn_new_buy"), self.card("", "2024-01-01", "10", "10", new_source="amfi", new_code=code))
        return Instrument.objects.get(code=code).asset_class

    def test_new_funds_get_their_asset_class_from_the_category(self):
        self.assertEqual(self.pick("900001", "Open Ended Schemes(Debt Scheme - Liquid Fund)", "Acme Liquid Fund - Direct Plan - Growth"), "debt")
        self.assertEqual(self.pick("900002", "Open Ended Schemes(Other Scheme - Gold ETF)", "Acme Gold ETF"), "gold")
        self.assertEqual(self.pick("900003", "Open Ended Schemes(Hybrid Scheme - Arbitrage Fund)", "Acme Arbitrage Fund - Direct Plan - Growth"), "other")
        self.assertEqual(self.pick("900004", "Open Ended Schemes ( Equity Scheme - Large Cap Fund )", "Acme Large Cap Fund - Direct Plan - Growth"), "equity")

    def test_without_a_category_the_name_decides(self):
        self.assertEqual(self.pick("900005", "", "Acme Overnight Fund - Direct Plan - Growth"), "debt")
        self.assertEqual(self.pick("900006", "", "Acme Small Cap Fund - Direct Plan - Growth"), "equity")

    def test_an_index_fund_category_defers_to_the_name(self):
        self.assertEqual(self.pick("900007", "Open Ended Schemes(Other Scheme - Index Funds)", "Acme Gold Index Fund - Direct Plan - Growth"), "gold")
        self.assertEqual(self.pick("900008", "Open Ended Schemes(Other Scheme - Index Funds)", "Acme Nifty 50 Index Fund - Direct Plan - Growth"), "equity")

    def test_the_add_page_agrees(self):
        AmfiScheme.objects.create(code="900009", name="Acme Liquid Fund - Direct Plan - Growth", category="Open Ended Schemes(Debt Scheme - Liquid Fund)")
        html = self.client.get(reverse("investments_add_2"), {"kind": "fund", "pick_code": "900009"}).content.decode()
        self.assertRegex(html, r'<option value="debt" selected>')
        self.assertTrue(self.client.get(reverse("investments_add_scheme"), {"code": "900009"}).json()["asset_class"] == "debt")


class LookupSpeedTests(LookupBase):
    def test_a_repeated_held_lookup_does_not_read_the_transactions_and_follows_a_new_buy(self):
        self.buy(d(2024, 1, 1), 120, 100)
        first = self.get(q="", held="1")
        self.assertEqual(first["in_quill"][0]["units"], "120")
        with CaptureQueriesContext(connection) as ctx:
            again = self.get(q="rel", held="1")
        self.assertEqual(again["in_quill"][0]["units"], "120")
        self.assertFalse([q for q in ctx.captured_queries if "investments_transaction" in q["sql"]])
        self.buy(d(2024, 2, 1), 5, 100)      # a saved transaction bumps the data version
        self.assertEqual(self.get(q="", held="1")["in_quill"][0]["units"], "125")

    def test_cached_units_come_back_as_ints_and_decimals(self):
        from investments.services import holdings

        self.buy(d(2024, 1, 1), D("12.5"), 100)
        for _ in range(2):
            self.assertEqual(holdings.held_units(self.profile), {self.reliance.pk: D("12.5")})


class LookupFailureTests(LookupBase):
    def test_a_failing_search_is_logged_and_shown_as_unavailable(self):
        from unittest import mock

        with mock.patch.object(instrument_search, "search", side_effect=RuntimeError("boom")), self.assertLogs("investments.views_txn", "ERROR"):
            out = self.get(q="tata", held="0")
        self.assertEqual(out["nse_amfi"], [])
        self.assertIn("not available", out["message"])
