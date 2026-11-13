"""Endpoint isolation and permission tests (T7.3): one table row per URL name in ``fees.urls``.

The table says how each route is reached:

* ``R``  : GET for any Fee Register role (pages, JSON, exports).
* ``RW`` : GET for any role, POST for an Editor only.
* ``E``  : GET and POST for an Editor only (payments, backup, import carry payment details).
* ``W``  : POST for an Editor only.
* ``A``  : GET and POST for a suite Admin only (restore, import, clear-all: an Editor or Reader gets 403).
* ``AW`` : POST for a suite Admin only.
* ``U``  : GET and POST for any role: the user's own interface preferences (column widths), which are not fee
  data (``fees_prefs``).

``test_the_table_lists_every_url_name`` fails when a route is added to ``fees.urls`` without a row here (and
when a row names a route that no longer exists), so a new endpoint cannot ship untested.
"""
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import ROLE_EDITOR, ROLE_READER, Profile, ProfileMembership
from accounts.suite import KEY_FEES
from fees import urls as fees_urls
from fees.models import Group, SavedView
from fees.services import word_template
from fees.tests import xlsx_support as xs

User = get_user_model()
PASSWORD = "x-Test-Pw-1"

R, RW, E, W, U, A, AW = "R", "RW", "E", "W", "U", "A", "AW"

# URL name -> (access, query string used for the GET request).
ROUTES = {
    "fees_landing": (R, ""),
    "fees_dashboard": (R, ""),
    "fees_dashboard_kpis": (RW, ""),
    "fees_statistics": (R, "?granularity=month&fy=2026-27"),
    "fees_statistics_data": (R, "?granularity=month&fy=2026-27"),
    "fees_statistics_explore": (R, "?measure=billed&row_dim=financialYear&col_dim=none"),
    "fees_statistics_views": (RW, ""),
    "fees_statistics_view_delete": (W, ""),
    "fees_statistics_year_end": (R, "?fy=2026-27"),
    "fees_statistics_export": (R, "?granularity=month&fy=2026-27"),
    "fees_statistics_annual_export": (R, "?fy=2026-27"),
    "fees_statistics_tax_summary": (R, "?fy=2026-27"),
    "fees_memos": (R, ""),
    "fees_memo_drafts": (R, ""),
    "fees_memo_new": (RW, ""),
    "fees_memo_picker": (R, ""),
    "fees_memo_matter_defaults": (R, "?matter=%(matter_id)d"),
    "fees_memo_preview_number": (R, "?date=2026-07-15"),
    "fees_memo_preview_totals": (R, "?num_appearances=1&fees_per_appearance=1000"),
    "fees_memos_export": (R, ""),
    "fees_memo_detail": (R, ""),
    "fees_memo_edit": (RW, ""),
    "fees_memo_delete": (W, ""),
    "fees_memo_write_off": (W, ""),
    "fees_memo_finalise": (W, ""),
    "fees_memo_based_on": (RW, ""),
    "fees_memo_move": (E, ""),
    "fees_memo_word": (R, ""),
    "fees_memo_statement": (R, ""),
    "fees_payment_new": (RW, ""),
    "fees_payment_payees": (E, "?matters=%(matter_id)d"),
    "fees_payment_edit": (RW, ""),
    "fees_payment_delete": (W, ""),
    "fees_payment_assign": (W, ""),
    "fees_firms": (R, ""),
    "fees_firm_new": (RW, ""),
    "fees_firm_detail": (R, ""),
    "fees_firm_edit": (RW, ""),
    "fees_firm_status": (W, ""),
    "fees_group_detail": (R, ""),
    "fees_group_add": (W, ""),
    "fees_group_rename": (W, ""),
    "fees_group_remove": (W, ""),
    "fees_firm_statement": (R, ""),
    "fees_firm_statement_export": (R, ""),
    "fees_firm_ledger": (R, ""),
    "fees_firm_ledger_export": (R, ""),
    "fees_matter_new": (RW, ""),
    "fees_matter_detail": (R, ""),
    "fees_matter_edit": (RW, ""),
    "fees_matter_archive": (W, ""),
    "fees_matter_statement": (R, ""),
    "fees_matter_statement_export": (R, ""),
    "fees_matter_ledger": (R, ""),
    "fees_matter_ledger_export": (R, ""),
    "fees_feebook": (R, ""),
    "fees_feebook_export": (R, ""),
    "fees_outstanding": (R, ""),
    "fees_outstanding_detail": (R, ""),
    "fees_outstanding_export": (R, ""),
    "fees_outstanding_summary_export": (R, ""),
    "fees_search": (R, "?q=alpha"),
    "fees_search_page": (R, "?q=alpha"),
    "fees_settings": (RW, ""),
    "fees_bank_account_add": (W, ""),
    "fees_bank_account_rename": (W, ""),
    "fees_bank_account_delete": (W, ""),
    "fees_template_upload": (W, ""),
    "fees_template_download": (R, ""),
    "fees_template_tags_download": (R, ""),
    "fees_signature_upload": (W, ""),
    "fees_signature_download": (R, ""),
    "fees_filename_preview": (R, "?pattern=Memo+%7Bmemo_no%7D"),
    "fees_settings_statistics_grid": (RW, "?fy=2026-27"),
    "fees_prefs": (U, "?key=col-widths:memos"),
    "fees_backup": (E, ""),
    "fees_backup_download": (E, ""),
    "fees_backup_restore": (A, ""),
    "fees_backup_clear": (A, ""),
    "fees_backup_restored": (A, ""),
    "fees_backup_cleared": (A, ""),
    "fees_import": (A, ""),
    "fees_import_inspect": (AW, ""),
    "fees_import_run": (AW, ""),
}


