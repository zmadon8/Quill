"""Clients belong to one firm (owner round 2026-12): the service rules, a matter's move, the dependent Client filters, the old
addresses, the data migration and the old-backup shims."""
import importlib

from django.apps import apps
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Profile
from accounts.suite import KEY_FEES
from fees.errors import FeesError
from fees.models import Client, Matter
from fees.services import client_scope, clients, filter_options, matters, outstanding
from fees.tests.test_search import make_memo, seed_firm, seed_matter


class ClientBase(TestCase):
    def setUp(self):
        self.profile = Profile.objects.create(program=KEY_FEES, name="Clients-Fees")
        self.firm_a, self.group_a = seed_firm(self.profile, "Alpha & Co", "Pat")
        self.firm_b, self.group_b = seed_firm(self.profile, "Beta LLP", "Quinn")

    def matter(self, firm, group, name, client=None):
        m = seed_matter(self.profile, firm, group, name)
        if client is not None:
            m.client = client
            m.save()
        return m


class ClientServiceTests(ClientBase):
    def test_a_name_is_unique_within_a_firm_but_may_repeat_across_firms(self):
        clients.create_client(self.profile, self.firm_a.pk, "Acme")
        with self.assertRaises(FeesError) as caught:
            clients.create_client(self.profile, self.firm_a.pk, "ACME")
        self.assertEqual(caught.exception.code, "DUPLICATE_CLIENT_NAME")
        other = clients.create_client(self.profile, self.firm_b.pk, "Acme")
        self.assertEqual(other.firm_id, self.firm_b.pk)

    def test_find_or_create_and_resolve_use_the_matters_firm(self):
        made = clients.resolve(self.profile, self.firm_a.pk, None, "  Zed Ltd ")
        self.assertEqual((made.firm_id, made.name), (self.firm_a.pk, "Zed Ltd"))
        self.assertEqual(clients.resolve(self.profile, self.firm_a.pk, None, "zed ltd").pk, made.pk)
        # A client of another firm, chosen from the list, becomes the target firm's client of that name.
        mapped = clients.resolve(self.profile, self.firm_b.pk, made.pk, "")
        self.assertEqual((mapped.firm_id, mapped.name), (self.firm_b.pk, "Zed Ltd"))
        self.assertNotEqual(mapped.pk, made.pk)
        self.assertIsNone(clients.resolve(self.profile, self.firm_a.pk, None, ""))

    def test_the_matter_form_lists_only_the_firms_clients_and_the_kept_one(self):
        a = clients.create_client(self.profile, self.firm_a.pk, "Acme")
        b = clients.create_client(self.profile, self.firm_b.pk, "Bolt")
        self.assertEqual([c["name"] for c in clients.choices_for_firm(self.profile, self.firm_a.pk)], ["Acme"])
        self.assertEqual([c["name"] for c in clients.choices_for_firm(self.profile, self.firm_a.pk, keep_id=b.pk)], ["Acme", "Bolt"])
        self.assertEqual(clients.choices_for_firm(self.profile, None), [])
        self.assertEqual(a.firm_id, self.firm_a.pk)

    def test_rename_and_remove_are_limited_to_the_firm(self):
        a = clients.create_client(self.profile, self.firm_a.pk, "Acme")
        clients.create_client(self.profile, self.firm_a.pk, "Bolt")
        with self.assertRaises(FeesError):
            clients.rename_for_firm(self.profile, self.firm_a.pk, a.pk, "bolt")
        with self.assertRaises(FeesError) as caught:
            clients.rename_for_firm(self.profile, self.firm_b.pk, a.pk, "Other")
        self.assertEqual(caught.exception.code, "CLIENT_NOT_FOUND")
        m = self.matter(self.firm_a, self.group_a, "M1", a)
        self.assertEqual(clients.clear_for_firm(self.profile, self.firm_a.pk, a.pk), 1)
        m.refresh_from_db()
        self.assertIsNone(m.client_id)
        self.assertFalse(Client.objects.filter(pk=a.pk).exists())

    def test_moving_a_matter_to_another_firm_moves_its_client_there(self):
        a = clients.create_client(self.profile, self.firm_a.pk, "Acme")
        m = self.matter(self.firm_a, self.group_a, "M1", a)
        moved = matters.update_matter(self.profile, m.pk, firm_id=self.firm_b.pk, group_id=self.group_b.pk)
        moved.refresh_from_db()
        self.assertEqual(moved.client.firm_id, self.firm_b.pk)
        self.assertEqual(moved.client.name, "Acme")
        # A second matter moving over reuses the client already made there.
        m2 = self.matter(self.firm_a, self.group_a, "M2", a)
        again = matters.update_matter(self.profile, m2.pk, firm_id=self.firm_b.pk, group_id=self.group_b.pk)
        self.assertEqual(again.client_id, moved.client_id)
        self.assertTrue(Client.objects.filter(pk=a.pk, firm=self.firm_a).exists())


