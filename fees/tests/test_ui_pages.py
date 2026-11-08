"""Fee Register user interface (Phase 8): the page shell, and a base class later UI tests reuse.

``UiPageBase`` renders a page as a signed-in user and checks the things every page must have: status 200, the
landmarks (header, main, program navigation), the skip link, the stylesheet, a single page heading, and no em dash.
Later screens subclass it and add their own checks on top of ``assert_page``.
"""
import re

from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils.html import escape

from fees.models import FeesSettings, Payment, SavedView
from fees.services import dashboard, memos, payments
from fees.tests import xlsx_support as xs
from fees.tests.test_views_read import SeededViewsBase

EM_DASH = "\u2014"
NAV_LABELS = ["Statistics", "Memos", "Firms", "Feebook", "Outstanding", "Settings"]


@override_settings(SECURE_SSL_REDIRECT=False)
class UiPageBase(SeededViewsBase):
    """Seeded profile plus helpers that render a page and check the parts every page shares."""

    def page(self, name, kwargs=None, query="", user=None):
        """GET a page as ``user`` (the Reader by default) and return the response."""
        self.login(user or self.reader)
        if name in ("fees_memos", "fees_memo_drafts", "fees_feebook") and "fy=" not in query:
            # These lists open on the current financial year; the seeded rows span two years, so ask for every year.
            query += ("&" if "?" in query else "?") + "fy="
        return self.client.get(reverse(name, kwargs=kwargs or {}) + query)

    def html(self, response):
        return response.content.decode("utf-8")

    def assert_page(self, response, label=""):
        """The checks every Fee Register page passes."""
        self.assertEqual(response.status_code, 200, label)
        text = self.html(response)
        self.assertNotIn(EM_DASH, text, label)
        self.assertIn('<html lang="en">', text, label)
        self.assertEqual(len(re.findall(r"<main[ >]", text)), 1, label)
        self.assertIn('<main id="main">', text, label)
        self.assertIn('href="#main"', text, label)
        self.assertIn('<header class="site-header"', text, label)
        self.assertIn('<nav class="program-nav" aria-label="Main">', text, label)
        self.assertIn("css/fees.css", text, label)
        self.assertEqual(len(re.findall(r"<h1[ >]", text)), 1, label)  # exactly one, visible or visually hidden
        return text

    def assert_no_unlabelled_controls(self, text, label=""):
        """Every text, search, select or file input has an id with a label for it, or an aria-label, or sits inside a label."""
        for match in re.finditer(r"<(input|select|textarea)\b([^>]*)>", text):
            attrs = match.group(2)
            if re.search(r'type="(hidden|submit|button|checkbox|radio)"', attrs):
                continue
            if "aria-label" in attrs:
                continue
            ident = re.search(r'\bid="([^"]+)"', attrs)
            if ident and ('for="%s"' % ident.group(1)) in text:
                continue
            before = text[: match.start()]
            self.assertGreater(before.rfind("<label"), before.rfind("</label>"), "%s: unlabelled %s" % (label, match.group(0)))


class ShellTests(UiPageBase):
    PAGES = (
        ("fees_dashboard", ""),
        ("fees_memos", ""),
        ("fees_memo_drafts", ""),
        ("fees_firms", ""),
        ("fees_feebook", ""),
        ("fees_outstanding", ""),
        ("fees_settings", ""),
        ("fees_backup", ""),
        ("fees_search_page", "?q=alpha"),
    )

    def test_every_page_has_the_shell(self):
        for name, query in self.PAGES:
            with self.subTest(page=name):
                # Backup carries payment details, so it is open to an Editor only (Readers get 403).
                user = self.editor if name == "fees_backup" else None
                self.assert_page(self.page(name, query=query, user=user), name)

    def test_search_and_filter_inputs_are_labelled(self):
        for name, query in (("fees_memos", ""), ("fees_search_page", "?q=alpha")):
            with self.subTest(page=name):
                self.assert_no_unlabelled_controls(self.html(self.page(name, query=query)), name)

    def test_program_nav_order_and_current_page(self):
        # The seeded profile has Statistics switched off, which leaves it out of the menu; switch it on.
        FeesSettings.objects.update_or_create(profile=self.profile, defaults={"statistics_enabled": True})
        text = self.html(self.page("fees_memos"))
        nav = text[text.index('<nav class="program-nav"'):text.index("</nav>")]
        positions = [nav.index(">%s</a>" % label) for label in NAV_LABELS]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(nav.count('aria-current="page"'), 1)
        self.assertRegex(nav, r'<a href="%s" class="on" aria-current="page">Memos</a>' % re.escape(reverse("fees_memos")))

    def test_statistics_is_left_out_when_switched_off(self):
        FeesSettings.objects.update_or_create(profile=self.profile, defaults={"statistics_enabled": False})
        nav = self.html(self.page("fees_memos"))
        nav = nav[nav.index('<nav class="program-nav"'):nav.index("</nav>")]
        self.assertNotIn(">Statistics</a>", nav)
        self.assertEqual(nav.count(">Dashboard</a>"), 1)
        self.assertEqual(nav.count('href="%s"' % reverse("fees_dashboard")), 1)

    def test_statistics_entry_is_current_on_the_dashboard_and_statistics_pages(self):
        FeesSettings.objects.update_or_create(profile=self.profile, defaults={"statistics_enabled": True})
        for name in ("fees_dashboard", "fees_statistics"):
            with self.subTest(page=name):
                text = self.html(self.page(name))
                nav = text[text.index('<nav class="program-nav"'):text.index("</nav>")]
                self.assertEqual(nav.count('aria-current="page"'), 1)
                self.assertRegex(nav, r'<a href="%s" class="on" aria-current="page">Statistics</a>' % re.escape(reverse("fees_dashboard")))
                self.assertNotIn(">Dashboard</a>", nav)

    def test_body_carries_the_ledger_class_and_stylesheet_order(self):
        text = self.html(self.page("fees_memos"))
        self.assertRegex(text, r'<body class="ledger w-\dxl">')
        self.assertLess(text.index("css/site.css"), text.index("css/ledger.css"))
        self.assertLess(text.index("css/ledger.css"), text.index("css/fees.css"))

    def test_program_name_links_to_the_dashboard(self):
        text = self.html(self.page("fees_firms"))
        self.assertIn('<span class="brand"><a href="%s" title="' % reverse("fees_dashboard"), text)

    def test_search_icon_and_bar(self):
        text = self.html(self.page("fees_memos"))
        self.assertIn('data-search-toggle aria-controls="search-pop" aria-expanded="false" aria-label="Search"', text)
        self.assertIn('<div class="search-pop" id="search-pop" hidden>', text)
        self.assertIn('role="search" method="get" action="%s"' % reverse("fees_search_page"), text)
        self.assertIn('for="search-pop-q"', text)
        # The diary's own search script must not attach to this form.
        self.assertNotIn("search-pop-form", text)

    def test_search_bar_keeps_the_query(self):
        text = self.html(self.page("fees_search_page", query="?q=alpha"))
        self.assertIn('name="q" value="alpha"', text)

    def test_scripts_and_styles_are_local_and_in_order(self):
        text = self.html(self.page("fees_memos"))
        self.assertLess(text.index("css/tokens.css"), text.index("css/site.css"))
        self.assertLess(text.index("css/site.css"), text.index("css/fees.css"))
        self.assertIn("js/fees/money.js", text)
        self.assertIn("js/fees/columns.js", text)
        self.assertNotRegex(text, r'(?:src|href)="https?://')

    def test_back_bar_only_when_a_page_asks_for_it(self):
        self.assertNotIn('class="crumb-row"', self.html(self.page("fees_memos")))


