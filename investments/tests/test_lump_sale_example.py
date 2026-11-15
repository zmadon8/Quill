"""A Lump Sum bought for 100 on day 1 and, on day 100, sold for 200 with 50 remaining, entered through the real pages.

Before the sale the holding was worth 250 (the 200 sold and the 50 left) and right after it 50. So its Manual Price History must show day 1 as
100 ("From purchase") and the sale date as 50 with "Before sale: 250.00", and its chart must hold 100 until the day before the sale, then 250 at
the before point on the sale date and 50 after it. The header Value is 50."""
import json
from decimal import Decimal as D

from django.urls import reverse

from investments.models import AltValue, Instrument
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

    def test_the_chart_is_the_same_when_values_are_averaged_between_entries(self):
        # "Averaged out" slopes between ordinary entries, but never across a sale: the value was 100 until the sale, and 250 just before it.
        masters.update_settings(self.profile, self.user, alt_treatment="averaged")
        self.buy_100_and_sell_200_leaving_50()
        self.assert_chart_steps_at_the_sale()
        self.assert_header_value_is_50()


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
        rows = {r[0]: r for r in self.history()}
        self.assertEqual(rows[SALE_DAY][1:], (D("50.00"), "From sale", D("250.00")))

    def test_an_old_sale_still_draws_100_then_250_then_50(self):
        self.make_old_state()
        self.assert_chart_steps_at_the_sale()
        self.assert_header_value_is_50()
