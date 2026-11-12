"""Shares allotted on a demerger (added at a cost of 0) and split or bonus units shown as labelled rows on Transactions."""
from datetime import date as d
from decimal import Decimal as D

from django.urls import reverse

from investments.models import CA_DEMERGER, ORIGIN_DEMERGER, Transaction
from investments.services import corporate, holdings, masters
from investments.tests.base import InvTestCase


class AllotmentTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.buy(d(2023, 1, 1), 10, 1000)
        self.client.force_login(self.user)

    def demerger(self):
        child = masters.create_instrument(self.profile, self.user, kind="share", name="Reliance Child", code="CHILD.NS")
        action = corporate.record(self.profile, self.user, instrument=self.reliance, ex_date=d(2024, 1, 1), kind="demerger", ratio_old=1,
                                  ratio_new=1, target_instrument=child, cost_percent_to_target=D(20))
        corporate.respond(self.profile, self.user, action.pk, corporate.STATUS_APPLIED)
        return action, child

    def test_add_form_is_prefilled_from_the_demerger(self):
        action, child = self.demerger()
        r = self.client.get(reverse("investments_txn_new_buy"), {"action": action.pk})
        form = r.context["form"]
        self.assertEqual(form.initial["origin"], ORIGIN_DEMERGER)
        self.assertEqual(form.initial["instrument"], child)
        self.assertEqual(form.initial["date"], d(2024, 1, 1))

    def test_allotted_shares_are_added_at_zero_and_labelled(self):
        action, child = self.demerger()
        t = self.buy(d(2024, 1, 1), 5, 0, instrument=child, origin=ORIGIN_DEMERGER, corporate_action=action)
        self.assertEqual(Transaction.objects.get(pk=t.pk).price, 0)
        self.assertEqual(action.kind, CA_DEMERGER)
        r = self.client.get(reverse("investments_transactions"))
        self.assertContains(r, "Received on a demerger")
        self.assertEqual(corporate.demerger_gaps(self.profile, action), [])

    def test_gap_banner_links_to_the_add_form(self):
        action, _child = self.demerger()
        r = self.client.get(reverse("investments_corporate_actions"))
        self.assertContains(r, "Add allotted shares")
        self.assertContains(r, f"?action={action.pk}")


class AutomaticRowsTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.buy(d(2023, 1, 1), 10, 1000)
        self.client.force_login(self.user)

    def split(self, method=None):
        action = corporate.record(None, None, instrument=self.reliance, ex_date=d(2024, 1, 1), kind="split", ratio_old=1, ratio_new=5)
        corporate.respond(self.profile, self.user, action.pk, corporate.STATUS_APPLIED, choice=method)
        return action

    def test_events_method_shows_a_labelled_row_and_no_transaction(self):
        self.split()
        r = self.client.get(reverse("investments_transactions"))
        self.assertContains(r, "Split (added automatically)")
        self.assertEqual(r.context["automatic_count"], 1)
        self.assertEqual(Transaction.objects.count(), 1)
        rows, _totals = holdings.compute(self.profile, as_of=d(2024, 6, 1))
        self.assertEqual(rows[0].units, D(50))

    def test_row_units_are_the_added_units(self):
        self.split()
        rows = corporate.automatic_unit_rows(self.profile)
        self.assertEqual([(r["units"], r["label"]) for r in rows], [(D(40), "Split (added automatically)")])

    def test_transactions_method_has_no_automatic_row(self):
        self.split(corporate.CHOICE_CREATE)
        self.assertEqual(corporate.automatic_unit_rows(self.profile), [])
        r = self.client.get(reverse("investments_transactions"))
        self.assertNotContains(r, "added automatically")
        self.assertContains(r, "Split (units recorded at no cost)")
        rows, _totals = holdings.compute(self.profile, as_of=d(2024, 6, 1))
        self.assertEqual(rows[0].units, D(50))

    def test_sell_filter_hides_them(self):
        self.split()
        r = self.client.get(reverse("investments_transactions"), {"side": "sell"})
        self.assertNotContains(r, "added automatically")