class ConfirmPageTests(UiPageBase):
    def test_clear_confirm_page(self):
        text = self.assert_page(self.page("fees_backup_clear", user=self.admin), "clear")
        self.assertIn('class="confirm warning-box"', text)
        self.assertIn('name="confirmation"', text)
        self.assertIn("Cancel", text)

    def test_busy_page_is_a_complete_document(self):
        from django.template.loader import render_to_string

        text = render_to_string("fees/busy.html")
        self.assertIn('<html lang="en">', text)
        self.assertIn('<main id="main"', text)  # the landmark the skip link targets (it also carries a class)
        self.assertNotIn(EM_DASH, text)


class PagerTests(UiPageBase):
    def render_pager(self, **meta):
        from django.template.loader import render_to_string

        return render_to_string("fees/_pager.html", {"meta": meta, "query_string": "fy=2026-27"})

    def test_pager_is_hidden_for_one_page(self):
        self.assertEqual(self.render_pager(page=1, total_pages=1, has_prev=False, has_next=False).strip(), "")

    def test_pager_links_keep_the_filters(self):
        text = self.render_pager(page=2, total_pages=3, has_prev=True, has_next=True)
        self.assertIn('<nav class="pager" aria-label="Pages">', text)
        self.assertIn('href="?fy=2026-27&amp;page=1"', text)
        self.assertIn('href="?fy=2026-27&amp;page=3"', text)
        self.assertIn("Page 2 of 3", text)

    def test_first_page_has_no_previous_link(self):
        text = self.render_pager(page=1, total_pages=3, has_prev=False, has_next=True)
        self.assertNotIn('rel="prev"', text)
        self.assertIn('aria-disabled="true"', text)


class TableFooterTests(UiPageBase):
    def test_footer_formats_figures_with_the_unit(self):
        from django.template.loader import render_to_string

        text = render_to_string(
            "fees/_table_footer.html",
            {"label_span": 2, "label": "Total (3)", "figures": [1234567, 50], "trailing": 1, "money_unit": "full"},
        )
        self.assertIn('<th scope="row" colspan="2">Total (3)</th>', text)
        self.assertIn('<td class="money">12,34,567</td>', text)
        self.assertIn('<td class="money">50</td>', text)
        self.assertIn('<td colspan="1"></td>', text)


class MemoScreenTests(UiPageBase):
    """T8.2: memo list, drafts, memo form and memo detail."""

    def test_memo_list_has_table_landmarks(self):
        text = self.assert_page(self.page("fees_memos"), "memos")
        self.assertIn('<th scope="col" data-col-fixed>No.</th>', text)
        self.assertIn('<th scope="row" colspan="4">Total (', text)
        self.assertIn('data-fees-columns="memos"', text)
        self.assertIn('aria-label="Memo actions"', text)
        self.assertIn('class="status-legend"', text)
        for word in ("Paid", "Unpaid", "Overdue", "Written Off"):
            self.assertIn("</span>%s</span>" % word, text)
        self.assertIn(">Draft Memos</a>", text)
        self.assertNotIn(">Payment</a>", text)
        self.assert_no_unlabelled_controls(text, "memos")

    def test_editor_sees_payment_buttons_unless_hidden_on_paid(self):
        editor = self.html(self.page("fees_memos", user=self.editor))
        self.assertIn('class="button small success" href="%s?memo=' % reverse("fees_payment_new"), editor)
        FeesSettings.objects.update_or_create(profile=self.profile, defaults={"hide_payment_when_paid": True})
        hidden = self.html(self.page("fees_memos", user=self.editor))
        self.assertLessEqual(hidden.count('class="button small success"'), editor.count('class="button small success"'))

    def test_reader_has_no_new_memo_button(self):
        text = self.html(self.page("fees_memos"))
        self.assertNotIn(reverse("fees_memo_new"), text)
        editor = self.html(self.page("fees_memos", user=self.editor))
        self.assertIn('href="%s"' % reverse("fees_memo_new"), editor)

    def test_status_is_words_as_well_as_a_marker(self):
        text = self.html(self.page("fees_memos"))
        self.assertRegex(text, r'<span class="status status-[a-z-]+" title="[A-Za-z ()]+"><span class="status-sq" aria-hidden="true"></span><span class="status-word visually-hidden">[A-Z]')

    def test_status_words_show_when_markers_are_off(self):
        FeesSettings.objects.update_or_create(profile=self.profile, defaults={"show_status_dots": False})
        text = self.html(self.page("fees_memos"))
        self.assertRegex(text, r'<span class="status status-[a-z-]+"><span class="status-word">[A-Z]')
        self.assertNotIn("visually-hidden\">Paid", text)

    def test_drafts_page(self):
        text = self.assert_page(self.page("fees_memo_drafts"), "drafts")
        self.assertIn('data-fees-columns="drafts"', text)
        self.assertIn("status-draft", text)
        self.assertIn("(draft)", text)

    def test_memo_form_works_without_script(self):
        text = self.assert_page(self.page("fees_memo_new", user=self.editor), "form")
        self.assertIn('method="post" action="%s"' % reverse("fees_memo_new"), text)
        for name in ("matter_id", "date", "num_appearances", "fees_per_appearance", "custom_total_fees"):
            self.assertIn('name="%s"' % name, text)
        self.assertIn('name="action" value="draft"', text)
        self.assertIn('name="action" value="save"', text)
        self.assertIn("js/fees/memo-form.js", text)
        # The live total stays hidden until the script shows it.
        self.assertIn("data-fee-total hidden", text)
        self.assertIn('data-totals-url="%s"' % reverse("fees_memo_preview_totals"), text)
        self.assert_no_unlabelled_controls(text, "form")

    def test_reader_sees_the_form_without_the_script_or_save_buttons(self):
        text = self.assert_page(self.page("fees_memo_new"), "form-reader")
        self.assertNotIn("memo-form.js", text)
        self.assertNotIn('name="action"', text)

    def test_edit_form_for_a_numbered_memo_and_a_draft(self):
        i = self.ids()
        numbered = self.assert_page(self.page("fees_memo_edit", {"memo_id": i["memo"]}, user=self.editor), "edit")
        self.assertIn('data-new="0"', numbered)
        self.assertNotIn('value="draft"', numbered)
        draft = self.assert_page(self.page("fees_memo_edit", {"memo_id": i["draft"]}, user=self.editor), "edit-draft")
        self.assertIn('data-draft="1"', draft)
        self.assertIn('value="draft"', draft)

    def test_preview_totals_uses_the_server_rule(self):
        self.login(self.reader)
        response = self.client.get(
            reverse("fees_memo_preview_totals"),
            {"num_appearances": "2", "fees_per_appearance": "1,500", "num_conferences": "1", "fees_per_conference": "500",
             "fees_misc_drafting": "250.50"},
        )
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["total_fees"], "3750.50")
        self.assertIn("thousand", body["words"].lower())

    def test_preview_totals_override_and_errors(self):
        self.login(self.reader)
        url = reverse("fees_memo_preview_totals")
        body = self.client.get(url, {"num_appearances": "2", "fees_per_appearance": "100", "custom_total_fees": "999"}).json()
        self.assertEqual(body["total_fees"], "999.00")
        bad = self.client.get(url, {"fees_per_appearance": "abc"})
        self.assertEqual(bad.status_code, 422)
        self.assertFalse(bad.json()["ok"])
        self.assertEqual(self.client.post(url).status_code, 405)

    def test_memo_detail_with_payments(self):
        i = self.ids()
        text = self.assert_page(self.page("fees_memo_detail", {"memo_id": i["memo"]}), "detail")
        self.assertIn("<h2>Payments</h2>", text)
        self.assertIn('<th scope="col" class="money">Amount</th>', text)
        self.assertIn('<th scope="row" colspan="3">Total fees</th>', text)
        self.assertNotIn(reverse("fees_payment_new"), text)
        self.assertNotIn(reverse("fees_memo_edit", kwargs={"memo_id": i["memo"]}), text)
        self.assertNotIn(reverse("fees_memo_delete", kwargs={"memo_id": i["memo"]}), text)

    def test_memo_detail_for_an_editor_has_the_actions(self):
        i = self.ids()
        text = self.assert_page(self.page("fees_memo_detail", {"memo_id": i["memo"]}, user=self.editor), "detail-editor")
        self.assertIn(reverse("fees_memo_delete", kwargs={"memo_id": i["memo"]}), text)
        self.assertIn(reverse("fees_payment_new"), text)
        self.assert_no_unlabelled_controls(text, "detail-editor")
        draft = self.assert_page(self.page("fees_memo_detail", {"memo_id": i["draft"]}, user=self.editor), "detail-draft")
        self.assertIn(reverse("fees_memo_finalise", kwargs={"memo_id": i["draft"]}), draft)


