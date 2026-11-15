"""The sale-date step of a hand-priced investment's charts and the calculated "Before sale" line of its Manual Price History (docs/DESIGN.md D188):
a Lump Sum uses the value it stored, a per-unit share, fund or alternative works it out as the units held before the sale times the sale price."""
import json
from decimal import Decimal as D

from django.urls import reverse

from investments.services import chartview, investment_page, masters, sale_steps
from investments.services import transactions as tx
from investments.tests.base import d
from investments.tests.test_trade_prices import ManualPricedBase

END = d(2024, 12, 31)
TEXT = "Before sale \u20b91,500.00, after sale \u20b9900.00, sold \u20b9600.00"


def points(chart, day):
    """``(values of the first line, tooltip note)`` for each hover point of ``day`` ("15 May 2024")."""
    data = json.loads(chart["hover"])
    found = [(data["s"][0]["v"][i], data.get("n", {}).get(str(i))) for i, label in enumerate(data["d"]) if label == day]
    return found


class LumpSumStepTests(ManualPricedBase):
    def setUp(self):
        super().setUp()
        self.chit = masters.create_instrument(self.profile, self.user, kind="alternative", name="Chit fund", asset_class="debt", lump_sum=True)

    def lump(self, side, day, amount, **kw):
        return tx.add_lump_sum_transaction(self.profile, self.user, side=side, instrument=self.chit, portfolio=self.portfolio, broker=self.zerodha,
                                           date=day, amount=D(amount), **kw)

    def chart(self):
        return chartview.value_chart(self.profile, None, END, portfolio=None, broker=None, instrument_ids=[self.chit.pk], entries_of=self.chit)

    def test_the_chart_has_a_point_before_and_one_after_the_sale_on_the_sale_date(self):
        self.lump("buy", d(2024, 1, 3), 1000000, value_after=D(1000000))
        self.lump("sell", d(2024, 6, 12), 300000, remaining=D(800000))
        found = points(self.chart(), "12 Jun 2024")
        note = "Before sale \u20b911,00,000.00, after sale \u20b98,00,000.00, sold \u20b93,00,000.00"
        self.assertEqual(found, [("11,00,000.00", note), ("8,00,000.00", note)])

    def test_the_step_is_a_vertical_drop_on_the_same_x(self):
        self.lump("buy", d(2024, 1, 3), 1000000, value_after=D(1000000))
        self.lump("sell", d(2024, 6, 12), 300000, remaining=D(800000))
        data = json.loads(self.chart()["hover"])
        at = [i for i, label in enumerate(data["d"]) if label == "12 Jun 2024"]
        self.assertEqual(len(at), 2)
        self.assertEqual(data["x"][at[0]], data["x"][at[1]])

    def test_the_stored_value_is_used_and_the_table_shows_no_calculated_line(self):
        self.lump("buy", d(2024, 1, 3), 1000000, value_after=D(1000000))
        self.lump("sell", d(2024, 6, 12), 300000, remaining=D(800000))
        self.assertEqual(sale_steps.steps(self.profile, self.chit), [
            {"date": d(2024, 6, 12), "before": D("1100000.00"), "after": D("800000.00"), "sold": D("300000.00")}])
        page = self.client.get(reverse("investments_investment", args=[self.chit.pk]))
        self.assertContains(page, "Before sale: ")
        self.assertNotContains(page, "Before sale (calculated)")

    def test_deleting_the_sale_removes_the_step(self):
        self.lump("buy", d(2024, 1, 3), 1000000, value_after=D(1000000))
        sale = self.lump("sell", d(2024, 6, 12), 300000, remaining=D(800000))
        self.assertEqual(len(points(self.chart(), "12 Jun 2024")), 2)
        tx.delete_transaction(self.profile, self.user, sale.pk)
        self.assertEqual(sale_steps.steps(self.profile, self.chit), [])
        self.assertNotIn('"n"', self.chart()["hover"])


