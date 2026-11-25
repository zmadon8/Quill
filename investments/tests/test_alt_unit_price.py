"""A hand-entered Manual Price History value of a per-unit alternative may be a unit price instead of a total (docs/DESIGN.md D190)."""
from decimal import Decimal as D

from django.urls import reverse

from investments.models import AltValue
from investments.services import masters
from investments.tests.base import InvTestCase, d


class UnitPriceEntryTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        self.gold = masters.create_instrument(self.profile, self.user, kind="alternative", name="Gold coins", asset_class="commodity")
        self.chit = masters.create_instrument(self.profile, self.user, kind="alternative", name="Chit fund", asset_class="debt", lump_sum=True)
        self.buy(d(2024, 1, 10), 12, 200, instrument=self.gold)

    def save(self, inst, data):
        return self.client.post(reverse("investments_investment_altvalue", args=[inst.pk]), data, follow=True)

    def row(self, inst, day):
        return AltValue.objects.filter(profile=self.profile, instrument=inst, date=day).first()

    def messages(self, response):
        return [str(m) for m in response.context["messages"]]

    def test_unit_price_only_gives_units_held_times_price(self):
        r = self.save(self.gold, {"date": "2024-03-12", "nav": "250.50", "note": "Jeweller"})
        row = self.row(self.gold, d(2024, 3, 12))
        self.assertEqual((row.total_value, row.nav), (D("3006.00"), D("250.50")))
        self.assertIn("Value saved.", self.messages(r))

    def test_the_total_is_rounded_half_up_to_two_places(self):
        self.save(self.gold, {"date": "2024-03-12", "nav": "250.5049"})
        self.assertEqual(self.row(self.gold, d(2024, 3, 12)).total_value, D("3006.06"))

    def test_both_given_the_total_wins_and_the_price_is_kept_as_typed(self):
        self.save(self.gold, {"date": "2024-03-12", "total_value": "3,100", "nav": "250.50"})
        row = self.row(self.gold, d(2024, 3, 12))
        self.assertEqual((row.total_value, row.nav), (D("3100"), D("250.50")))

    def test_a_total_alone_still_works(self):
        self.save(self.gold, {"date": "2024-03-12", "total_value": "3100"})
        row = self.row(self.gold, d(2024, 3, 12))
        self.assertEqual((row.total_value, row.nav), (D("3100"), None))

    def test_neither_given_is_refused(self):
        r = self.save(self.gold, {"date": "2024-03-12"})
        self.assertTrue(any("Enter a total value or a unit price" in m for m in self.messages(r)))
        self.assertIsNone(self.row(self.gold, d(2024, 3, 12)))

    def test_no_units_held_on_the_date_is_refused_and_nothing_is_saved(self):
        r = self.save(self.gold, {"date": "2023-12-31", "nav": "250"})
        self.assertIn("You held no units of Gold coins on 31 Dec 2023, so a unit price cannot give a value. Enter a total value instead.", self.messages(r))
        self.assertIsNone(self.row(self.gold, d(2023, 12, 31)))
        self.assertNotIn("Value saved.", self.messages(r))

    def test_everything_sold_by_the_date_is_refused(self):
        self.sell(d(2024, 2, 1), 12, 220, instrument=self.gold)
        r = self.save(self.gold, {"date": "2024-03-12", "nav": "250"})
        self.assertTrue(any("You held no units of Gold coins on 12 Mar 2024" in m for m in self.messages(r)))
        self.assertIsNone(self.row(self.gold, d(2024, 3, 12)))

    def test_no_units_but_a_total_works(self):
        self.save(self.gold, {"date": "2023-12-31", "total_value": "500"})
        self.assertEqual(self.row(self.gold, d(2023, 12, 31)).total_value, D("500"))

    def test_a_later_purchase_does_not_change_a_hand_entered_total(self):
        self.save(self.gold, {"date": "2024-03-12", "nav": "250.50"})
        self.buy(d(2024, 4, 1), 8, 260, instrument=self.gold)
        row = self.row(self.gold, d(2024, 3, 12))
        self.assertEqual((row.total_value, row.nav), (D("3006.00"), D("250.50")))

    def test_a_lump_sum_has_no_unit_price_and_needs_a_total(self):
        page = self.client.get(reverse("investments_investment", args=[self.chit.pk]))
        self.assertNotIn("nav", page.context["alt_form"].fields)
        self.assertNotContains(page, "Unit price")
        self.assertNotContains(page, "For per-unit investments, enter a unit price")
        r = self.save(self.chit, {"date": "2024-03-12", "nav": "250"})
        self.assertIsNone(self.row(self.chit, d(2024, 3, 12)))
        self.assertTrue(any("Total value" in m for m in self.messages(r)))
        self.save(self.chit, {"date": "2024-03-12", "total_value": "900", "nav": "5"})
        row = self.row(self.chit, d(2024, 3, 12))
        self.assertEqual((row.total_value, row.nav), (D("900"), None))

    def test_the_page_shows_the_hint_and_a_unit_price_column(self):
        self.save(self.gold, {"date": "2024-03-12", "nav": "250.50"})
        page = self.client.get(reverse("investments_investment", args=[self.gold.pk]))
        self.assertContains(page, "For per-unit investments, enter a unit price and the value is worked out from the units you held on that date")
        self.assertContains(page, 'data-table-id="inv-investment-2"')
        self.assertContains(page, '<th class="r">Total value</th><th class="r">Unit price</th><th>Note</th>')
        # At most two decimals, no trailing zero; the exact figure on hover (owner round 2026-12).
        self.assertContains(page, '<td class="r"><span class="m" title="250.5">250.5</span></td>')

    def test_a_hand_entry_without_a_price_has_an_empty_unit_price_cell(self):
        self.save(self.gold, {"date": "2024-03-12", "total_value": "3000"})
        page = self.client.get(reverse("investments_investment", args=[self.gold.pk]))
        self.assertContains(page, '<td class="r"></td>')