class FirmScreenTests(UiPageBase):
    """T8.3: firms, firm page with its groups, matter page and the matter form (including a move)."""

    def test_firm_list(self):
        text = self.assert_page(self.page("fees_firms"), "firms")
        self.assertIn('class="firm-list"', text)
        self.assertRegex(text, r'class="firm-status is-(active|archived)">(Active|Archived)</span>')
        self.assertNotIn("+ Matter", text)
        self.assertIn('aria-label="Show firms"', text)
        self.assertNotIn(reverse("fees_firm_new"), text)
        editor = self.html(self.page("fees_firms", user=self.editor))
        self.assertIn('href="%s"' % reverse("fees_firm_new"), editor)
        self.assertIn("+ Matter</a>", editor)
        self.assertIn("+ Memo</a>", editor)

    def test_firm_page_for_a_reader_has_no_edit_controls(self):
        i = self.ids()
        text = self.assert_page(self.page("fees_firm_detail", {"firm_id": i["firm"]}), "firm")
        self.assertIn('aria-labelledby="groups-heading"', text)
        self.assertIn('class="breadcrumb" aria-label="Back"', text)
        self.assertNotIn("/groups/add/", text)
        self.assertNotIn("/rename/", text)
        self.assertNotIn("/remove/", text)
        self.assertNotIn(reverse("fees_firm_status", kwargs={"firm_id": i["firm"]}), text)
        self.assertNotIn(reverse("fees_firm_edit", kwargs={"firm_id": i["firm"]}), text)

    def test_firm_page_for_an_editor_has_the_groups_panel(self):
        i = self.ids()
        text = self.assert_page(self.page("fees_firm_detail", {"firm_id": i["firm"]}, user=self.editor), "firm-editor")
        self.assertIn(reverse("fees_group_add", kwargs={"firm_id": i["firm"]}), text)
        self.assertIn("aria-label=\"New name for group ", text)
        self.assertIn(reverse("fees_firm_status", kwargs={"firm_id": i["firm"]}), text)
        self.assert_no_unlabelled_controls(text, "firm-editor")

    def test_firm_forms(self):
        i = self.ids()
        new = self.assert_page(self.page("fees_firm_new", user=self.editor), "firm-new")
        self.assertIn('name="name"', new)
        edit = self.assert_page(self.page("fees_firm_edit", {"firm_id": i["firm"]}, user=self.editor), "firm-edit")
        self.assertIn('name="notes"', edit)
        self.assert_no_unlabelled_controls(edit, "firm-edit")
        reader = self.assert_page(self.page("fees_firm_edit", {"firm_id": i["firm"]}), "firm-edit-reader")
        self.assertNotIn(">Save</button>", reader)

    def test_matter_page(self):
        i = self.ids()
        text = self.assert_page(self.page("fees_matter_detail", {"matter_id": i["matter"]}), "matter")
        self.assertIn('data-fees-columns="matter-memos"', text)
        self.assertIn('<th scope="col" class="money">Apps</th>', text)
        self.assertIn('<th scope="col" class="money">Confs</th>', text)
        self.assertNotIn(">Payment</a>", text)
        self.assertNotIn(reverse("fees_matter_archive", kwargs={"matter_id": i["matter"]}), text)
        editor = self.assert_page(self.page("fees_matter_detail", {"matter_id": i["matter"]}, user=self.editor), "matter-editor")
        self.assertIn(reverse("fees_matter_archive", kwargs={"matter_id": i["matter"]}), editor)
        self.assertIn("Edit Or Move Matter", editor)

    def test_matter_form_new_and_move(self):
        i = self.ids()
        new = self.assert_page(self.page("fees_matter_new", user=self.editor), "matter-new")
        self.assert_no_unlabelled_controls(new, "matter-new")
        edit = self.assert_page(self.page("fees_matter_edit", {"matter_id": i["matter"]}, user=self.editor), "matter-edit")
        self.assertIn("change to move this matter", edit)
        self.assertIn('aria-label="Move to another firm"', edit)
        self.assert_no_unlabelled_controls(edit, "matter-edit")
        other = self.seed["firm_b"].pk
        query = "?firm=%d" % other
        moved = self.assert_page(self.page("fees_matter_edit", {"matter_id": i["matter"]}, query=query, user=self.editor), "matter-move")
        self.assertIn('name="firm_id" value="%d"' % other, moved)