# Routes whose GET is a redirect for every member allowed in: the landing page opens the default tab; a
# result page with no finished job in the session goes back to the backup page; and the restore route is
# POST-driven (its upload form lives on the backup page), so a GET sends the user back there.
FIXTURE = Path(__file__).parent / "fixtures" / "Template 2-11-2026 (short tags).docx"

REDIRECTS = {"fees_landing", "fees_backup_restore", "fees_backup_restored", "fees_backup_cleared"}

# Editor-only routes that also accept POST (the payment forms are RW: a Reader may open them, only an Editor saves) (the rest of the E routes are GET only).
E_POST = {"fees_memo_move"}

# Admin-only routes that take a POST from the Admin without a 403 or 405 (the GET-and-POST ones plus the POST-only ones).
ADMIN_POST = {"fees_backup_restore", "fees_backup_clear", "fees_import_inspect", "fees_import_run"}


def route_names():
    """Every URL name in fees.urls, in order."""
    return [p.name for p in fees_urls.urlpatterns]


def route_params():
    """URL name -> the names of its path converters (the object ids it takes)."""
    return {p.name: sorted(p.pattern.converters) for p in fees_urls.urlpatterns}


def make_user(name, profile=None, role=None):
    user = User.objects.create_user(username=name, password=PASSWORD)
    if profile is not None:
        ProfileMembership.objects.create(user=user, profile=profile, role=role)
    return user


def id_kwargs(seed, profile):
    """The object ids of one seeded profile, keyed by the converter names used in fees.urls."""
    group = Group.objects.filter(firm=seed["firm_a"]).first()
    return {
        "memo_id": seed["memo_a"].pk,
        "firm_id": seed["firm_a"].pk,
        "group_id": group.pk,
        "matter_id": seed["matter_1"].pk,
        "payment_id": seed["single"]["id"],
        "account_id": seed["bank"].pk,
        "view_id": SavedView.objects.get(profile=profile).pk,
    }


class RouteTableTests(TestCase):
    def test_the_table_lists_every_url_name(self):
        names = route_names()
        self.assertEqual(len(names), len(set(names)), "duplicate URL names in fees.urls")
        self.assertFalse([n for n in names if not n], "an unnamed route in fees.urls")
        self.assertEqual(sorted(set(names) - set(ROUTES)), [], "route without a permissions row")
        self.assertEqual(sorted(set(ROUTES) - set(names)), [], "permissions row for a missing route")

    def test_every_access_code_is_known(self):
        for name, (access, _query) in ROUTES.items():
            self.assertIn(access, (R, RW, E, W, U, A, AW), name)

    def test_every_id_param_is_known(self):
        known = {"memo_id", "firm_id", "group_id", "matter_id", "payment_id", "account_id", "view_id"}
        for name, params in route_params().items():
            self.assertLessEqual(set(params), known, name)