@override_settings(SECURE_SSL_REDIRECT=False, FEES_ENABLED=True)
class ClientPagesTests(ClientBase):
    def setUp(self):
        super().setUp()
        from django.contrib.auth import get_user_model
        from accounts.models import ProfileMembership

        user = get_user_model().objects.create_user("cli-editor", password="pw-cli-12345")
        ProfileMembership.objects.create(user=user, profile=self.profile, role="editor")
        self.client.force_login(user)

    def test_the_old_client_addresses_redirect(self):
        a = clients.create_client(self.profile, self.firm_a.pk, "Acme")
        self.assertRedirects(self.client.get(reverse("fees_firms_clients")), reverse("fees_firms"), fetch_redirect_response=False)
        self.assertRedirects(
            self.client.get(reverse("fees_firms_client_detail", args=[a.pk])),
            reverse("fees_firm_client_detail", args=[self.firm_a.pk, a.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(self.client.get(reverse("fees_firms_client_detail", args=[a.pk + 999])).status_code, 404)

    def test_the_firms_page_has_no_clients_tab_and_a_clients_page_only_opens_under_its_own_firm(self):
        a = clients.create_client(self.profile, self.firm_a.pk, "Acme")
        page = self.client.get(reverse("fees_firms"))
        self.assertNotContains(page, "firms/clients/")
        self.assertEqual(self.client.get(reverse("fees_firm_client_detail", args=[self.firm_a.pk, a.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("fees_firm_client_detail", args=[self.firm_b.pk, a.pk])).status_code, 404)

    def test_a_client_has_a_ledger_of_its_matters_only(self):
        # Owner round 2026-12: the client page (and the firm's Clients list) open a Ledger of that client's matters.
        acme = clients.create_client(self.profile, self.firm_a.pk, "Acme")
        mine = self.matter(self.firm_a, self.group_a, "Acme v State", acme)
        other = self.matter(self.firm_a, self.group_a, "Someone Else")
        make_memo(self.profile, mine)
        make_memo(self.profile, other, fees_misc_drafting=700)
        url = reverse("fees_firm_ledger", args=[self.firm_a.pk]) + "?client=%d" % acme.pk
        self.assertContains(self.client.get(reverse("fees_firm_client_detail", args=[self.firm_a.pk, acme.pk])), url.replace("&", "&amp;"))
        self.assertContains(self.client.get(reverse("fees_firm_clients", args=[self.firm_a.pk])), url)
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Ledger - Alpha &amp; Co - Acme")
        self.assertEqual(len(page.context["rows"]), 1)                       # only Acme's memo, not the other matter's
        self.assertContains(page, reverse("fees_firm_ledger_export", args=[self.firm_a.pk]) + "?client=%d" % acme.pk)
        self.assertContains(page, reverse("fees_firm_client_detail", args=[self.firm_a.pk, acme.pk]))   # Back goes to the client
        export = self.client.get(reverse("fees_firm_ledger_export", args=[self.firm_a.pk]), {"client": acme.pk})
        self.assertEqual(export.status_code, 200)
        # Another firm's client is not this firm's: not found.
        self.assertEqual(self.client.get(reverse("fees_firm_ledger", args=[self.firm_b.pk]), {"client": acme.pk}).status_code, 404)

    def test_a_new_client_typed_on_the_matter_form_is_made_under_the_matters_firm(self):
        response = self.client.post(reverse("fees_matter_new"), {
            "name": "Fresh", "firm_id": self.firm_b.pk, "group_id": self.group_b.pk, "client_new": "Newco",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Matter.objects.get(name="Fresh").client.firm_id, self.firm_b.pk)

    def test_search_opens_the_client_under_its_firm(self):
        from fees.services import search

        a = clients.create_client(self.profile, self.firm_a.pk, "Zyx Holdings")
        hit = next(r for r in search.search(self.profile, "Zyx") if r["kind"] == "client")
        self.assertEqual(hit["url"], reverse("fees_firm_client_detail", args=[self.firm_a.pk, a.pk]))
        self.assertEqual(hit["subtitle"], "Client \u00b7 Alpha & Co")


class ClientFilterTests(ClientBase):
    def setUp(self):
        super().setUp()
        self.acme_a = clients.create_client(self.profile, self.firm_a.pk, "Acme")
        self.acme_b = clients.create_client(self.profile, self.firm_b.pk, "Acme")
        self.solo = clients.create_client(self.profile, self.firm_a.pk, "Solo")
        self.unused = clients.create_client(self.profile, self.firm_a.pk, "Unused")
        m1 = self.matter(self.firm_a, self.group_a, "M1", self.acme_a)
        m2 = self.matter(self.firm_b, self.group_b, "M2", self.acme_b)
        m3 = self.matter(self.firm_a, self.group_a, "M3", self.solo)
        m4 = self.matter(self.firm_b, self.group_b, "M4")
        for m in (m1, m2, m3, m4):
            make_memo(self.profile, m)

    def names(self, options):
        return [c["name"] for c in options["clients"]]

    def test_memo_clients_follow_the_other_filters_and_name_the_firm_on_a_clash(self):
        options = filter_options.memo_options(self.profile, {}, "exclude_drafts")
        self.assertEqual(self.names(options), ["Acme (Alpha & Co)", "Acme (Beta LLP)", "Solo"])
        self.assertTrue(options["no_client"])
        in_a = filter_options.memo_options(self.profile, {"firm_id": self.firm_a.pk}, "exclude_drafts")
        self.assertEqual(self.names(in_a), ["Acme", "Solo"])
        self.assertFalse(in_a["no_client"])
        self.assertEqual(self.names(filter_options.memo_options(self.profile, {"firm_id": self.firm_b.pk}, "exclude_drafts")), ["Acme"])

    def test_a_chosen_client_narrows_the_other_lists_but_stays_in_its_own(self):
        options = filter_options.memo_options(self.profile, {"client_id": self.solo.pk}, "exclude_drafts")
        self.assertEqual([f["name"] for f in options["firms"]], ["Alpha & Co"])
        self.assertEqual(self.names(options), ["Acme (Alpha & Co)", "Acme (Beta LLP)", "Solo"])

    def test_a_client_with_no_matter_in_the_view_is_left_out_but_a_chosen_one_is_kept(self):
        options = filter_options.memo_options(self.profile, {"client_id": self.unused.pk}, "exclude_drafts")
        self.assertIn("Unused", self.names(options))
        self.assertNotIn("Unused", self.names(filter_options.memo_options(self.profile, {}, "exclude_drafts")))

    def test_feebook_clients_follow_the_firm_and_the_chosen_client_narrows_the_firms(self):
        import datetime

        from fees.models import Allocation, Payment

        for memo in self.profile_memos():
            payment = Payment.objects.create(profile=self.profile, amount=10, date_of_payment=datetime.date(2026, 7, 20))
            Allocation.objects.create(profile=self.profile, payment=payment, memo=memo, amount=10)
        everything = filter_options.feebook_options(self.profile, {}, [])
        self.assertEqual(self.names(everything), ["Acme (Alpha & Co)", "Acme (Beta LLP)", "Solo"])
        self.assertTrue(everything["no_client"])
        in_b = filter_options.feebook_options(self.profile, {"firm_id": self.firm_b.pk}, [])
        self.assertEqual(self.names(in_b), ["Acme"])
        chosen = filter_options.feebook_options(self.profile, {"client_id": self.solo.pk}, [])
        self.assertEqual([f["name"] for f in chosen["firms"]], ["Alpha & Co"])

    def profile_memos(self):
        from fees.models import Memo

        return list(Memo.objects.filter(profile=self.profile))

    def test_outstanding_clients_follow_the_firm_and_partner(self):
        scope = outstanding.list_outstanding_scope(self.profile, {})
        everything = filter_options.narrow_outstanding_choices(self.profile, scope, {})
        self.assertEqual([c["name"] for c in everything["clients"]], ["Acme (Alpha & Co)", "Acme (Beta LLP)", "Solo"])
        self.assertTrue(everything["no_client"])
        in_b = filter_options.narrow_outstanding_choices(self.profile, scope, {"firm_id": self.firm_b.pk})
        self.assertEqual([c["name"] for c in in_b["clients"]], ["Acme"])
        by_partner = filter_options.narrow_outstanding_choices(self.profile, scope, {"group_id": self.group_a.pk})
        self.assertEqual([c["name"] for c in by_partner["clients"]], ["Acme", "Solo"])
        self.assertFalse(by_partner["no_client"])
        chosen = filter_options.narrow_outstanding_choices(self.profile, scope, {"client_id": self.acme_b.pk})
        self.assertEqual([f["name"] for f in chosen["firms"]], ["Beta LLP"])

    def test_the_blank_choice_is_not_an_id(self):
        options = filter_options.memo_options(self.profile, {"client_id": client_scope.BLANK}, "exclude_drafts")
        self.assertEqual([f["name"] for f in options["firms"]], ["Beta LLP"])
        self.assertTrue(options["no_client"])


class ClientMigrationTests(ClientBase):
    """The data step of migration 0013, run on the live models (the firm column is already required there, so a client is built with
    the firm it will keep)."""

    def setUp(self):
        super().setUp()
        self.step = importlib.import_module("fees.migrations.0013_client_firm_data")

    def test_a_client_used_by_two_firms_is_split_and_the_biggest_firm_keeps_the_original(self):
        shared = Client.objects.create(profile=self.profile, firm=self.firm_b, name="Shared")
        for name in ("A1",):
            self.matter(self.firm_a, self.group_a, name, shared)
        for name in ("B1", "B2"):
            self.matter(self.firm_b, self.group_b, name, shared)
        # Both firms' matters point at one client, as before the migration: the data step must give each firm its own.
        self.step.give_each_client_a_firm(apps, None)
        shared.refresh_from_db()
        self.assertEqual(shared.firm_id, self.firm_b.pk)
        copy = Matter.objects.get(name="A1").client
        self.assertNotEqual(copy.pk, shared.pk)
        self.assertEqual((copy.firm_id, copy.name), (self.firm_a.pk, "Shared"))
        self.assertEqual({m.client_id for m in Matter.objects.filter(firm=self.firm_b)}, {shared.pk})

    def test_a_client_with_no_matter_is_deleted_and_the_merge_back_joins_the_copies(self):
        Client.objects.create(profile=self.profile, firm=self.firm_a, name="Idle")
        self.step.give_each_client_a_firm(apps, None)
        self.assertFalse(Client.objects.filter(name="Idle").exists())
        a = Client.objects.create(profile=self.profile, firm=self.firm_a, name="Twin")
        b = Client.objects.create(profile=self.profile, firm=self.firm_b, name="TWIN")
        ma, mb = self.matter(self.firm_a, self.group_a, "M1", a), self.matter(self.firm_b, self.group_b, "M2", b)
        self.step.merge_copies_back(apps, None)
        ma.refresh_from_db()
        mb.refresh_from_db()
        self.assertEqual(ma.client_id, a.pk)
        self.assertEqual(mb.client_id, a.pk)
        self.assertEqual(Client.objects.filter(name__iexact="twin").count(), 1)