class FeebookAndPaymentTests(UiPageBase):
    """T8.4: the Feebook and the payment form."""

    def test_feebook_table_landmarks(self):
        text = self.assert_page(self.page("fees_feebook"), "feebook")
        self.assertIn('data-fees-columns="feebook"', text)
        self.assertIn('<th scope="col" class="money">Paid + TDS</th>', text)
        self.assertRegex(text, r'<th scope="row" colspan="4">Total \(\d+\)</th>')
        self.assertIn("<caption>", text)
        self.assertIn('aria-label="Feebook actions"', text)
        self.assert_no_unlabelled_controls(text, "feebook")

    def test_feebook_unaccounted_shows_plain_visible_text(self):
        text = self.html(self.page("fees_feebook", query="?unaccounted=1"))
        self.assertIn("<td>Unaccounted</td>", text)
        self.assertNotIn("status-unaccounted", text)

    def test_feebook_hides_edit_controls_from_a_reader(self):
        text = self.html(self.page("fees_feebook"))
        self.assertNotIn(reverse("fees_payment_new"), text)
        self.assertNotIn("/assign/", text)
        self.assertNotIn(">Attach<", text)

    def test_feebook_editor_can_edit(self):
        text = self.assert_page(self.page("fees_feebook", user=self.editor), "feebook-editor")
        self.assertIn(reverse("fees_payment_new"), text)
        self.assertNotIn("/assign/", text)
        self.assertIn('aria-label="Edit payment of ', text)
        self.assert_no_unlabelled_controls(text, "feebook-editor")

    def test_feebook_unaccounted_row_has_edit_but_no_attach_menu(self):
        """Owner decision: no "Attach Memo number" menu on Feebook rows; a memo is added from Edit."""
        text = self.html(self.page("fees_feebook", user=self.editor, query="?unaccounted=1"))
        body = text.split("<tbody>", 1)[-1].split("</tbody>", 1)[0]
        self.assertIn('aria-label="Edit payment of ', body)
        self.assertIn("<td>Unaccounted</td>", body)
        for gone in ("row-menu", "More actions", "/assign/", "Memo number", ">Attach<", "<form"):
            self.assertNotIn(gone, body)

    def test_payment_form_works_without_script(self):
        text = self.assert_page(self.page("fees_payment_new", user=self.editor), "payment")
        self.assertIn('method="post" action="%s"' % reverse("fees_payment_new"), text)
        for name in ("amount", "date_of_payment", "tds_rate", "auto_tds", "tds_amount", "payee", "bank_account_id",
                     "alloc_memo_0", "alloc_amount_0", "alloc_tds_0", "alloc_memo_2"):
            self.assertIn('name="%s"' % name, text)
        self.assertIn('<button type="submit" class="primary">Save</button>', text)
        self.assertIn("js/fees/payment-form.js", text)
        # Script-made parts stay hidden until the script shows them.
        self.assertIn("data-payee-chips hidden", text)
        self.assertIn("data-remaining role=\"status\" aria-live=\"polite\" hidden", text)
        self.assertIn('data-payees-url="%s"' % reverse("fees_payment_payees"), text)
        self.assertIn('class="crumb-row"', text)
        self.assert_no_unlabelled_controls(text, "payment")

    def selected_memo(self, text, row):
        """The memo number chosen in the row's drop-down (the option marked selected), or None."""
        select = re.search(r'<select name="alloc_memo_%d".*?</select>' % row, text, re.S)
        self.assertIsNotNone(select, "no memo drop-down for row %d" % row)
        chosen = re.search(r'<option value="([^"]*)"[^>]*? selected', select.group(0))
        return chosen.group(1) if chosen else None

    def test_payment_form_for_a_memo_prefills_the_row_and_the_payee_matters(self):
        i = self.ids()
        text = self.assert_page(self.page("fees_payment_new", query="?memo=%d" % i["memo"], user=self.editor), "payment-memo")
        memo = self.seed["memo_a"]
        memo.refresh_from_db()
        self.assertEqual(self.selected_memo(text, 0), memo.memo_number)
        self.assertIn('data-matters="%d"' % i["matter"], text)
        self.assertIn("?memo=%d" % i["memo"], text)
        self.assertIn(reverse("fees_memo_detail", kwargs={"memo_id": i["memo"]}), text)

    def test_payment_form_for_several_memos(self):
        a, b = self.seed["memo_a"], self.seed["memo_b"]
        a.refresh_from_db()
        b.refresh_from_db()
        query = "?memo=%d&memo=%d" % (a.pk, b.pk)
        text = self.assert_page(self.page("fees_payment_new", query=query, user=self.editor), "payment-two")
        self.assertEqual(self.selected_memo(text, 0), a.memo_number)
        self.assertEqual(self.selected_memo(text, 1), b.memo_number)
        self.assertIn("?memo=%d&amp;memo=%d" % (a.pk, b.pk), text)
        self.assertIn('data-matters="%d"' % self.ids()["matter"], text)

    def test_repeated_and_junk_memo_values_are_ignored(self):
        a = self.seed["memo_a"]
        text = self.assert_page(self.page("fees_payment_new", query="?memo=%d,x,%d" % (a.pk, a.pk), user=self.editor), "payment-dup")
        self.assertIn('name="alloc_memo_0"', text)
        self.assertEqual(text.count("?memo=%d" % a.pk), 1)

    def new_memos(self, count, **over):
        return [memos.create_memo(self.profile, xs.memo_input(self.seed["matter_1"].pk, **over)) for _ in range(count)]

    def test_payment_form_takes_more_than_five_memos_from_the_query(self):
        found = self.new_memos(7)
        query = "?" + "&".join("memo=%d" % m.pk for m in found)
        text = self.assert_page(self.page("fees_payment_new", query=query, user=self.editor), "payment-seven")
        for i, m in enumerate(found):
            self.assertRegex(text, r'<option value="%s" data-due="[^"]*" selected>' % re.escape(m.memo_number))
            self.assertIn('name="alloc_memo_%d"' % i, text)
        self.assertEqual(text.count("data-alloc-row>"), 7 + 1)  # the seven rows and the script's template row

    def test_each_row_is_a_separate_block_with_its_number(self):
        text = self.html(self.page("fees_payment_new", user=self.editor))
        self.assertEqual(text.count('<div class="alloc-row" data-alloc-row>'), 3 + 1)
        for n in (1, 2, 3):
            self.assertIn('<span data-row-no>%d</span>' % n, text)
        self.assertIn("<legend>Allocate To Memos</legend>", text)
        self.assertIn("+ Memo</button>", text)

    def test_memo_options_show_number_matter_and_amount_due(self):
        memo = self.new_memos(1, date="2030-03-01")[0]
        text = self.html(self.page("fees_payment_new", user=self.editor))
        label = escape("%s \u00b7 %s (Rs 14,000 Due)" % (memo.memo_number, self.seed["matter_1"].name))
        self.assertIn('<option value="%s" data-due="14000.00">%s</option>' % (memo.memo_number, label), text)
        self.assertIn('<option value="">Select...</option>', text)

    def test_memo_options_leave_out_drafts_written_off_and_paid_memos(self):
        paid = self.new_memos(1)[0]
        payments.add_payment_to_memo(self.profile, paid.pk, {"amount": 14000, "date_of_payment": "2026-08-01"})
        written_off = self.seed["memo_c"]
        written_off.refresh_from_db()
        text = self.html(self.page("fees_payment_new", user=self.editor))
        self.assertNotIn('<option value="%s"' % paid.memo_number, text)
        self.assertNotIn('<option value="%s"' % written_off.memo_number, text)

    def test_memo_options_are_newest_first_and_the_known_matter_comes_first(self):
        newest = memos.create_memo(self.profile, xs.memo_input(self.seed["matter_3"].pk, date="2031-01-01"))
        older = memos.create_memo(self.profile, xs.memo_input(self.seed["matter_1"].pk, date="2029-01-01"))
        oldest = memos.create_memo(self.profile, xs.memo_input(self.seed["matter_1"].pk, date="2028-01-01"))
        text = self.html(self.page("fees_payment_new", user=self.editor))
        order = [text.index('<option value="%s"' % m.memo_number) for m in (newest, older, oldest)]
        self.assertEqual(order, sorted(order))
        known = self.html(self.page("fees_payment_new", query="?memo=%d" % oldest.pk, user=self.editor))
        place = {m.memo_number: known.index('<option value="%s"' % m.memo_number) for m in (newest, older, oldest)}
        self.assertLess(place[older.memo_number], place[newest.memo_number])
        self.assertLess(place[oldest.memo_number], place[newest.memo_number])

    def test_editing_keeps_an_already_paid_memo_in_the_list(self):
        memo = self.new_memos(1)[0]
        dto = payments.add_payment_to_memo(self.profile, memo.pk, {"amount": 14000, "date_of_payment": "2026-08-01"})
        text = self.html(self.page("fees_payment_edit", {"payment_id": dto["id"]}, user=self.editor))
        self.assertRegex(text, r'<option value="%s" data-due="0.00" selected>[^<]*\(Rs 0 Due\)</option>' % re.escape(memo.memo_number))

    def test_options_cost_one_query_however_many_rows(self):
        found = self.new_memos(6)
        few = "?memo=%d" % found[0].pk
        many = "?" + "&".join("memo=%d" % m.pk for m in found)
        self.login(self.editor)
        url = reverse("fees_payment_new")
        self.client.get(url + few)
        with CaptureQueriesContext(connection) as one:
            self.client.get(url + few)
        with CaptureQueriesContext(connection) as six:
            self.client.get(url + many)
        # Each memo named in the query is read once for its prefill; the option list adds nothing per row.
        self.assertLessEqual(len(six), len(one) + 5 * 6)

    def test_add_another_memo_without_script_adds_an_empty_row_and_saves_nothing(self):
        a = self.seed["memo_a"]
        a.refresh_from_db()
        self.login(self.editor)
        before = Payment.objects.filter(profile=self.profile).count()
        response = self.client.post(
            reverse("fees_payment_new"),
            {"amount": "100", "tds_rate": "0", "date_of_payment": "2026-09-01", "alloc_memo_0": a.memo_number,
             "alloc_amount_0": "100", "alloc_memo_1": "", "alloc_memo_2": "", "add_row": "1"},
        )
        self.assertEqual(response.status_code, 200)
        text = self.html(response)
        self.assertIn('name="alloc_memo_3"', text)
        self.assertNotIn('name="alloc_memo_4"', text)
        self.assertIn('name="alloc_amount_0" value="100"', text)
        self.assertRegex(text, r'<option value="%s" data-due="[^"]*" selected>' % re.escape(a.memo_number))
        self.assertIn('name="add_row" value="1"', text)
        self.assertEqual(Payment.objects.filter(profile=self.profile).count(), before)

    def test_payment_edit_form(self):
        i = self.ids()
        text = self.assert_page(self.page("fees_payment_edit", {"payment_id": i["payment"]}, user=self.editor), "payment-edit")
        self.assertIn('value="Alpha payer"', text)
        self.assertIn(reverse("fees_payment_delete", kwargs={"payment_id": i["payment"]}), text)
        self.assertIn('data-matters="%d"' % i["matter"], text)
        self.assert_no_unlabelled_controls(text, "payment-edit")

    def test_payment_form_posts_without_script(self):
        a = self.seed["memo_a"]
        a.refresh_from_db()
        self.login(self.editor)
        response = self.client.post(
            reverse("fees_payment_new") + "?memo=%d" % a.pk,
            {"amount": "100", "tds_rate": "10", "auto_tds": "1", "date_of_payment": "2026-09-01", "alloc_memo_0": a.memo_number},
        )
        self.assertEqual(response.status_code, 302)

    def test_failed_save_shows_the_form_again_with_the_error(self):
        a = self.seed["memo_a"]
        self.login(self.editor)
        response = self.client.post(reverse("fees_payment_new") + "?memo=%d" % a.pk, {"amount": "abc", "date_of_payment": "2026-09-01"})
        self.assertGreaterEqual(response.status_code, 400)
        text = self.html(response)
        self.assertIn('role="alert"', text)
        self.assertIn('data-matters="%d"' % self.ids()["matter"], text)

    def test_reader_opens_the_payment_form_read_only(self):
        for name, kwargs in (("fees_payment_new", None), ("fees_payment_edit", {"payment_id": self.ids()["payment"]})):
            response = self.page(name, kwargs)
            self.assertEqual(response.status_code, 200, name)
            text = self.html(response)
            self.assertIn("Only Editors can save a payment", text, name)
            self.assertNotIn('<button type="submit" class="primary">Save</button>', text, name)
            self.assertNotIn("Delete Payment", text, name)
            self.assertNotIn("js/fees/payment-form.js", text, name)

    def test_editor_sees_save_on_the_payment_form(self):
        text = self.html(self.page("fees_payment_new", user=self.editor))
        self.assertIn('<button type="submit" class="primary">Save</button>', text)
        self.assertNotIn("Only Editors can save a payment", text)

    def test_reader_cannot_save_a_payment(self):
        self.login(self.reader)
        self.assertEqual(self.client.post(reverse("fees_payment_new"), {}).status_code, 403)
        edit = reverse("fees_payment_edit", kwargs={"payment_id": self.ids()["payment"]})
        self.assertEqual(self.client.post(edit, {}).status_code, 403)

    def test_payment_script_does_not_use_the_single_fee_rule(self):
        from pathlib import Path

        import fees

        source = (Path(fees.__file__).resolve().parent.parent / "static" / "js" / "fees" / "payment-form.js").read_text()
        self.assertNotRegex(source, r"num_appearances\s*\*\s*fees_per_appearance")
        self.assertNotIn(EM_DASH, source)


