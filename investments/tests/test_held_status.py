"""An investment is "Held" only while units (or a tentative purchase) exist."""
from datetime import date as d

from django.urls import reverse

from investments.services import holdings
from investments.tests.base import InvTestCase


class HeldStatusTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def page(self, status=""):
        url = reverse("investments_holdings") + (f"?status={status}" if status else "")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_an_investment_never_bought_is_not_listed_as_held(self):
        # setUp adds Reliance and a fund to the profile; nothing has been bought.
        self.assertNotIn("Reliance Industries", self.page())
        self.assertNotIn("Reliance Industries", self.page("held"))
        page = self.page("not_bought")
        self.assertIn("Reliance Industries", page)
        self.assertIn("Not bought yet", page)
        self.assertNotIn("</span>Held</td>", page)

    def test_a_fully_sold_investment_is_sold_out_not_held(self):
        self.buy(d(2023, 1, 1), 10, 100)
        self.sell(d(2023, 6, 1), 10, 120)
        self.assertNotIn("Reliance Industries", self.page("held"))
        page = self.page("sold_out")
        self.assertIn("Reliance Industries", page)
        self.assertIn("Sold out", page)

    def test_an_investment_with_units_is_held(self):
        self.buy(d(2023, 1, 1), 10, 100)
        page = self.page("held")
        self.assertIn("Reliance Industries", page)
        self.assertIn("</span>Held</td>", page)
        self.assertNotIn("Parag Parikh", page)

    def test_average_price_and_invested_value_follow_the_units_still_held(self):
        self.buy(d(2023, 1, 1), 10, 100)
        self.buy(d(2023, 2, 1), 10, 200)
        self.sell(d(2023, 6, 1), 10, 300)   # first in, first out: the 100 lot goes, the 200 lot stays
        page = self.page("held")
        head = page[page.index("<thead>"):page.index("</thead>")]
        self.assertLess(head.index(">Units</th>"), head.index(">Average price</th>"))
        self.assertLess(head.index(">Average price</th>"), head.index(">Invested value</th>"))
        self.assertLess(head.index(">Invested value</th>"), head.index(">Value</th>"))
        row = page[page.index("Reliance Industries"):]
        row = row[:row.index("</tr>")]
        self.assertIn('data-sort="200', row)    # average price of the 10 units still held
        self.assertIn('data-sort="2000', row)   # invested value: what those units cost

    def test_all_shows_each_with_its_own_status(self):
        self.buy(d(2023, 1, 1), 10, 100)
        page = self.page("all")
        self.assertIn("Reliance Industries", page)
        self.assertIn("Parag Parikh", page)
        self.assertIn("Not bought yet", page)

    def test_held_helper_and_property(self):
        self.buy(d(2023, 1, 1), 10, 100)
        self.buy(d(2023, 1, 1), 5, 50, instrument=self.fund)
        self.sell(d(2023, 6, 1), 5, 60, instrument=self.fund)
        rows, _ = holdings.compute(self.profile, as_of=d(2024, 1, 1))
        by_name = {h.instrument.name: h for h in rows}
        self.assertTrue(by_name["Reliance Industries"].is_held)
        self.assertFalse(by_name[self.fund.name].is_held)
        self.assertEqual([h.instrument.name for h in holdings.held(rows)], ["Reliance Industries"])
        self.assertFalse(holdings.Holding(instrument=self.fund, empty=True).is_held)

    def test_investment_page_of_a_never_bought_investment_shows_no_gain(self):
        response = self.client.get(reverse("investments_investment", args=[self.reliance.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Hide (")   # hidden investments were removed (D194)
