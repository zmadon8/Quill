"""Shares allotted on a demerger (added at a cost of 0) and split or bonus units shown as labelled rows on Transactions."""
from datetime import date as d
from decimal import Decimal as D

from django.urls import reverse

from investments.errors import InvestmentsError
from investments.models import CA_DEMERGER, ORIGIN_DEMERGER, CorporateActionResponse, Transaction
from investments.services import corporate, holdings, masters
from investments.services import transactions as tx
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


class DemergerAutoTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.buy(d(2023, 1, 1), 10, 1000)
        self.client.force_login(self.user)
        self.child = masters.create_instrument(self.profile, self.user, kind="share", name="Reliance Child", code="CHILD.NS")

    def record(self, percent=20, ratio_new=1, ratio_old=2):
        return corporate.record(self.profile, self.user, instrument=self.reliance, ex_date=d(2024, 1, 1), kind="demerger", ratio_old=ratio_old,
                                ratio_new=ratio_new, target_instrument=self.child, cost_percent_to_target=D(percent))

    def auto(self):
        return Transaction.objects.filter(instrument=self.child, auto_created=True)

    def test_applying_enters_the_new_shares_from_the_ratio(self):
        action = self.record()
        corporate.respond(self.profile, self.user, action.pk, corporate.STATUS_APPLIED)
        [t] = self.auto()
        self.assertEqual((t.units, t.price, t.origin, t.date, t.corporate_action_id), (D(5), 0, ORIGIN_DEMERGER, d(2024, 1, 1), action.pk))
        self.assertEqual(corporate.demerger_gaps(self.profile, action), [])

    def test_applying_again_does_not_double_count(self):
        action = self.record()
        corporate.respond(self.profile, self.user, action.pk, corporate.STATUS_APPLIED)
        corporate.respond(self.profile, self.user, action.pk, corporate.STATUS_APPLIED, inherit_dates=True)
        self.assertEqual(self.auto().count(), 1)

    def test_zero_cost_percent_is_allowed(self):
        action = self.record(percent=0)
        corporate.respond(self.profile, self.user, action.pk, corporate.STATUS_APPLIED)
        self.assertEqual(self.auto().count(), 1)
        self.assertEqual(corporate.applied_demergers(self.profile)[self.reliance.pk][0][3], 0)

    def test_dates_are_not_inherited_by_default(self):
        action = self.record()
        corporate.respond(self.profile, self.user, action.pk, corporate.STATUS_APPLIED)
        self.assertFalse(CorporateActionResponse.objects.get(profile=self.profile, action=action).inherit_dates)

    def test_editing_replaces_the_automatic_entries(self):
        action = self.record()
        corporate.respond(self.profile, self.user, action.pk, corporate.STATUS_APPLIED)
        corporate.update(self.profile, self.user, action.pk, ex_date=d(2024, 1, 1), ratio_old=1, ratio_new=1, target_instrument=self.child,
                         cost_percent_to_target=D(0))
        [t] = self.auto()
        self.assertEqual(t.units, D(10))
        action.refresh_from_db()
        self.assertEqual(action.cost_percent_to_target, 0)

    def test_a_hand_recorded_entry_is_kept_and_not_doubled(self):
        action = self.record()
        corporate.respond(self.profile, self.user, action.pk, corporate.STATUS_APPLIED)
        tx.edit_transaction(self.profile, self.user, self.auto().get().pk, units=D(4))
        corporate.update(self.profile, self.user, action.pk, ex_date=d(2024, 1, 1), ratio_old=1, ratio_new=1, target_instrument=self.child,
                         cost_percent_to_target=D(30))
        self.assertEqual(self.auto().count(), 0)
        self.assertEqual(Transaction.objects.filter(instrument=self.child).count(), 1)

    def test_not_applicable_removes_the_automatic_entries(self):
        action = self.record()
        corporate.respond(self.profile, self.user, action.pk, corporate.STATUS_APPLIED)
        corporate.respond(self.profile, self.user, action.pk, corporate.STATUS_NA)
        self.assertEqual(Transaction.objects.filter(instrument=self.child).count(), 0)

    def test_edit_page_saves(self):
        action = self.record()
        corporate.respond(self.profile, self.user, action.pk, corporate.STATUS_APPLIED)
        url = reverse("investments_corporate_action_edit", args=[action.pk])
        self.assertContains(self.client.get(url), "cost_percent_to_target")
        r = self.client.post(url, {"ex_date": "2024-01-01", "ratio_old": "1", "ratio_new": "3", "target_instrument": self.child.pk,
                                   "cost_percent_to_target": "0", "notes": ""})
        self.assertRedirects(r, reverse("investments_corporate_actions"))
        self.assertEqual(self.auto().get().units, D(30))


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

    def test_later_pages_work_with_an_automatic_row(self):
        self.split()
        for _ in range(55):
            self.buy(d(2024, 2, 1), 1, 1000)
        first = self.client.get(reverse("investments_transactions"))
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.context["automatic_count"], 0)
        second = self.client.get(reverse("investments_transactions"), {"page": 2})
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.context["automatic_count"], 1)
        self.assertContains(second, "Split (added automatically)")


class DemergerOverrideTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.buy(d(2023, 1, 1), 10, 1000)
        self.client.force_login(self.user)
        self.child = masters.create_instrument(self.profile, self.user, kind="share", name="Reliance Child", code="CHILD.NS")
        self.action = corporate.record(self.profile, self.user, instrument=self.reliance, ex_date=d(2024, 1, 1), kind="demerger", ratio_old=2,
                                       ratio_new=1, target_instrument=self.child, cost_percent_to_target=D(20))
        corporate.respond(self.profile, self.user, self.action.pk, corporate.STATUS_APPLIED)
        [self.row] = corporate.bucket_allotments(self.profile, self.action)

    def auto(self):
        return Transaction.objects.filter(instrument=self.child, auto_created=True)

    def override(self, text):
        return corporate.set_units_overrides(self.profile, self.user, self.action.pk, {self.row["key"]: text})

    def test_computed_units_are_the_default(self):
        self.assertEqual((self.row["default"], self.row["units"], self.row["override"]), (D(5), D(5), ""))
        self.assertEqual(self.auto().get().units, D(5))

    def test_override_replaces_the_computed_units(self):
        self.override("7")
        self.assertEqual(self.auto().get().units, D(7))
        self.assertEqual(Transaction.objects.filter(instrument=self.child).count(), 1)

    def test_override_survives_editing_the_ratio_and_applying_again(self):
        self.override("7")
        corporate.update(self.profile, self.user, self.action.pk, ex_date=d(2024, 1, 1), ratio_old=1, ratio_new=1, target_instrument=self.child,
                         cost_percent_to_target=D(20))
        self.assertEqual(self.auto().get().units, D(7))
        corporate.respond(self.profile, self.user, self.action.pk, corporate.STATUS_NA)
        self.assertFalse(self.auto().exists())
        corporate.respond(self.profile, self.user, self.action.pk, corporate.STATUS_APPLIED)
        self.assertEqual(self.auto().get().units, D(7))

    def test_clearing_reverts_to_the_computed_units(self):
        self.override("7")
        self.override("")
        self.assertEqual(self.auto().get().units, D(5))
        self.assertEqual(CorporateActionResponse.objects.get(profile=self.profile, action=self.action).units_override, {})

    def test_zero_means_no_entry(self):
        self.override("0")
        self.assertFalse(self.auto().exists())

    def test_bad_input_is_refused(self):
        for text in ("-1", "abc", "2.5", "nan"):
            with self.assertRaises(InvestmentsError):
                self.override(text)
        with self.assertRaises(InvestmentsError):
            corporate.set_units_overrides(self.profile, self.user, self.action.pk, {"999:999:0": "3"})
        self.assertEqual(self.auto().get().units, D(5))

    def test_hand_entered_bucket_is_not_overridden(self):
        self.auto().delete()
        mine = self.buy(d(2024, 1, 1), 4, 0, instrument=self.child, origin=ORIGIN_DEMERGER, corporate_action=self.action)
        self.override("9")
        self.assertFalse(self.auto().exists())
        self.assertEqual(Transaction.objects.get(pk=mine.pk).units, D(4))

    def test_cost_split_is_unchanged(self):
        self.override("7")
        self.action.refresh_from_db()
        self.assertEqual(self.action.cost_percent_to_target, D(20))
        self.assertEqual(corporate.demerger_terms(self.profile, [self.action.pk])[self.action.pk].fraction, D(20) / 100)

    def test_page_shows_calculated_units_beside_the_override(self):
        self.override("7")
        r = self.client.get(reverse("investments_corporate_action_edit", args=[self.action.pk]))
        self.assertContains(r, 'data-table-id="demerger-allotments"')
        self.assertContains(r, f'name="{self.row["field"]}" value="7"')
        self.assertContains(r, 'placeholder="5"')

    def test_saving_the_page_sets_and_rejects_overrides(self):
        url = reverse("investments_corporate_action_edit", args=[self.action.pk])
        data = {"ex_date": "2024-01-01", "ratio_old": "2", "ratio_new": "1", "notes": "", "target_instrument": self.child.pk,
                "cost_percent_to_target": "20", self.row["field"]: "8"}
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(self.auto().get().units, D(8))
        bad = self.client.post(url, {**data, self.row["field"]: "-3"})
        self.assertEqual(bad.status_code, 200)
        self.assertContains(bad, "0 or more")
        self.assertEqual(self.auto().get().units, D(8))