class OutstandingScreenTests(UiPageBase):
    """T8.5: the firm summary and the detail (grouped, summary and in-order views, tick boxes plus Pay)."""

    def test_firm_summary(self):
        text = self.assert_page(self.page("fees_outstanding"), "outstanding")
        self.assertIn('data-fees-columns="outstanding-firms"', text)
        self.assertIn("<caption>", text)
        self.assertIn('<th scope="col" class="money" data-col-fixed>Outstanding</th>', text)
        self.assertRegex(text, r'<th scope="row">Total \(\d+ firms?\)</th>')
        self.assertIn('class="total-card"', text)
        self.assertIn('>View</a>', text)
        self.assertIn(reverse("fees_outstanding_detail") + "?firm=%d" % self.ids()["firm"], text)
        self.assert_no_unlabelled_controls(text, "outstanding")

    def test_firm_summary_keeps_the_filters_in_the_detail_link(self):
        text = self.html(self.page("fees_outstanding", query="?overdue=1&written_off=1"))
        self.assertRegex(text, r'href="%s\?[^"]*overdue=1' % re.escape(reverse("fees_outstanding_detail")))

    def test_detail_grouped_for_a_firm(self):
        query = "?firm=%d" % self.ids()["firm"]
        text = self.assert_page(self.page("fees_outstanding_detail", query=query), "detail")
        self.assertIn('data-fees-columns="outstanding-grouped"', text)
        self.assertIn('scope="rowgroup"', text)
        self.assertIn("Subtotal, ", text)
        self.assertIn("Grand total due", text)
        # The By Firm | All Memos sub-tabs replace the old back link; Export sits on the tab row.
        self.assertIn('<a href="/fees/outstanding/detail/" class="on" aria-current="page">All Memos</a>', text)
        self.assertRegex(text, r'<div class="tab-bar">\s*<nav class="stat-tabs sub-tabs" aria-label="Outstanding lists">')
        self.assertRegex(text, r'<span class="status status-(unpaid|partial|overdue)" title="[A-Za-z ()]+"><span class="status-sq" aria-hidden="true"></span><span class="status-word visually-hidden">')
        self.assert_no_unlabelled_controls(text, "detail")

    def test_detail_defaults_to_the_flat_list_for_all_firms(self):
        text = self.assert_page(self.page("fees_outstanding_detail"), "detail-flat")
        self.assertIn('data-fees-columns="outstanding-flat"', text)
        self.assertIn('<th scope="col">Matter</th>', text)
        self.assertNotIn('scope="rowgroup"', text)

    def test_detail_views_and_sorts(self):
        for view in ("grouped", "summary", "flat"):
            for sort in ("firm", "group", "matter", "date", "due"):
                with self.subTest(view=view, sort=sort):
                    self.assert_page(self.page("fees_outstanding_detail", query="?view=%s&sort=%s" % (view, sort)), view)
        summary = self.html(self.page("fees_outstanding_detail", query="?view=summary"))
        self.assertIn('data-fees-columns="outstanding-summary"', summary)
        self.assertNotIn('name="memo"', summary)

    def test_unknown_view_and_sort_fall_back(self):
        self.assert_page(self.page("fees_outstanding_detail", query="?view=zzz&sort=zzz"), "fallback")

    def test_reader_has_no_tick_boxes_or_pay(self):
        text = self.html(self.page("fees_outstanding_detail", query="?view=grouped"))
        self.assertNotIn('name="memo"', text)
        self.assertNotIn(reverse("fees_payment_new"), text)
        self.assertNotIn("outstanding.js", text)

    def test_editor_ticks_go_to_the_payment_form_as_a_plain_get_form(self):
        text = self.assert_page(self.page("fees_outstanding_detail", query="?view=grouped", user=self.editor), "detail-editor")
        self.assertIn('<form method="get" action="%s" data-pay-form data-max="30">' % reverse("fees_payment_new"), text)
        self.assertRegex(text, r'<input type="checkbox" name="memo" value="\d+" data-due="[\d.]+" aria-label="Select memo ')
        self.assertIn("Pay Ticked Memos", text)
        self.assertIn("js/fees/outstanding.js", text)
        self.assert_no_unlabelled_controls(text, "detail-editor")

    def test_ticked_memos_open_the_payment_form_with_rows(self):
        a, b = self.seed["memo_a"], self.seed["memo_b"]
        self.login(self.editor)
        response = self.client.get(reverse("fees_payment_new"), {"memo": [a.pk, b.pk]})
        self.assertEqual(response.status_code, 200)

    def test_export_link_leaves_out_the_view_and_sort(self):
        text = self.html(self.page("fees_outstanding_detail", query="?view=flat&sort=due&overdue=1"))
        match = re.search(r'href="%s\?([^"]*)"' % re.escape(reverse("fees_outstanding_export")), text)
        self.assertIsNotNone(match)
        self.assertIn("overdue=1", match.group(1))
        self.assertNotIn("view=", match.group(1))
        self.assertNotIn("sort=", match.group(1))


