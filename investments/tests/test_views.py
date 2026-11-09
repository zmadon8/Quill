"""End-to-end page tests with the Django client."""
from datetime import date as d
from decimal import Decimal as D

from django.urls import reverse

from accounts.models import ROLE_READER
from investments.models import Broker, Instrument, InvestmentHistory, Portfolio, Transaction
from investments.services import holdings, masters, prices, transactions as tx
from investments.tests.base import InvTestCase, make_user


class PageTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def post(self, name, data, args=None, follow=False):
        return self.client.post(reverse(name, args=args or []), data, follow=follow)

    def test_add_investment_flow_confirm_then_create(self):
        r = self.client.get(reverse("investments_add_2") + "?kind=share")
        self.assertEqual(r.status_code, 200)
        data = {"kind": "share", "name": "Infosys", "code": "INFY.NS", "isin": "", "currency": "INR", "asset_class": "equity", "sector": "IT"}
        r = self.post("investments_add_2", data)
        self.assertContains(r, "Confirm")
        self.assertFalse(Instrument.objects.filter(name="Infosys").exists())
        r = self.post("investments_add_2", {**data, "confirmed": "1"})
        inst = Instrument.objects.get(name="Infosys")
        self.assertRedirects(r, reverse("investments_added", args=[inst.pk]))
        self.assertContains(self.client.get(reverse("investments_added", args=[inst.pk])), "What next")

    def test_duplicate_is_flagged_on_confirm_page(self):
        data = {"kind": "share", "name": "Reliance Industries", "code": "", "currency": "INR", "asset_class": "equity"}
        r = self.post("investments_add_2", data)
        self.assertContains(r, "may already exist")
        r = self.post("investments_add_2", {**data, "confirmed": "1"})
        self.assertEqual(Instrument.objects.filter(name="Reliance Industries").count(), 1)
        self.assertContains(r, "already exists")

    def test_buy_then_sell_through_the_forms_and_dashboard(self):
        base = {"date": "2024-01-01", "instrument": self.reliance.pk, "portfolio": self.portfolio.pk, "broker": self.zerodha.pk,
                "units": "10", "price": "100", "charges": "5"}
        r = self.post("investments_txn_new_buy", base)
        self.assertRedirects(r, reverse("investments_transactions"))
        t = Transaction.objects.get()
        self.assertEqual(tx.core.buy_total(t), D("1005"))
        prices.set_manual_price(self.profile, self.user, self.reliance, d(2024, 6, 1), "150")
        r = self.client.get(reverse("investments_dashboard"))
        self.assertContains(r, "Reliance Industries")
        self.assertContains(r, "₹1.50 k")
        over = {**base, "date": "2024-02-01", "units": "11"}
        r = self.post("investments_txn_new_sell", over)
        self.assertEqual(r.status_code, 409)
        self.assertContains(r, "This change is refused", status_code=409)
        self.assertEqual(Transaction.objects.count(), 1)
        ok = {**base, "date": "2024-02-01", "units": "10"}
        self.assertRedirects(self.post("investments_txn_new_sell", ok), reverse("investments_transactions"))

    def test_refused_edit_page_lists_the_conflicting_sale(self):
        buy = self.buy(d(2024, 1, 1), 10, 100)
        sale = self.sell(d(2024, 2, 1), 10, 120)
        form = {"date": "2024-01-01", "instrument": self.reliance.pk, "portfolio": self.portfolio.pk, "broker": self.zerodha.pk,
                "units": "6", "price": "100", "charges": "0", "version": buy.version}
        r = self.post("investments_txn_edit", form, [buy.pk])
        self.assertEqual(r.status_code, 409)
        self.assertContains(r, "units are sold or moved", status_code=409)
        self.assertContains(r, reverse("investments_txn_edit", args=[sale.pk]), status_code=409)

    def test_sale_form_availability_json(self):
        self.buy(d(2024, 1, 1), 10, 100)
        r = self.client.get(reverse("investments_available_units"), {"instrument": self.reliance.pk, "date": "2024-03-01"})
        data = r.json()
        self.assertEqual(data["buckets"][0]["units"], "10.0000")
        self.assertEqual(data["buckets"][0]["broker_name"], "Zerodha")

    def test_awaiting_flow_through_pages(self):
        r = self.post("investments_txn_new_awaiting", {"date": "2024-11-04", "instrument": self.fund.pk, "portfolio": self.portfolio.pk,
                                                       "broker": self.zerodha.pk, "amount": "50,000", "charges": "0"})
        self.assertRedirects(r, reverse("investments_transactions"))
        t = Transaction.objects.get()
        self.assertEqual(t.status, "awaiting")
        self.assertContains(self.client.get(reverse("investments_dashboard")), "waiting for units")      # paid in 2024: past the reminder
        self.assertContains(self.client.get(reverse("investments_txn_to_confirm")), "Complete")
        prices.set_manual_price(self.profile, self.user, self.fund, d(2024, 11, 5), "50")
        self.assertContains(self.client.get(reverse("investments_txn_complete", args=[t.pk])), "1,000")
        r = self.post("investments_txn_complete", {"allotment_date": "2024-11-06", "units": "1000", "version": t.version}, [t.pk])
        self.assertRedirects(r, reverse("investments_transactions"))
        t.refresh_from_db()
        self.assertEqual((t.status, t.price), ("final", D("50.0000")))

    def test_complete_with_unconfirmed_difference_shows_message(self):
        t = tx.add_transaction(self.profile, self.user, side="buy", instrument=self.fund, portfolio=self.portfolio, broker=self.zerodha,
                               date=d(2024, 11, 4), awaiting=True, amount=D(50000))
        r = self.post("investments_txn_complete", {"allotment_date": "2024-11-06", "units": "900", "nav": "50"}, [t.pk])
        self.assertContains(r, "differs from the amount paid")
        t.refresh_from_db()
        self.assertEqual(t.status, "awaiting")

    def test_delete_then_restore_from_history_page(self):
        t = self.buy(d(2024, 1, 1), 10, 100)
        self.post("investments_txn_delete", {}, [t.pk])
        self.assertFalse(Transaction.objects.exists())
        page = self.client.get(reverse("investments_history"))
        self.assertContains(page, "Restore")
        row = InvestmentHistory.objects.filter(change_kind="delete").get()
        self.post("investments_history_restore", {}, [row.pk])
        self.assertTrue(Transaction.objects.filter(pk=t.pk).exists())

    def test_investment_page_shows_figures_and_forms(self):
        self.buy(d(2023, 1, 1), 10, 100)
        prices.set_manual_price(self.profile, self.user, self.reliance, d(2024, 1, 1), "120")
        r = self.client.get(reverse("investments_investment", args=[self.reliance.pk]))
        self.assertContains(r, "Reliance Industries")
        self.assertContains(r, "Where it is held")
        self.assertContains(r, "Zerodha")
        self.assertContains(r, "Purchase by purchase")

    def test_alternative_investment_page_takes_dated_values(self):
        fd = masters.create_instrument(self.profile, self.user, kind="alternative", name="PPF - Ziyad", asset_class="debt")
        r = self.post("investments_investment_altvalue", {"date": "2024-03-31", "total_value": "7,85,000"}, [fd.pk])
        self.assertEqual(r.status_code, 302)
        self.assertContains(self.client.get(reverse("investments_investment", args=[fd.pk])), "Dated value".replace("Dated value", "alternative investment"))

    def test_settings_pages_hide_a_page_and_menu_follows(self):
        self.post("investments_settings_pages", {"shown": ["dashboard", "holdings", "transactions", "brokers", "history"]})
        row = holdings.core.get_settings(self.profile)
        self.assertIn("dividends", row.hidden_pages)
        r = self.client.get(reverse("investments_transactions"))
        self.assertNotContains(r, 'href="/investments/dividends/"')
        self.assertNotContains(r, 'href="/investments/corporate-actions/"')

    def test_settings_general_saves(self):
        masters.ensure_builtin_indices()
        r = self.post("investments_settings", {"sip_mode": "final", "awaiting_treatment": "leave_out", "awaiting_reminder_days": "10",
                                               "corporate_action_mode": "block", "long_term_days": "730", "alt_treatment": "averaged",
                                               "money_default": "full", "default_index": ""})
        self.assertRedirects(r, reverse("investments_settings"))
        row = holdings.core.get_settings(self.profile)
        self.assertEqual((row.sip_mode, row.awaiting_treatment, row.awaiting_reminder_days, row.long_term_days), ("final", "leave_out", 10, 730))

    def test_broker_settings_actions_and_defaults(self):
        self.post("investments_broker_action", {"action": "add", "name": "Direct"})
        direct = Broker.objects.get(name="Direct")
        self.post("investments_broker_action", {"action": "defaults", "default_broker_share": self.zerodha.pk, "default_broker_fund": direct.pk})
        row = holdings.core.get_settings(self.profile)
        self.assertEqual((row.default_broker_share, row.default_broker_fund), (self.zerodha, direct))
        r = self.client.get(reverse("investments_txn_new_buy") + f"?instrument={self.fund.pk}")
        self.assertContains(r, f'<option value="{direct.pk}" selected>')

    def test_money_preference_is_saved_per_person(self):
        self.post("investments_set_money_mode", {"mode": "full"})
        self.assertContains(self.client.get(reverse("investments_dashboard")), 'data-initial="full"')
        self.assertEqual(self.post("investments_set_money_mode", {"mode": "bogus"}).status_code, 400)

    def test_selection_filters_the_dashboard(self):
        other = Portfolio.objects.create(profile=self.profile, name="Spouse")
        tx.add_transaction(self.profile, self.user, side="buy", instrument=self.fund, portfolio=other, broker=self.groww, date=d(2024, 1, 1),
                           units=D(10), price=D(10))
        self.buy(d(2024, 1, 1), 5, 100)
        self.post("investments_set_selection", {"portfolio": other.pk, "broker": "", "asat": ""})
        r = self.client.get(reverse("investments_dashboard"))
        self.assertContains(r, "Parag Parikh")
        self.assertNotContains(r, "Reliance Industries</a>")

    def test_opening_balance_page(self):
        r = self.post("investments_txn_opening", {"instrument": self.reliance.pk, "portfolio": self.portfolio.pk, "broker": self.zerodha.pk,
                                                  "rows": "5", "date_0": "2019-05-01", "units_0": "10", "cost_0": "100",
                                                  "date_1": "2020-05-01", "units_1": "5", "cost_1": "120", "estimated_1": "1"})
        self.assertRedirects(r, reverse("investments_transactions"))
        self.assertEqual(Transaction.objects.filter(is_opening=True).count(), 2)
        self.assertContains(self.client.get(reverse("investments_transactions")), "Opening")

    def test_getting_started_checklist_updates(self):
        Broker.objects.all().delete()
        Instrument.objects.all().delete()
        r = self.client.get(reverse("investments_start"))
        self.assertContains(r, "Add a broker")
        self.assertNotContains(r, "Done")

    def test_delete_investment_pages(self):
        fresh = masters.create_instrument(self.profile, self.user, kind="share", name="Wipro", code="WIPRO.NS")
        r = self.post("investments_inv_delete", {}, [fresh.pk])
        self.assertRedirects(r, reverse("investments_holdings"))
        self.buy(d(2024, 1, 1), 1, 1)
        r = self.client.get(reverse("investments_inv_delete", args=[self.reliance.pk]))
        self.assertContains(r, "permanently remove")
        r = self.post("investments_inv_delete", {"confirm_name": "nope"}, [self.reliance.pk])
        self.assertTrue(Instrument.objects.filter(pk=self.reliance.pk).exists())

    def test_sorting_attribute_and_all_tables_have_headers(self):
        self.buy(d(2024, 1, 1), 1, 1)
        for name in ("investments_holdings", "investments_transactions", "investments_dashboard"):
            self.assertContains(self.client.get(reverse(name)), "data-sortable")


class PermissionTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.reader, _ = make_user("reader", ROLE_READER, profile=self.profile)
        self.client.force_login(self.reader)

    def test_reader_can_view_but_not_write(self):
        self.buy(d(2024, 1, 1), 1, 1)
        for name in ("investments_dashboard", "investments_holdings", "investments_transactions", "investments_history",
                     "investments_settings", "investments_brokers", "investments_txn_to_confirm", "investments_start"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        for name in ("investments_txn_new_buy", "investments_txn_opening", "investments_add_1", "investments_txn_transfer"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)
        r = self.client.post(reverse("investments_txn_new_buy"), {"date": "2024-01-01"})
        self.assertEqual(r.status_code, 403)
        r = self.client.post(reverse("investments_settings"), {"sip_mode": "final"})
        self.assertEqual(r.status_code, 403)
        t = Transaction.objects.get()
        self.assertEqual(self.client.post(reverse("investments_txn_delete", args=[t.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("investments_investment_price", args=[self.reliance.pk]), {"close": "5", "date": "2024-01-01"}).status_code, 403)

    def test_other_profile_data_is_invisible(self):
        _u, other = make_user("stranger")
        theirs = Portfolio.objects.create(profile=other, name="T")
        tb = Broker.objects.create(profile=other, name="TB")
        t = tx.add_transaction(other, _u, side="buy", instrument=self.reliance, portfolio=theirs, broker=tb, date=d(2024, 1, 1), units=D(1), price=D(1))
        mine = make_user("mine2")[0]
        self.client.force_login(mine)
        self.assertEqual(self.client.get(reverse("investments_txn_edit", args=[t.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("investments_broker_detail", args=[tb.pk])).status_code, 404)


class CommandTests(InvTestCase):
    def test_create_investments_profile_command(self):
        from django.core.management import call_command
        from accounts.models import Profile, User
        User.objects.create_user(username="newbie", password="pw-for-tests-1")
        call_command("create_investments_profile", "--username", "NEWBIE", "--profile", "Fresh", stdout=__import__("io").StringIO())
        profile = Profile.objects.get(name="Fresh", program="investments")
        self.assertTrue(Portfolio.objects.filter(profile=profile).exists())
        self.assertTrue(Instrument.objects.filter(kind="index", code="^NSEI").exists())
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command("create_investments_profile", "--username", "nobody", "--profile", "X")


class ReadOnlyGetTests(InvTestCase):
    def test_a_reader_opening_pages_writes_nothing(self):
        from investments.models import InvestmentSettings, Portfolio
        reader, profile = make_user("lonely_reader", ROLE_READER)
        self.client.force_login(reader)
        for name in ("investments_dashboard", "investments_settings", "investments_settings_brokers", "investments_settings_pages",
                     "investments_holdings", "investments_transactions", "investments_start"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        self.assertFalse(InvestmentSettings.objects.filter(profile=profile).exists())
        self.assertFalse(Portfolio.objects.filter(profile=profile).exists())
