"""The Edit button on every investment page: Admin to the Catalogue for shared ones, Editor to an Edit page for the profile's own."""
from datetime import date as d
from decimal import Decimal as D

from django.urls import reverse

from accounts.models import ROLE_READER
from investments.models import CatalogueHistory, InvestmentSettings
from investments.services import fetch, masters
from investments.tests.base import InvTestCase, make_user


class OwnInstrumentEditTests(InvTestCase):
    def setUp(self):
        super().setUp()
        self.fd = masters.create_instrument(self.profile, self.user, kind="alternative", name="Bank FD", asset_class="debt",
                                            interest_rate=D(7), interest_type="compound")
        self.url = reverse("investments_investment_edit", args=[self.fd.pk])
        self.editor, _p = make_user("ed", admin=False, profile=self.profile)
        self.reader, _p = make_user("rd", role=ROLE_READER, admin=False, profile=self.profile)

    def data(self, **extra):
        data = {"name": "Bank FD", "code": "", "isin": "", "currency": "INR", "asset_class": "debt", "sector": "", "interest_rate": "7",
                "interest_type": "compound", "maturity_date": ""}
        data.update(extra)
        return data

    def test_editor_edits_alternative_and_changes_are_logged(self):
        self.client.force_login(self.editor)
        before = InvestmentSettings.objects.get(profile=self.profile).data_version
        r = self.client.post(self.url, self.data(name="Post Office FD", interest_rate="7.5", interest_type="simple", maturity_date="2030-01-01",
                                                 code="POFD"))
        self.assertRedirects(r, reverse("investments_investment", args=[self.fd.pk]))
        self.fd.refresh_from_db()
        self.assertEqual((self.fd.name, self.fd.code, self.fd.interest_rate, self.fd.interest_type, self.fd.maturity_date),
                         ("Post Office FD", "POFD", D("7.5"), "simple", d(2030, 1, 1)))
        self.assertGreater(InvestmentSettings.objects.get(profile=self.profile).data_version, before)
        self.assertTrue(CatalogueHistory.objects.filter(instrument_id_ref=self.fd.pk, field="name", new="Post Office FD").exists())

    def test_taxed_as_interest_bumps_shared_version(self):
        self.client.force_login(self.editor)
        before = fetch.price_version()
        self.client.post(self.url, self.data(taxed_as_interest="on"))
        self.fd.refresh_from_db()
        self.assertTrue(self.fd.taxed_as_interest)
        self.assertGreater(fetch.price_version(), before)

    def test_rate_limit_and_duplicate_refused(self):
        self.client.force_login(self.editor)
        r = self.client.post(self.url, self.data(interest_rate="1001"))
        self.assertEqual(r.status_code, 200)
        masters.create_instrument(self.profile, self.user, kind="alternative", name="PPF", asset_class="debt")
        r = self.client.post(self.url, self.data(name="ppf"))
        self.assertContains(r, "already exists")
        self.fd.refresh_from_db()
        self.assertEqual((self.fd.name, self.fd.interest_rate), ("Bank FD", D(7)))

    def test_reader_gets_403_and_sees_no_edit_button(self):
        self.client.force_login(self.reader)
        self.assertEqual(self.client.post(self.url, self.data(name="X")).status_code, 403)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        page = self.client.get(reverse("investments_investment", args=[self.fd.pk]))
        self.assertNotContains(page, self.url)

    def test_shared_instrument_not_editable_by_editor_here(self):
        self.client.force_login(self.editor)
        url = reverse("investments_investment_edit", args=[self.reliance.pk])
        self.assertEqual(self.client.post(url, self.data(name="Hacked")).status_code, 404)
        self.reliance.refresh_from_db()
        self.assertEqual(self.reliance.name, "Reliance Industries")

    def test_buttons_by_role_and_kind(self):
        self.client.force_login(self.editor)
        own = self.client.get(reverse("investments_investment", args=[self.fd.pk]))
        self.assertContains(own, f'class="btn q" href="{self.url}">Edit</a>')
        shared = self.client.get(reverse("investments_investment", args=[self.reliance.pk]))
        self.assertNotContains(shared, reverse("investments_admin_catalogue_item", args=[self.reliance.pk]))
        self.assertNotContains(shared, reverse("investments_investment_edit", args=[self.reliance.pk]))
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("investments_investment", args=[self.reliance.pk])),
                            reverse("investments_admin_catalogue_item", args=[self.reliance.pk]))
