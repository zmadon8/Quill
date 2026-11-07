"""Every Fee Register screen renders (T8.9): status 200, landmarks, labelled controls, accessible tables, no em dash.

``test_every_html_route_is_listed`` keeps this list honest: a new page route that is neither here nor in ``NOT_PAGES``
fails it, so a new screen cannot ship without a render test.
"""
import re
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import get_resolver, reverse

from fees.services.excel_restore import RESTORE_CONFIRMATION
from fees.tests.test_ui_pages import EM_DASH, UiPageBase
from fees.tests.test_view_permissions import A, ROUTES, RW

# Screens a signed-in user opens with GET, as (url name, needs an id of this kind, query, editor only).
SCREENS = (
    ("fees_dashboard", None, "", False),
    ("fees_statistics", None, "", False),
    ("fees_settings", None, "?fy=2026-27", False),
    ("fees_statistics", None, "?tab=explore&measure=billed&row_dim=financialYear&col_dim=none", False),
    ("fees_statistics_year_end", None, "?fy=2026-27", False),
    ("fees_memos", None, "", False),
    ("fees_memo_drafts", None, "", False),
    ("fees_memo_new", None, "", True),
    ("fees_memo_detail", "memo", "", False),
    ("fees_memo_edit", "memo", "", True),
    ("fees_memo_based_on", "memo", "", True),
    ("fees_memo_move", "memo", "", True),
    ("fees_payment_new", None, "", True),
    ("fees_payment_edit", "payment", "", True),
    ("fees_firms", None, "", False),
    ("fees_firm_new", None, "", True),
    ("fees_firm_detail", "firm", "", False),
    ("fees_firm_edit", "firm", "", True),
    ("fees_firm_statement", "firm", "", False),
    ("fees_firm_ledger", "firm", "", False),
    ("fees_matter_new", "firm", "", True),
    ("fees_matter_detail", "matter", "", False),
    ("fees_matter_edit", "matter", "", True),
    ("fees_matter_statement", "matter", "", False),
    ("fees_matter_ledger", "matter", "", False),
    ("fees_feebook", None, "", False),
    ("fees_outstanding", None, "", False),
    ("fees_outstanding_detail", None, "", False),
    ("fees_search_page", None, "?q=alpha", False),
    ("fees_settings", None, "", False),
    ("fees_backup", None, "", True),
    ("fees_backup_clear", None, "", True),
    ("fees_import", None, "", True),
)

# Routes that are not screens: redirects, JSON, downloads, and POST-only actions. The result pages that only
# exist after a POST (import map, import result, restore preview, restored, cleared) are tested below.
NOT_PAGES = {
    "fees_landing", "fees_dashboard_kpis", "fees_statistics_data", "fees_statistics_explore", "fees_statistics_views", "fees_statistics_view_delete",
    "fees_statistics_export", "fees_statistics_annual_export", "fees_statistics_tax_summary", "fees_memo_preview_number",
    "fees_memo_preview_totals", "fees_memos_export", "fees_memo_delete", "fees_memo_write_off", "fees_memo_finalise",
    "fees_memo_word", "fees_memo_statement", "fees_payment_payees", "fees_payment_delete", "fees_payment_assign",
    "fees_firm_status", "fees_group_add", "fees_group_rename", "fees_group_remove", "fees_firm_statement_export",
    "fees_firm_ledger_export", "fees_matter_archive", "fees_matter_statement_export", "fees_matter_ledger_export",
    "fees_feebook_export", "fees_outstanding_export", "fees_outstanding_summary_export", "fees_search",
    "fees_bank_account_add", "fees_bank_account_rename", "fees_bank_account_delete", "fees_template_upload",
    "fees_template_download", "fees_template_tags_download", "fees_prefs", "fees_signature_upload", "fees_signature_download", "fees_filename_preview",
    "fees_settings_statistics_grid", "fees_backup_download", "fees_backup_restore", "fees_backup_restored",
    "fees_backup_cleared", "fees_import_inspect", "fees_import_run",
}


def route_names():
    names = set()

    def walk(patterns):
        for p in patterns:
            if hasattr(p, "url_patterns"):
                walk(p.url_patterns)
            elif getattr(p, "name", None) and p.name.startswith("fees_"):
                names.add(p.name)

    walk(get_resolver().url_patterns)
    return names


