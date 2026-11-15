"""A Lump Sum bought for 100 on day 1 and, on day 100, sold for 200 with 50 remaining, entered through the real pages.

Before the sale the holding was worth 250 (the 200 sold and the 50 left) and right after it 50. So its Manual Price History must show day 1 as
100 ("From purchase") and the sale date as 50 with "Before sale: 250.00", and its chart must hold 100 until the day before the sale, then 250 at
the before point on the sale date and 50 after it. The header Value is 50."""
import json
from decimal import Decimal as D

from django.urls import reverse

from investments.models import AltValue, Instrument, Transaction
from investments.services import chartview, masters
from investments.tests.base import InvTestCase, d

BUY_DAY = d(2024, 1, 1)
SALE_DAY = d(2024, 4, 9)        # day 1 plus 99 days, so day 100
END = d(2024, 12, 31)
SALE_LABEL = "9 Apr 2024"


class LumpSaleExampleBase(InvTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        r = self.client.post(reverse("investments_add_2"), {"kind": "alternative", "name": "Chit fund", "asset_class": "debt", "lump_sum": "on",
                                                            "interest_type": "compound", "confirmed": "1"})
        self.assertEqual(r.status_code, 302)
        self.chit = Instrument.objects.get(name="Chit fund")
        self.assertTrue(self.chit.lump_sum)

    def card(self, day, **extra):
        return {"date": day.isoformat(), "instrument": self.chit.pk, "portfolio": self.portfolio.pk, "broker": self.zerodha.pk, "charges": "0", **extra}

    def buy_100_and_sell_200_leaving_50(self):
        r = self.client.post(reverse("investments_txn_new_buy"), self.card(BUY_DAY, lump_amount="100"))
        self.assertRedirects(r, reverse("investments_transactions"))
        r = self.client.post(reverse("investments_txn_new_sell"), self.card(SALE_DAY, lump_amount="200", remaining="50"))
        self.assertRedirects(r, reverse("investments_transactions"))

    def page(self):
        return self.client.get(reverse("investments_investment", args=[self.chit.pk]))

    def history(self):
        """``[(date, total value, note, value before)]`` as the Manual Price History table is given them, oldest first."""
        rows = self.page().context["alt_values"]
        return sorted((r.date, r.total_value, r.note, r.value_before) for r in rows)

    def chart_points(self):
        """``[(label, value)]`` of every point of the chart's value line, in drawing order."""
        chart = chartview.value_chart(self.profile, None, END, portfolio=None, broker=None, instrument_ids=[self.chit.pk], entries_of=self.chit)
        data = json.loads(chart["hover"])
        return list(zip(data["d"], data["s"][0]["v"]))

    def assert_chart_steps_at_the_sale(self):
        points = self.chart_points()
        at = [i for i, (label, _v) in enumerate(points) if label == SALE_LABEL]
        self.assertEqual([points[i][1] for i in at], ["250.00", "50.00"])           # the drop is drawn at the sale date
        before = points[:at[0]]
        self.assertTrue(before)
        self.assertEqual({v for _label, v in before}, {"100.00"}, before)           # flat at 100 up to the day before, with no slope towards 250
        self.assertIn(("8 Apr 2024", "100.00"), before)                             # the day before the sale still holds 100
        after = points[at[-1] + 1:]
        self.assertTrue(after)
        self.assertEqual({v for _label, v in after}, {"50.00"}, after)

    def assert_header_value_is_50(self):
        self.assertEqual(self.page().context["h"].value, D("50"))


class LumpSaleExampleTests(LumpSaleExampleBase):
    def test_the_manual_price_history_shows_100_on_day_one_and_50_with_before_sale_250(self):
        self.buy_100_and_sell_200_leaving_50()
        self.assertEqual(self.history(), [(BUY_DAY, D("100.00"), "From purchase", None), (SALE_DAY, D("50.00"), "From sale", D("250.00"))])

    def test_the_page_prints_the_before_sale_figure(self):
        self.buy_100_and_sell_200_leaving_50()
        page = self.page()
        self.assertContains(page, "Before sale: ")
        self.assertContains(page, "250.00")

    def test_the_chart_holds_100_then_250_before_the_sale_and_50_after(self):
        self.buy_100_and_sell_200_leaving_50()
        self.assert_chart_steps_at_the_sale()

    def test_the_header_value_is_50(self):
        self.buy_100_and_sell_200_leaving_50()
        self.assert_header_value_is_50()

    def test_with_averaged_values_the_line_slopes_to_the_value_before_the_sale_then_drops(self):
        # "Averaged out" is the person's own choice: the value is worked out between entries, so from the 100 of day 1 to the 250 that stands for
        # the day before the sale (a sale's value before counts as that day's value), where the drop to 50 follows.
        masters.update_settings(self.profile, self.user, alt_treatment="averaged")
        self.buy_100_and_sell_200_leaving_50()
        points = self.chart_points()
        self.assertEqual(points[0], ("1 Jan 2024", "100.00"))
        self.assertIn(("8 Apr 2024", "250.00"), points)
        at = [v for label, v in points if label == SALE_LABEL]
        self.assertEqual(at, ["250.00", "50.00"])
        slope = [D(v) for label, v in points[:points.index(("8 Apr 2024", "250.00"))]]
        self.assertEqual(slope, sorted(slope))
        self.assertGreater(slope[-1], D("100"))
        self.assert_header_value_is_50()

    def test_the_chart_is_cached_per_treatment(self):
        self.buy_100_and_sell_200_leaving_50()
        flat = self.chart_points()
        masters.update_settings(self.profile, self.user, alt_treatment="averaged")
        self.assertNotEqual(self.chart_points(), flat)


class LumpSaleOldDataTests(LumpSaleExampleBase):
    """Entries saved before the value just before a sale was stored (and before a first purchase wrote a value): the sale date holds 50 "From
    sale" with no ``value_before`` and nothing else. The sale's own figures (200 sold, 50 remaining) are still in its transaction."""

    def make_old_state(self):
        self.buy_100_and_sell_200_leaving_50()
        AltValue.objects.filter(profile=self.profile, instrument=self.chit).exclude(date=SALE_DAY).delete()
        AltValue.objects.filter(profile=self.profile, instrument=self.chit, date=SALE_DAY).update(value_before=None)
        self.assertEqual(list(AltValue.objects.filter(profile=self.profile, instrument=self.chit).values_list("date", "total_value", "value_before")),
                         [(SALE_DAY, D("50.00"), None)])

    def test_an_old_sale_still_shows_before_sale_250_in_the_history(self):
        self.make_old_state()
        row = next(r for r in self.page().context["alt_values"] if r.date == SALE_DAY)
        self.assertEqual((row.total_value, row.note, row.value_before, row.calc_before), (D("50.00"), "From sale", None, D("250.00")))
        self.assertContains(self.page(), "Before sale (calculated): ")

    def test_an_old_sale_still_draws_100_then_250_then_50(self):
        self.make_old_state()
        self.assert_chart_steps_at_the_sale()
        self.assert_header_value_is_50()


class LumpSaleDerivedBeforeTests(LumpSaleExampleBase):
    """The value before a sale worked out from the sale's own transactions (older sales have none stored)."""

    def clear_stored_before(self):
        AltValue.objects.filter(profile=self.profile, instrument=self.chit).update(value_before=None)

    def derived(self):
        from investments.services import sale_steps
        return sale_steps.steps(self.profile, self.chit)

    def test_a_derived_step_matches_the_stored_one(self):
        self.buy_100_and_sell_200_leaving_50()
        stored = self.derived()
        self.clear_stored_before()
        self.assertEqual(self.derived(), stored)
        self.assertEqual(stored, [{"date": SALE_DAY, "before": D("250.00"), "after": D("50.00"), "sold": D("200.00")}])

    def test_the_price_rounding_is_taken_out_so_the_figure_is_what_was_typed(self):
        # 1,000,000 held, 100,000 sold and 33,000 left: the unit price 0.13300... is rounded up to 0.1331, so the transaction carries a price
        # rounding of 75.19 in its note, and units times price is 100,075.19, not the 100,000 that was typed.
        self.client.post(reverse("investments_txn_new_buy"), self.card(BUY_DAY, lump_amount="1000000"))
        self.client.post(reverse("investments_txn_new_sell"), self.card(SALE_DAY, lump_amount="100000", remaining="33000"))
        self.assertIn("Price rounding 75.19 added to charges.", Transaction.objects.get(side="sell").note)
        stored = AltValue.objects.get(profile=self.profile, instrument=self.chit, date=SALE_DAY).value_before
        self.assertEqual(stored, D("133000.00"))
        self.clear_stored_before()
        self.assertEqual(self.derived()[0]["before"], D("133000.00"))

    def test_a_date_with_a_purchase_has_no_derived_step(self):
        self.buy_100_and_sell_200_leaving_50()
        self.client.post(reverse("investments_txn_new_buy"), self.card(SALE_DAY, lump_amount="10"))
        self.clear_stored_before()
        self.assertEqual(self.derived(), [])

    def test_selling_everything_derives_the_amount_sold(self):
        self.client.post(reverse("investments_txn_new_buy"), self.card(BUY_DAY, lump_amount="100"))
        self.client.post(reverse("investments_txn_new_sell"), self.card(SALE_DAY, lump_amount="250", remaining="0"))
        self.clear_stored_before()
        self.assertEqual(self.derived(), [{"date": SALE_DAY, "before": D("250.00"), "after": D("0.00"), "sold": D("250.00")}])

    def test_two_sales_on_one_date_add_up(self):
        self.buy_100_and_sell_200_leaving_50()
        self.client.post(reverse("investments_txn_new_sell"), self.card(SALE_DAY, lump_amount="20", remaining="30"))
        self.clear_stored_before()
        step = self.derived()[0]
        self.assertEqual((step["before"], step["after"]), (D("250.00"), D("30.00")))

    def test_the_history_marks_a_derived_figure_as_calculated(self):
        self.buy_100_and_sell_200_leaving_50()
        self.clear_stored_before()
        page = self.page()
        self.assertContains(page, "Before sale (calculated): ")
        self.assertContains(page, "250.00")


class LumpSaleMigrationTests(LumpSaleExampleBase):
    def migration(self):
        import importlib
        return importlib.import_module("investments.migrations.0038_backfill_lump_value_before")

    def old_state(self):
        self.buy_100_and_sell_200_leaving_50()
        AltValue.objects.filter(profile=self.profile, instrument=self.chit).delete()
        AltValue.objects.create(profile=self.profile, instrument=self.chit, date=SALE_DAY, total_value=D("50"), note="From sale")

    def rows(self):
        return list(AltValue.objects.filter(profile=self.profile, instrument=self.chit).order_by("date")
                    .values_list("date", "total_value", "note", "value_before"))

    def test_it_stores_the_value_before_and_the_first_purchase_value(self):
        from django.apps import apps
        self.old_state()
        self.migration().backfill(apps, None)
        self.assertEqual(self.rows(), [(BUY_DAY, D("100.00"), "From purchase", None), (SALE_DAY, D("50.00"), "From sale", D("250.00"))])

    def test_running_it_twice_changes_nothing(self):
        from django.apps import apps
        self.old_state()
        self.migration().backfill(apps, None)
        first = self.rows()
        self.migration().backfill(apps, None)
        self.assertEqual(self.rows(), first)

    def test_it_leaves_an_investment_with_an_interest_rate_without_a_purchase_entry(self):
        from django.apps import apps
        self.old_state()
        Instrument.objects.filter(pk=self.chit.pk).update(interest_rate=D("7"))
        self.migration().backfill(apps, None)
        self.assertEqual([r[0] for r in self.rows()], [SALE_DAY])

    def test_the_plain_functions(self):
        m = self.migration()
        self.assertEqual(m.sold_amount(D("3.0003"), D("11.1100"), "Price rounding 0.01 added to charges."), D("33.32"))
        self.assertEqual(m.derived_value_before([(D("100"), D("2"), "")], D("50")), D("250.00"))
        trades = [(BUY_DAY, "buy", D("100")), (SALE_DAY, "sell", D("80"))]
        self.assertEqual(m.backfill_values_before(trades, {SALE_DAY: [(D("80"), D("2.5"), "")]}, [(SALE_DAY, None, D("50"))]), {SALE_DAY: D("250.00")})
        self.assertEqual(m.backfill_values_before(trades, {SALE_DAY: [(D("80"), D("2.5"), "")]}, [(SALE_DAY, D("1"), D("50"))]), {})
        self.assertEqual(m.first_purchase_entry(trades, []), (BUY_DAY, D("100.00")))
        self.assertIsNone(m.first_purchase_entry(trades, [BUY_DAY]))