@override_settings(SECURE_SSL_REDIRECT=False)
class PermissionBase(TestCase):
    def setUp(self):
        self.profile = Profile.objects.create(program=KEY_FEES, name="Perm-Fees")
        self.seed = xs.seed_web_data(self.profile)
        # The Word export needs an uploaded template (no template, no export), so the role tests seed one.
        word_template.upload_template(self.profile, FIXTURE.name, FIXTURE.read_bytes())
        self.reader = make_user("reader-p", self.profile, ROLE_READER)
        self.editor = make_user("editor-p", self.profile, ROLE_EDITOR)
        self.outsider = make_user("outsider-p")
        self.admin = make_user("admin-p", self.profile, ROLE_EDITOR)
        self.admin.is_superuser = True
        self.admin.save()
        self.other_profile = Profile.objects.create(program=KEY_FEES, name="Other-Perm")
        self.other_seed = xs.seed_web_data(self.other_profile)
        xs.statistics_on(self.profile)
        xs.statistics_on(self.other_profile)
        self.mine = id_kwargs(self.seed, self.profile)
        self.theirs = id_kwargs(self.other_seed, self.other_profile)

    def url(self, name, ids):
        kwargs = {param: ids[param] for param in route_params()[name]}
        query = ROUTES[name][1]
        return reverse(name, kwargs=kwargs) + (query % self.mine if "%(" in query else query)

    def expected_get(self, name):
        return 302 if name in REDIRECTS else 200

    def request(self, name, ids):
        """GET for every route a GET can reach, POST for a POST-only route."""
        url = self.url(name, ids)
        if ROUTES[name][0] in (W, AW):
            return self.client.post(url, {})
        return self.client.get(url)

    def assert_login_redirect(self, response, label):
        self.assertEqual(response.status_code, 302, label)
        self.assertIn(reverse("login"), response["Location"], label)