class DashboardScreenTests(UiPageBase):
    """T8.6: KPI boxes, customise, recent matters."""

    def settings_on(self, **extra):
        FeesSettings.objects.update_or_create(profile=self.profile, defaults=dict({"dashboard_kpis_enabled": True}, **extra))

    def test_dashboard_landmarks_and_boxes(self):
        self.settings_on(statistics_enabled=True)
        text = self.assert_page(self.page("fees_dashboard"), "dashboard")
        self.assertNotIn("At a glance", text)
        self.assertNotIn('aria-label="Summary"', text)
        self.assertNotIn("Overview</h2>", text)
        self.assertNotIn('id="overview-heading"', text)
        self.assertIn('aria-label="Statistics sections"', text)
        self.assertIn('class="on" aria-current="page">Dashboard</a>', text)
        for label in ("Standard", "Explore"):
            self.assertIn(">%s</a>" % label, text)
        self.assertIn('aria-label="Dashboard boxes"', text)
        self.assertIn('aria-labelledby="recent-heading"', text)
        self.assertIn("<dt>Total Outstanding</dt>", text)
        self.assertIn("<dt>Appearances This Year</dt>", text)
        self.assertIn('<th scope="col" class="money">Memos</th>', text)
        self.assertIn("<caption>", text)

    def test_boxes_show_every_figure_when_the_saved_list_is_empty_or_unknown(self):
        self.settings_on(dashboard_kpis="")
        text = self.html(self.page("fees_dashboard"))
        self.assertIn("<dt>Billed (Last 30 Days)</dt>", text)
        self.assertIn("<dt>Memos Awaiting Payment</dt>", text)
        self.settings_on(dashboard_kpis="nonsense")
        self.assertIn("<dt>Billed (Last 30 Days)</dt>", self.html(self.page("fees_dashboard")))

    def test_boxes_follow_the_saved_selection_and_order(self):
        self.settings_on(dashboard_kpis="drafts_last30,billed_this_year")
        text = self.html(self.page("fees_dashboard"))
        boxes = text[text.index('aria-label="Dashboard boxes"'):text.index('id="recent-heading"')]
        grid = boxes[:boxes.index("</dl>")]
        self.assertLess(grid.index("Drafts (Documents), Last 30 Days"), grid.index("Billed This Year"))
        self.assertNotIn("Billed (Last 30 Days)", grid)

    def test_boxes_can_be_switched_off(self):
        FeesSettings.objects.update_or_create(profile=self.profile, defaults={"dashboard_kpis_enabled": False})
        text = self.assert_page(self.page("fees_dashboard"), "dashboard-off")
        self.assertNotIn('aria-label="Dashboard boxes"', text)
        self.assertNotIn('class="kpi-grid"', text)

    def test_statistics_switch_trims_the_tab_strip(self):
        self.settings_on(statistics_enabled=False)
        text = self.html(self.page("fees_dashboard"))
        # Statistics off: the tab strip holds the Dashboard tab only.
        self.assertIn(">Dashboard</a>", text)
        self.assertNotIn(">Standard</a>", text)
        self.assertNotIn(">Explore</a>", text)

    def test_customise_is_for_editors_only_and_posts_to_the_existing_endpoint(self):
        self.settings_on()
        reader = self.html(self.page("fees_dashboard"))
        self.assertNotIn("kpi-customise", reader)
        self.assertNotIn('name="kpi"', reader)
        editor = self.assert_page(self.page("fees_dashboard", user=self.editor), "dashboard-editor")
        self.assertIn('<details class="kpi-customise">', editor)
        self.assertIn("<summary>Customise</summary>", editor)
        self.assertIn("Customise Overview boxes", editor)
        self.assertIn('method="post" action="%s"' % reverse("fees_dashboard_kpis"), editor)
        self.assertIn('<button type="submit" class="primary">Save Boxes</button>', editor)
        self.assertEqual(editor.count('name="kpi"'), len(dashboard.KPI_IDS))
        self.assertIn("js/fees/dashboard-kpis.js", editor)

    def test_customise_groups_cover_every_kpi_and_the_order_list_has_arrows(self):
        self.settings_on(dashboard_kpis="billed_this_year,memos_last30,drafts_last30")
        editor = self.html(self.page("fees_dashboard", user=self.editor))
        for title in ("Billing", "Receipts", "Memos", "Appearances &amp; work", "Outstanding"):
            self.assertIn("<legend>%s</legend>" % title, editor)
        for kpi in dashboard.KPI_IDS:
            self.assertIn('name="kpi" value="%s"' % kpi, editor)
        self.assertIn("<h3>Order</h3>", editor)
        self.assertIn('name="order" value="billed_this_year,memos_last30,drafts_last30"', editor)
        # No JavaScript needed: the first Up and the last Down arrows are disabled, the rest submit.
        self.assertRegex(editor, r'value="billed_this_year:up"[^>]*disabled')
        self.assertRegex(editor, r'value="drafts_last30:down"[^>]*disabled')
        self.assertNotRegex(editor, r'value="memos_last30:up"[^>]*disabled')
        self.assertNotRegex(editor, r'value="memos_last30:down"[^>]*disabled')

    def test_arrow_button_post_reorders_and_reopens_the_panel(self):
        self.settings_on(dashboard_kpis="billed_this_year,memos_last30")
        self.login(self.editor)
        response = self.client.post(
            reverse("fees_dashboard_kpis"),
            {"kpi": ["billed_this_year", "memos_last30"], "order": "billed_this_year,memos_last30", "move": "memos_last30:up"},
        )
        self.assertEqual(response.status_code, 302)
        page = self.html(self.client.get(response["Location"]))
        self.assertIn('<details class="kpi-customise" open>', page)
        self.assertIn('name="order" value="memos_last30,billed_this_year"', page)

    def test_recent_matters_link_to_matter_firm_and_memo(self):
        i = self.ids()
        text = self.html(self.page("fees_dashboard"))
        self.assertIn(reverse("fees_matter_detail", kwargs={"matter_id": i["matter"]}), text)
        self.assertIn(reverse("fees_firm_detail", kwargs={"firm_id": i["firm"]}), text)

    def test_kpi_labels_are_words(self):
        self.assertEqual(dashboard.KPI_LABELS["billed_last30"], "Billed (Last 30 Days)")
        self.assertEqual(dashboard.KPI_LABELS["memos_this_month"], "Memos This Month")
        self.assertEqual(dashboard.KPI_LABELS["memos_awaiting_payment"], "Memos Awaiting Payment")