class PerUnitShareStepTests(ManualPricedBase):
    def setUp(self):
        super().setUp()
        self.buy(d(2024, 1, 10), 10, 100)
        self.sale = self.sell(d(2024, 5, 15), 4, 150)

    def chart(self):
        return chartview.value_chart(self.profile, None, END, portfolio=None, broker=None, instrument_ids=[self.reliance.pk], entries_of=self.reliance)

    def test_before_is_the_units_held_before_the_sale_times_the_sale_price(self):
        self.assertEqual(sale_steps.steps(self.profile, self.reliance), [
            {"date": d(2024, 5, 15), "before": D("1500.00"), "after": D("900.00"), "sold": D("600.00")}])

    def test_the_sale_markers_carry_the_same_text(self):
        value_sells = [m["label"] for m in self.chart()["markers"] if m["kind"] == "sell"]
        price_sells = [m["label"] for m in investment_page.price_chart(self.profile, self.reliance, d(2024, 1, 1), END)["markers"] if m["kind"] == "sell"]
        self.assertEqual(value_sells, [TEXT])
        self.assertEqual(price_sells, [TEXT])

    def test_nothing_is_stored_for_it(self):
        from investments.models import AltValue

        self.assertFalse(AltValue.objects.filter(instrument=self.reliance).exists())
        self.assertEqual(self.manual(d(2024, 5, 15)).close, D("150"))

    def test_the_value_chart_has_both_points_at_the_sale_date(self):
        self.assertEqual(points(self.chart(), "15 May 2024"), [("1,500.00", TEXT), ("900.00", TEXT)])

    def test_the_price_chart_has_both_points_at_the_sale_date_with_the_same_price(self):
        chart = investment_page.price_chart(self.profile, self.reliance, d(2024, 1, 1), END)
        self.assertEqual(points(chart, "15 May 2024"), [("150.00", TEXT), ("150.00", TEXT)])

    def test_the_manual_price_history_shows_a_calculated_line_with_no_controls_of_its_own(self):
        page = self.client.get(reverse("investments_investment", args=[self.reliance.pk]))
        rows = {r.date: r for r in page.context["manual_prices"]}
        self.assertEqual(rows[d(2024, 5, 15)].calc_before, D("1500.00"))
        self.assertIsNone(rows[d(2024, 1, 10)].calc_before)
        self.assertContains(page, '<small class="calc-before">Before sale (calculated): ', count=1)
        self.assertContains(page, 'data-table-id="inv-investment-manual"')

    def test_editing_the_sale_changes_the_step(self):
        tx.edit_transaction(self.profile, self.user, self.sale.pk, units="2")
        step = sale_steps.steps(self.profile, self.reliance)[0]
        self.assertEqual((step["before"], step["after"], step["sold"]), (D("1500.00"), D("1200.00"), D("300.00")))
        self.assertEqual(points(self.chart(), "15 May 2024")[0][0], "1,500.00")
        self.assertEqual(points(self.chart(), "15 May 2024")[1][0], "1,200.00")

    def test_deleting_the_sale_removes_the_step_and_the_line(self):
        tx.delete_transaction(self.profile, self.user, self.sale.pk)
        self.assertEqual(sale_steps.steps(self.profile, self.reliance), [])
        self.assertNotIn('"n"', self.chart()["hover"])
        page = self.client.get(reverse("investments_investment", args=[self.reliance.pk]))
        self.assertNotContains(page, "Before sale (calculated)")

    def test_a_second_sale_on_the_day_uses_the_average_sale_price(self):
        self.sell(d(2024, 5, 15), 2, 120)
        step = sale_steps.steps(self.profile, self.reliance)[0]
        # sold: 4 x 150 + 2 x 120 = 840 at an average of 140; held before: 10 units; left: 4
        self.assertEqual((step["before"], step["after"], step["sold"]), (D("1400.00"), D("560.00"), D("840.00")))

    def test_a_fetched_share_has_no_step(self):
        masters.update_shared_details(self.profile, self.user, self.reliance, price_source="yahoo")
        self.reliance.refresh_from_db()
        self.assertEqual(sale_steps.steps(self.profile, self.reliance), [])


class PerUnitAlternativeStepTests(ManualPricedBase):
    def setUp(self):
        super().setUp()
        self.buy(d(2024, 1, 1), 10, 100, instrument=self.gold)
        self.sale = self.sell(d(2024, 3, 1), 4, 150, instrument=self.gold)

    def chart(self):
        return chartview.value_chart(self.profile, None, END, portfolio=None, broker=None, instrument_ids=[self.gold.pk], entries_of=self.gold)

    def test_before_is_the_units_held_before_the_sale_times_the_sale_price(self):
        self.assertEqual(sale_steps.steps(self.profile, self.gold), [
            {"date": d(2024, 3, 1), "before": D("1500.00"), "after": D("900.00"), "sold": D("600.00")}])
        self.assertEqual(self.alt(d(2024, 3, 1)).nav, D("150"))      # the sale-date entry's nav is that price

    def test_the_value_chart_has_both_points_at_the_sale_date(self):
        self.assertEqual(points(self.chart(), "1 Mar 2024"), [("1,500.00", TEXT), ("900.00", TEXT)])

    def test_the_table_shows_the_calculated_line_next_to_the_sale_entry(self):
        page = self.client.get(reverse("investments_investment", args=[self.gold.pk]))
        rows = {r.date: r for r in page.context["alt_values"]}
        self.assertEqual(rows[d(2024, 3, 1)].calc_before, D("1500.00"))
        self.assertIsNone(rows[d(2024, 1, 1)].calc_before)
        self.assertContains(page, '<small class="calc-before">Before sale (calculated): ', count=1)
        self.assertContains(page, 'data-table-id="inv-investment-2"')

    def test_an_interest_rate_investment_has_no_step(self):
        masters.update_alt_interest(self.profile, self.user, self.gold, interest_rate=D(7), interest_type="simple", maturity_date=None)
        self.gold.refresh_from_db()
        self.assertEqual(sale_steps.steps(self.profile, self.gold), [])