class RoleTests(PermissionBase):
    def test_anonymous_is_sent_to_login_on_every_route(self):
        for name in ROUTES:
            self.assert_login_redirect(self.request(name, self.mine), name)

    def test_anonymous_post_is_sent_to_login_on_every_writable_route(self):
        for name, (access, _query) in ROUTES.items():
            if access == R:
                continue
            response = self.client.post(self.url(name, self.mine), {})
            self.assert_login_redirect(response, name)

    def test_a_user_without_fees_membership_gets_403_on_every_route(self):
        self.client.force_login(self.outsider)
        for name in ROUTES:
            self.assertEqual(self.request(name, self.mine).status_code, 403, name)
        for name, (access, _query) in ROUTES.items():
            if access != R:
                self.assertEqual(self.client.post(self.url(name, self.mine), {}).status_code, 403, name)

    def test_a_reader_gets_every_read_route(self):
        self.client.force_login(self.reader)
        for name, (access, _query) in ROUTES.items():
            if access in (R, RW, U):
                self.assertEqual(self.request(name, self.mine).status_code, self.expected_get(name), name)

    def test_a_reader_is_refused_every_editor_only_route_and_every_write(self):
        self.client.force_login(self.reader)
        for name, (access, _query) in ROUTES.items():
            if access in (E, W, A, AW):
                self.assertEqual(self.request(name, self.mine).status_code, 403, name)
            if access not in (R, U):
                self.assertEqual(self.client.post(self.url(name, self.mine), {}).status_code, 403, name)

    def test_a_reader_may_use_the_user_preference_routes(self):
        self.client.force_login(self.reader)
        for name, (access, _query) in ROUTES.items():
            if access == U:
                response = self.client.post(self.url(name, self.mine), {})
                self.assertNotEqual(response.status_code, 403, name)
                self.assertNotEqual(response.status_code, 405, name)

    def test_an_editor_gets_every_page_and_export(self):
        self.client.force_login(self.editor)
        for name, (access, _query) in ROUTES.items():
            if access in (W, AW):
                continue
            if access == A:
                self.assertEqual(self.request(name, self.mine).status_code, 403, name)
            else:
                self.assertEqual(self.request(name, self.mine).status_code, self.expected_get(name), name)

    def test_an_editor_is_not_refused_on_any_write(self):
        self.client.force_login(self.editor)
        with mock.patch("fees.services.excel_restore._default_backup", return_value=None), mock.patch(
            "fees.services.clear_all._default_backup", return_value=None
        ):
            for name, (access, _query) in ROUTES.items():
                if access in (RW, W, U) or name in E_POST:
                    response = self.client.post(self.url(name, self.mine), {})
                else:
                    continue
                self.assertNotEqual(response.status_code, 403, name)
                self.assertNotEqual(response.status_code, 405, name)
                if response.status_code == 302:
                    self.assertNotIn(reverse("login"), response["Location"], name)

    def test_an_editor_is_refused_every_admin_only_route_on_get_and_post(self):
        self.client.force_login(self.editor)
        for name, (access, _query) in ROUTES.items():
            if access in (A, AW):
                self.assertEqual(self.client.post(self.url(name, self.mine), {}).status_code, 403, name)
                self.assertEqual(self.client.get(self.url(name, self.mine)).status_code, 403, name)

    def test_the_admin_gets_every_admin_only_route(self):
        self.client.force_login(self.admin)
        for name, (access, _query) in ROUTES.items():
            if access == A:
                self.assertEqual(self.request(name, self.mine).status_code, self.expected_get(name), name)

    def test_the_admin_is_not_refused_on_an_admin_only_post(self):
        self.client.force_login(self.admin)
        with mock.patch("fees.services.excel_restore._default_backup", return_value=None), mock.patch(
            "fees.services.clear_all._default_backup", return_value=None
        ):
            for name in sorted(ADMIN_POST):
                response = self.client.post(self.url(name, self.mine), {})
                self.assertNotEqual(response.status_code, 403, name)
                self.assertNotEqual(response.status_code, 405, name)
                if response.status_code == 302:
                    self.assertNotIn(reverse("login"), response["Location"], name)

    def test_an_admin_only_post_route_refuses_get_for_the_admin(self):
        self.client.force_login(self.admin)
        for name, (access, _query) in ROUTES.items():
            if access == AW:
                self.assertEqual(self.client.get(self.url(name, self.mine)).status_code, 405, name)

    def test_a_post_only_route_refuses_get_for_an_editor(self):
        self.client.force_login(self.editor)
        for name, (access, _query) in ROUTES.items():
            if access == W:
                self.assertEqual(self.client.get(self.url(name, self.mine)).status_code, 405, name)


class IsolationTests(PermissionBase):
    """Another profile's object id is a 404 on every route that takes an id (B 12)."""

    def id_routes(self):
        return [name for name, params in route_params().items() if params]

    def test_there_are_id_routes_to_check(self):
        self.assertGreaterEqual(len(self.id_routes()), 30)

    def test_another_profiles_id_is_a_404_for_an_editor(self):
        self.client.force_login(self.editor)
        for name in self.id_routes():
            if name == "fees_statistics_view_delete":
                continue  # Deleting a missing saved view is a documented no-op, see the next test.
            self.assertEqual(self.request(name, self.theirs).status_code, 404, name)

    def test_another_profiles_id_is_a_404_for_a_reader_on_read_routes(self):
        self.client.force_login(self.reader)
        for name in self.id_routes():
            if ROUTES[name][0] in (R, RW):
                self.assertEqual(self.request(name, self.theirs).status_code, 404, name)

    def test_another_profiles_saved_view_is_not_deleted(self):
        self.client.force_login(self.editor)
        view = SavedView.objects.get(profile=self.other_profile)
        response = self.client.post(reverse("fees_statistics_view_delete", kwargs={"view_id": view.pk}), {})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(SavedView.objects.filter(pk=view.pk).exists())
        self.assertTrue(SavedView.objects.filter(profile=self.profile).exists())

    def test_a_404_never_shows_the_other_profiles_data(self):
        self.client.force_login(self.editor)
        response = self.client.get(reverse("fees_memo_detail", kwargs={"memo_id": self.theirs["memo_id"]}))
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, xs.PAYMENT_DETAILS_SENTINEL, status_code=404)