class StatisticsPageTests(UiPageBase):
    def test_standard_tab_renders_for_reader_and_editor(self):
        for user in (self.reader, self.editor):
            text = self.assert_page(self.page("fees_statistics", query="?granularity=month&fy=2026-27", user=user), "stats")
            self.assertIn('aria-label="Statistics sections"', text)
            self.assertIn('aria-current="page">Standard</a>', text)
            self.assertIn("<caption>Statistics by month for 2026-27</caption>", text)
            self.assertIn('<th scope="row">Amount Billed</th>', text)
            self.assertIn('class="money"', text)
            self.assertIn(reverse("fees_statistics_export"), text)
            self.assert_no_unlabelled_controls(text, "stats")

    def test_edit_statistics_is_not_a_statistics_tab(self):
        for user in (self.reader, self.editor):
            text = self.html(self.page("fees_statistics", user=user))
            self.assertNotIn(">Edit statistics</a>", text)
            self.assertNotIn(">Adjustments</a>", text)
            self.assertNotIn("tab=edit", text)
        # An old link to the edit tab shows the standard tab.
        old = self.html(self.page("fees_statistics", query="?tab=edit&fy=2026-27", user=self.editor))
        self.assertNotIn('class="ledger-table adjust-grid"', old)
        self.assertIn('aria-current="page">Standard</a>', old)

    def test_edit_grid_in_settings_is_a_form_grid_for_editors_and_read_only_for_readers(self):
        editor = self.assert_page(self.page("fees_settings", query="?fy=2026-27", user=self.editor), "edit")
        self.assertEqual(editor.count('id="adj-'), 12)
        self.assertIn('action="%s"' % reverse("fees_settings_statistics_grid"), editor)
        self.assertIn('name="return_to" value="settings"', editor)
        self.assertIn('aria-label="Working days, April"', editor)
        self.assertIn('aria-label="Replace billed, March"', editor)
        self.assertLess(editor.index(">April</th>"), editor.index(">March</th>"))
        self.assert_no_unlabelled_controls(editor, "edit")
        reader = self.assert_page(self.page("fees_settings", query="?fy=2026-27"), "edit-reader")
        self.assertNotIn("<form id=\"adj-", reader)
        self.assertNotIn('name="working_days"', reader)
        self.assertIn("Only an Editor can change them", reader)

    def test_edit_form_saves_a_month_and_goes_back_to_settings(self):
        self.login(self.editor)
        response = self.client.post(
            reverse("fees_settings_statistics_grid"),
            {"return_to": "settings", "fy": "2026-27", "month": "4", "working_days": "21", "override_billed": "5000"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("fees_settings") + "?fy=2026-27#settings-years")
        text = self.html(self.client.get(response["Location"]))
        self.assertIn('name="working_days" value="21"', text)
        self.assertIn('value="5000', text)
        self.assertIn("Adjustments saved.", text)

    def test_edit_form_error_is_a_message_not_json(self):
        self.login(self.editor)
        response = self.client.post(
            reverse("fees_settings_statistics_grid"), {"return_to": "settings", "fy": "2026-27", "month": "4", "working_days": "x"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("Working days must be a whole number.", self.html(self.client.get(response["Location"])))

    def test_explore_tab_shows_form_table_and_off_by_default_chart(self):
        text = self.assert_page(self.page("fees_statistics", query="?tab=explore"), "explore")
        for name in ("measure", "row_dim", "col_dim", "firm_id", "from_fy", "to_fy"):
            self.assertIn('name="%s"' % name, text)
        self.assertIn('<table class="ledger-table pivot-table', text)
        self.assertIn("<caption>Amount Billed by financial year</caption>", text)
        self.assertIn('data-chart-tools hidden', text)
        self.assertIn('data-chart-figure hidden', text)
        self.assertNotIn("data-chart-on checked", text)
        self.assertIn('id="pivot-data"', text)
        self.assertIn("js/pivot-chart.js", text)
        self.assert_no_unlabelled_controls(text, "explore")

    def test_explore_pivot_follows_the_query(self):
        text = self.html(self.page("fees_statistics", query="?tab=explore&measure=memos&row_dim=firm&col_dim=none"))
        self.assertIn("<caption>Memos (count) by firm</caption>", text)
        self.assertIn(escape(self.seed["firm_a"].name), text)  # "Alpha & Co" is shown as "Alpha &amp; Co"

    def test_explore_explains_a_pivot_that_cannot_be_made(self):
        text = self.assert_page(self.page("fees_statistics", query="?tab=explore&measure=feesPerWeek&row_dim=firm"), "per-week")
        self.assertIn('role="alert"', text)
        self.assertIn("Per-week measures need Month, Quarter or Financial Year rows.", text)
        self.assertNotIn("js/pivot-chart.js", text)

    def test_saved_views_are_listed_for_all_and_managed_by_editors(self):
        editor = self.assert_page(self.page("fees_statistics", query="?tab=explore", user=self.editor), "views-editor")
        view = SavedView.objects.get(profile=self.profile)
        self.assertIn(view.name, editor)
        self.assertIn(reverse("fees_statistics_view_delete", kwargs={"view_id": view.pk}), editor)
        self.assertIn('action="%s"' % reverse("fees_statistics_views"), editor)
        self.assertIn('aria-label="Save this pivot as a view"', editor)
        reader = self.assert_page(self.page("fees_statistics", query="?tab=explore"), "views-reader")
        self.assertIn(view.name, reader)
        self.assertNotIn(reverse("fees_statistics_view_delete", kwargs={"view_id": view.pk}), reader)
        self.assertNotIn('name="name"', reader)

    def test_saving_and_deleting_a_view_from_the_page(self):
        self.login(self.editor)
        saved = self.client.post(
            reverse("fees_statistics_views"),
            {"return_to": "statistics", "name": "Page view", "measure": "memos", "row_dim": "firm", "col_dim": "none"},
        )
        self.assertEqual(saved.status_code, 302)
        self.assertIn("tab=explore", saved["Location"])
        view = SavedView.objects.get(profile=self.profile, name="Page view")
        self.assertIn("View saved.", self.html(self.client.get(saved["Location"])))
        deleted = self.client.post(
            reverse("fees_statistics_view_delete", kwargs={"view_id": view.pk}), {"return_to": "statistics"}
        )
        self.assertEqual(deleted.status_code, 302)
        self.assertFalse(SavedView.objects.filter(pk=view.pk).exists())

    def test_a_blank_view_name_is_a_message(self):
        self.login(self.editor)
        response = self.client.post(
            reverse("fees_statistics_views"), {"return_to": "statistics", "name": " ", "measure": "billed", "row_dim": "month", "col_dim": "none"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(SavedView.objects.filter(profile=self.profile).count(), 1)

    def test_page_still_answers_when_statistics_is_switched_off(self):
        FeesSettings.objects.update_or_create(profile=self.profile, defaults={"statistics_enabled": False})
        text = self.assert_page(self.page("fees_statistics"), "off")
        self.assertIn("Statistics is switched off in Settings.", text)
        self.assertNotIn("still correct", text)
        self.assertNotIn("<caption>", text)
        nav = text[text.index('<nav class="program-nav"'):text.index("</nav>")]
        self.assertNotIn(">Statistics</a>", nav)


class StatusMarkerSettingTests(UiPageBase):
    """Owner decision 4: Settings > Show status markers hides the coloured square everywhere; the words stay."""

    MARKER = 'class="status-sq"'

    def set_dots(self, value):
        FeesSettings.objects.update_or_create(profile=self.profile, defaults={"show_status_dots": value})

    def marker_pages(self):
        """Pages that render a status marker when the setting is on: (label, url name, kwargs, query)."""
        i = self.ids()
        return [
            ("memos", "fees_memos", {}, ""),
            ("drafts", "fees_memo_drafts", {}, ""),
            ("memo detail", "fees_memo_detail", {"memo_id": i["memo"]}, ""),
            ("outstanding detail", "fees_outstanding_detail", {}, ""),
            ("outstanding detail by firm", "fees_outstanding_detail", {}, "?firm=%d" % i["firm"]),
        ]

    def other_pages(self):
        """Pages that show a marker only when the setting is on (or not at all); they are checked with it off."""
        i = self.ids()
        return [
            ("outstanding", "fees_outstanding", {}, ""),
            ("feebook", "fees_feebook", {}, ""),
            ("feebook unaccounted", "fees_feebook", {}, "?unaccounted=1"),
            ("firms", "fees_firms", {}, ""),
            ("firm", "fees_firm_detail", {"firm_id": i["firm"]}, ""),
            ("matter", "fees_matter_detail", {"matter_id": i["matter"]}, ""),
            ("dashboard", "fees_dashboard", {}, ""),
        ]

    def test_default_is_on_and_markers_show(self):
        for label, name, kwargs, query in self.marker_pages():
            text = self.assert_page(self.page(name, kwargs, query), label)
            self.assertIn(self.MARKER, text, label)

    def test_on_shows_markers_with_words(self):
        self.set_dots(True)
        for label, name, kwargs, query in self.marker_pages():
            self.assertIn(self.MARKER, self.html(self.page(name, kwargs, query)), label)

    def test_off_hides_every_marker_on_every_page(self):
        self.set_dots(False)
        for label, name, kwargs, query in self.marker_pages() + self.other_pages():
            text = self.assert_page(self.page(name, kwargs, query), label)
            self.assertNotIn("status-sq", text, label)

    def test_off_keeps_the_status_words_and_columns(self):
        self.set_dots(False)
        text = self.html(self.page("fees_memos"))
        self.assertRegex(text, r'<span class="status status-[a-z-]+"><span class="status-word">[A-Z][a-z]+')
        self.assertIn('<th scope="col" data-col-fixed>Status</th>', text)
        drafts = self.html(self.page("fees_memo_drafts"))
        self.assertIn('<span class="status status-draft"><span class="status-word">Draft</span></span>', drafts)
        detail = self.html(self.page("fees_outstanding_detail"))
        self.assertRegex(detail, r'<span class="status status-(unpaid|partial|overdue)"><span class="status-word">(Unpaid|Partly paid)')
        feebook = self.html(self.page("fees_feebook", query="?unaccounted=1"))
        self.assertIn("<td>Unaccounted</td>", feebook)

    def test_off_applies_to_editors_too(self):
        self.set_dots(False)
        text = self.html(self.page("fees_memos", user=self.editor))
        self.assertNotIn("status-sq", text)

    def test_turning_it_back_on_restores_the_markers(self):
        self.set_dots(False)
        self.assertNotIn("status-sq", self.html(self.page("fees_memos")))
        self.set_dots(True)
        self.assertIn(self.MARKER, self.html(self.page("fees_memos")))

    def test_hiding_adds_no_queries(self):
        counts = {}
        for value in (True, False):
            self.set_dots(value)
            self.login(self.reader)
            with CaptureQueriesContext(connection) as ctx:
                self.client.get(reverse("fees_memos"))
            counts[value] = len(ctx)
        self.assertLessEqual(counts[False], counts[True])