class EveryScreenTests(UiPageBase):
    def kwargs_for(self, kind):
        if kind is None:
            return {}
        ids = self.ids()
        if kind == "memo":
            return {"memo_id": ids["memo"]}
        if kind == "payment":
            return {"payment_id": ids["payment"]}
        if kind == "firm":
            return {"firm_id": ids["firm"]}
        return {"matter_id": ids["matter"]}

    def render(self, name, kind, query, user):
        kwargs = self.kwargs_for(kind)
        # The "new matter" and "new payment" screens take their parent as a query, not in the path.
        if name == "fees_matter_new":
            kwargs, query = {}, "?firm=%d" % self.ids()["firm"]
        return self.assert_page(self.page(name, kwargs, query, user=user), name + query)

    def check_structure(self, text, label):
        """Tables have a caption, scoped headers and a scrolling wrapper; every control is labelled."""
        self.assert_no_unlabelled_controls(text, label)
        for match in re.finditer(r"<table\b", text):
            start = match.start()
            end = text.index("</table>", start)
            table = text[start:end]
            self.assertIn("<caption", table, label + ": table without a caption")
            self.assertTrue(text[:start].rstrip().endswith('<div class="table-wrap">'), label + ": table outside .table-wrap")
        for th in re.findall(r"<th\b[^>]*>", text):
            self.assertIn("scope=", th, label + ": header cell without scope: " + th)
        levels = [int(n) for n in re.findall(r"<h([1-6])[ >]", text)]
        self.assertEqual(levels[0], 1, label)
        for before, after in zip(levels, levels[1:]):
            self.assertLessEqual(after, before + 1, label + ": heading level skipped")

    def test_every_screen_renders_for_an_editor(self):
        for name, kind, query, _editor_only in SCREENS:
            # Import and clear-all are Admin only, so the Admin renders those.
            text = self.render(name, kind, query, self.admin if ROUTES[name][0] == A else self.editor)
            self.check_structure(text, name)

    def test_titles_repeating_the_header_or_tab_are_visually_hidden(self):
        """The header entry or sub-tab underlined on these pages already names them, so the title is for screen readers only."""
        for name, query, title in (("fees_memos", "", "Memos"), ("fees_memo_drafts", "", "Draft memos"),
                                   ("fees_firms", "", "Firms"), ("fees_feebook", "", "Feebook"),
                                   ("fees_settings", "", "Settings"), ("fees_dashboard", "", "Statistics"),
                                   ("fees_statistics", "?tab=standard", "Statistics")):
            text = self.render(name, None, query, self.editor)
            self.assertRegex(text, r'<h1 class="visually-hidden">%s</h1>' % title, name)

    def test_titles_that_are_the_only_visible_name_stay_visible(self):
        for name, kind, query, title in (("fees_outstanding", None, "", "Outstanding by firm"),
                                         ("fees_outstanding_detail", None, "", "Outstanding memos"),
                                         ("fees_memo_new", None, "", "New memo"),
                                         ("fees_firm_new", None, "", "New firm"),
                                         ("fees_backup", None, "", "Backup")):
            text = self.render(name, kind, query, self.admin if ROUTES[name][0] == A else self.editor)
            self.assertIn("<h1>%s</h1>" % title, text, name)

    def test_reader_screens_render_for_a_reader(self):
        for name, kind, query, editor_only in SCREENS:
            if editor_only:
                continue
            text = self.render(name, kind, query, self.reader)
            self.check_structure(text, name + " (reader)")

    def test_editor_only_screens_are_closed_to_a_reader(self):
        for name, kind, query, editor_only in SCREENS:
            # Forms whose GET is open to a Reader (permissions table "RW": only the POST is Editor-only) show 200.
            if not editor_only or ROUTES[name][0] == RW:
                continue
            response = self.page(name, self.kwargs_for(kind), query)
            self.assertEqual(response.status_code, 403, name)

    def test_every_html_route_is_listed(self):
        listed = {name for name, _kind, _query, _editor in SCREENS}
        self.assertEqual(route_names() - listed - NOT_PAGES, set(), "new route without a render test")

    def test_screens_are_not_unlisted_routes(self):
        self.assertEqual({name for name, *_ in SCREENS} - route_names(), set())


class ResultScreenTests(UiPageBase):
    """Pages that exist only after a POST: import map and result, restore preview, restored, cleared."""

    CSV = b"Firm name,Matter name\nFirm One,Matter One\n"

    def post(self, name, data):
        self.login(self.admin)  # import, restore and clear-all are Admin only
        return self.client.post(reverse(name), data)

    def test_import_map_and_result(self):
        mapped = self.post("fees_import_inspect", {"file": SimpleUploadedFile("memos.csv", self.CSV)})
        text = self.assert_page(mapped, "import map")
        self.assert_no_unlabelled_controls(text, "import map")
        self.assertIn("Firm name", text)
        done = self.post(
            "fees_import_run",
            {"file": SimpleUploadedFile("memos.csv", self.CSV), "map_firm_name": "Firm name", "map_matter_name": "Matter name"},
        )
        text = self.assert_page(done, "import result")
        self.assertNotIn(EM_DASH, text)

    def test_restore_preview_restored_and_cleared(self):
        self.login(self.admin)
        workbook = self.body(self.client.get(reverse("fees_backup_download")))
        preview = self.post(
            "fees_backup_restore", {"action": "preview", "file": SimpleUploadedFile("backup.xlsx", workbook)}
        )
        text = self.assert_page(preview, "restore preview")
        self.assert_no_unlabelled_controls(text, "restore preview")
        with mock.patch("fees.services.excel_restore._default_backup", return_value=None):
            done = self.post(
                "fees_backup_restore",
                {"action": "restore", "file": SimpleUploadedFile("backup.xlsx", workbook), "confirmation": RESTORE_CONFIRMATION},
            )
        self.assertRedirects(done, reverse("fees_backup_restored"), fetch_redirect_response=False)
        self.assert_page(self.client.get(reverse("fees_backup_restored")), "restored")
        with mock.patch("fees.services.clear_all._default_backup", return_value=None):
            cleared = self.post("fees_backup_clear", {"confirmation": self.profile.name})
        self.assertRedirects(cleared, reverse("fees_backup_cleared"), fetch_redirect_response=False)
        self.assert_page(self.client.get(reverse("fees_backup_cleared")), "cleared")
