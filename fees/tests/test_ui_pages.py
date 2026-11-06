"""Fee Register user interface (Phase 8): the page shell, and a base class later UI tests reuse.

``UiPageBase`` renders a page as a signed-in user and checks the things every page must have: status 200, the
landmarks (header, main, program navigation), the skip link, the stylesheet, a single page heading, and no em dash.
Later screens subclass it and add their own checks on top of ``assert_page``.
"""
import re

from django.test import override_settings
from django.urls import reverse

from fees.models import FeesSettings, SavedView
from fees.tests.test_views_read import SeededViewsBase

EM_DASH = "\u2014"
NAV_LABELS = ["Dashboard", "Statistics", "Memos", "Firms", "Feebook", "Outstanding", "Settings"]


@override_settings(SECURE_SSL_REDIRECT=False)
class UiPageBase(SeededViewsBase):
    """Seeded profile plus helpers that render a page and check the parts every page shares."""

    def page(self, name, kwargs=None, query="", user=None):
        """GET a page as ``user`` (the Reader by default) and return the response."""
        self.login(user or self.reader)
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
        self.assertGreaterEqual(len(re.findall(r"<h1[ >]", text)), 1, label)
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
                self.assert_page(self.page(name, query=query), name)

    def test_search_and_filter_inputs_are_labelled(self):
        for name, query in (("fees_memos", ""), ("fees_search_page", "?q=alpha")):
            with self.subTest(page=name):
                self.assert_no_unlabelled_controls(self.html(self.page(name, query=query)), name)

    def test_program_nav_order_and_current_page(self):
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
        self.assertIn(">Dashboard</a>", nav)

    def test_program_name_links_to_the_dashboard(self):
        text = self.html(self.page("fees_firms"))
        self.assertIn('<span class="brand"><a href="%s">' % reverse("fees_dashboard"), text)

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
        text = self.assert_page(self.page("fees_backup_clear", user=self.editor), "clear")
        self.assertIn('class="confirm warning-box"', text)
        self.assertIn('name="confirmation"', text)
        self.assertIn("Cancel", text)

    def test_busy_page_is_a_complete_document(self):
        from django.template.loader import render_to_string

        text = render_to_string("fees/busy.html")
        self.assertIn('<html lang="en">', text)
        self.assertIn('<main id="main">', text)
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
        self.assert_no_unlabelled_controls(text, "memos")

    def test_reader_has_no_new_memo_button(self):
        text = self.html(self.page("fees_memos"))
        self.assertNotIn(reverse("fees_memo_new"), text)
        editor = self.html(self.page("fees_memos", user=self.editor))
        self.assertIn('href="%s"' % reverse("fees_memo_new"), editor)

    def test_status_is_words_as_well_as_a_marker(self):
        text = self.html(self.page("fees_memos"))
        self.assertRegex(text, r'<span class="status status-[a-z-]+"><span class="status-sq" aria-hidden="true"></span>[A-Z]')

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
        self.assertIn('<th scope="col">Firm</th>', text)
        self.assertIn('aria-label="Show firms"', text)
        self.assertNotIn(reverse("fees_firm_new"), text)
        editor = self.html(self.page("fees_firms", user=self.editor))
        self.assertIn('href="%s"' % reverse("fees_firm_new"), editor)

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
        self.assertNotIn(reverse("fees_matter_archive", kwargs={"matter_id": i["matter"]}), text)
        editor = self.assert_page(self.page("fees_matter_detail", {"matter_id": i["matter"]}, user=self.editor), "matter-editor")
        self.assertIn(reverse("fees_matter_archive", kwargs={"matter_id": i["matter"]}), editor)
        self.assertIn("Edit or move matter", editor)

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

    def test_feebook_unaccounted_has_words_and_a_marker(self):
        text = self.html(self.page("fees_feebook", query="?unaccounted=1"))
        self.assertIn('status-unaccounted"><span class="status-sq" aria-hidden="true"></span>Unaccounted', text)

    def test_feebook_hides_edit_controls_from_a_reader(self):
        text = self.html(self.page("fees_feebook"))
        self.assertNotIn(reverse("fees_payment_new"), text)
        self.assertNotIn("/assign/", text)
        self.assertNotIn(">Attach<", text)

    def test_feebook_editor_can_edit_and_attach(self):
        text = self.assert_page(self.page("fees_feebook", user=self.editor), "feebook-editor")
        self.assertIn(reverse("fees_payment_new"), text)
        self.assertIn("/assign/", text)
        self.assertIn('aria-label="Edit payment of ', text)
        self.assert_no_unlabelled_controls(text, "feebook-editor")

    def test_payment_form_works_without_script(self):
        text = self.assert_page(self.page("fees_payment_new", user=self.editor), "payment")
        self.assertIn('method="post" action="%s"' % reverse("fees_payment_new"), text)
        for name in ("amount", "date_of_payment", "tds_rate", "auto_tds", "tds_amount", "payee", "bank_account_id",
                     "alloc_memo_0", "alloc_amount_0", "alloc_tds_0", "alloc_memo_4"):
            self.assertIn('name="%s"' % name, text)
        self.assertIn('<button type="submit" class="primary">Save</button>', text)
        self.assertIn("js/fees/payment-form.js", text)
        # Script-made parts stay hidden until the script shows them.
        self.assertIn("data-payee-chips hidden", text)
        self.assertIn("data-remaining role=\"status\" aria-live=\"polite\" hidden", text)
        self.assertIn('data-payees-url="%s"' % reverse("fees_payment_payees"), text)
        self.assertIn('class="crumb-row"', text)
        self.assert_no_unlabelled_controls(text, "payment")

    def test_payment_form_for_a_memo_prefills_the_row_and_the_payee_matters(self):
        i = self.ids()
        text = self.assert_page(self.page("fees_payment_new", query="?memo=%d" % i["memo"], user=self.editor), "payment-memo")
        memo = self.seed["memo_a"]
        memo.refresh_from_db()
        self.assertIn('name="alloc_memo_0" value="%s"' % memo.memo_number, text)
        self.assertIn('data-matters="%d"' % i["matter"], text)
        self.assertIn("?memo=%d" % i["memo"], text)
        self.assertIn(reverse("fees_memo_detail", kwargs={"memo_id": i["memo"]}), text)

    def test_payment_form_for_several_memos(self):
        a, b = self.seed["memo_a"], self.seed["memo_b"]
        a.refresh_from_db()
        b.refresh_from_db()
        query = "?memo=%d&memo=%d" % (a.pk, b.pk)
        text = self.assert_page(self.page("fees_payment_new", query=query, user=self.editor), "payment-two")
        self.assertIn('name="alloc_memo_0" value="%s"' % a.memo_number, text)
        self.assertIn('name="alloc_memo_1" value="%s"' % b.memo_number, text)
        self.assertIn("?memo=%d&amp;memo=%d" % (a.pk, b.pk), text)
        self.assertIn('data-matters="%d"' % self.ids()["matter"], text)

    def test_several_memos_are_capped_at_the_rows_and_junk_is_ignored(self):
        a = self.seed["memo_a"]
        text = self.assert_page(self.page("fees_payment_new", query="?memo=%d,x,%d" % (a.pk, a.pk), user=self.editor), "payment-dup")
        self.assertIn('name="alloc_memo_0"', text)

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

    def test_reader_cannot_open_the_payment_form(self):
        self.assertEqual(self.page("fees_payment_new").status_code, 403)

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
        self.assertIn('<th scope="row">Total</th>', text)
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
        self.assertIn('class="crumb-row"', text)
        self.assertRegex(text, r'<span class="status status-(unpaid|partial|overdue)"><span class="status-sq" aria-hidden="true"></span>')
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
        self.assertIn('<form method="get" action="%s" data-pay-form>' % reverse("fees_payment_new"), text)
        self.assertRegex(text, r'<input type="checkbox" name="memo" value="\d+" data-due="[\d.]+" aria-label="Select memo ')
        self.assertIn("Pay ticked memos", text)
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
        self.assertIn('aria-labelledby="summary-heading"', text)
        self.assertIn('aria-labelledby="overview-heading"', text)
        self.assertIn('aria-labelledby="recent-heading"', text)
        self.assertIn('<div class="kpi"><dt><a href="%s">Total outstanding</a></dt>' % reverse("fees_outstanding"), text)
        self.assertIn("Appearances this year", text)
        self.assertIn('<th scope="col" class="money">Memos</th>', text)
        self.assertIn("<caption>", text)

    def test_overview_shows_every_figure_when_the_saved_list_is_empty_or_unknown(self):
        self.settings_on(dashboard_kpis="")
        text = self.html(self.page("fees_dashboard"))
        self.assertIn("Billed, last 30 days", text)
        self.assertIn("Memos awaiting payment", text)
        self.settings_on(dashboard_kpis="nonsense")
        self.assertIn("Billed, last 30 days", self.html(self.page("fees_dashboard")))

    def test_overview_shows_only_the_chosen_figures_in_order(self):
        self.settings_on(dashboard_kpis="billed_this_year,drafts_last30")
        text = self.html(self.page("fees_dashboard"))
        overview = text[text.index('id="overview-heading"'):text.index('id="recent-heading"')]
        self.assertLess(overview.index("Billed, this year"), overview.index("Drafts, last 30 days"))
        self.assertNotIn("Billed, last 30 days", overview)

    def test_overview_can_be_switched_off(self):
        FeesSettings.objects.update_or_create(profile=self.profile, defaults={"dashboard_kpis_enabled": False})
        text = self.assert_page(self.page("fees_dashboard"), "dashboard-off")
        self.assertNotIn("overview-heading", text)
        self.assertIn("summary-heading", text)

    def test_appearances_box_follows_the_statistics_switch(self):
        self.settings_on(statistics_enabled=False)
        self.assertNotIn("Appearances this year", self.html(self.page("fees_dashboard")))

    def test_customise_is_for_editors_only_and_posts_to_the_existing_endpoint(self):
        self.settings_on()
        reader = self.html(self.page("fees_dashboard"))
        self.assertNotIn("kpi-customise", reader)
        self.assertNotIn('name="kpi"', reader)
        editor = self.assert_page(self.page("fees_dashboard", user=self.editor), "dashboard-editor")
        self.assertIn('<details class="kpi-customise">', editor)
        self.assertIn('method="post" action="%s"' % reverse("fees_dashboard_kpis"), editor)
        self.assertIn('<button type="submit" class="primary">Save figures</button>', editor)
        self.assertGreater(editor.count('name="kpi"'), 5)

    def test_recent_matters_link_to_matter_firm_and_memo(self):
        i = self.ids()
        text = self.html(self.page("fees_dashboard"))
        self.assertIn(reverse("fees_matter_detail", kwargs={"matter_id": i["matter"]}), text)
        self.assertIn(reverse("fees_firm_detail", kwargs={"firm_id": i["firm"]}), text)

    def test_kpi_labels_are_words(self):
        from fees.views_dashboard import kpi_label

        self.assertEqual(kpi_label("billed_last30"), "Billed, last 30 days")
        self.assertEqual(kpi_label("memos_this_month"), "Memos, this month")
        self.assertEqual(kpi_label("memos_awaiting_payment"), "Memos awaiting payment")


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

    def test_tab_names_differ_by_role(self):
        self.assertIn(">Adjustments</a>", self.html(self.page("fees_statistics")))
        self.assertIn(">Edit statistics</a>", self.html(self.page("fees_statistics", user=self.editor)))

    def test_edit_tab_is_a_form_grid_for_editors_and_read_only_for_readers(self):
        editor = self.assert_page(self.page("fees_statistics", query="?tab=edit&fy=2026-27", user=self.editor), "edit")
        self.assertEqual(editor.count('id="adj-'), 12)
        self.assertIn('action="%s"' % reverse("fees_settings_statistics_grid"), editor)
        self.assertIn('name="return_to" value="statistics"', editor)
        self.assertIn('aria-label="Working days, April"', editor)
        self.assertIn('aria-label="Replace billed, March"', editor)
        self.assertLess(editor.index(">April</th>"), editor.index(">March</th>"))
        self.assert_no_unlabelled_controls(editor, "edit")
        reader = self.assert_page(self.page("fees_statistics", query="?tab=edit&fy=2026-27"), "edit-reader")
        self.assertNotIn("<form id=\"adj-", reader)
        self.assertNotIn('name="working_days"', reader)
        self.assertIn("Only an Editor can change them", reader)

    def test_edit_form_saves_a_month_and_goes_back_to_the_grid(self):
        self.login(self.editor)
        response = self.client.post(
            reverse("fees_settings_statistics_grid"),
            {"return_to": "statistics", "fy": "2026-27", "month": "4", "working_days": "21", "override_billed": "5000"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("fees_statistics") + "?tab=edit&fy=2026-27")
        text = self.html(self.client.get(response["Location"]))
        self.assertIn('name="working_days" value="21"', text)
        self.assertIn('value="5000', text)
        self.assertIn("Adjustments saved.", text)

    def test_edit_form_error_is_a_message_not_json(self):
        self.login(self.editor)
        response = self.client.post(
            reverse("fees_settings_statistics_grid"), {"return_to": "statistics", "fy": "2026-27", "month": "4", "working_days": "x"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("Working days must be a whole number.", self.html(self.client.get(response["Location"])))

    def test_explore_tab_shows_form_table_and_off_by_default_chart(self):
        text = self.assert_page(self.page("fees_statistics", query="?tab=explore"), "explore")
        for name in ("measure", "row_dim", "col_dim", "firm_id", "from_fy", "to_fy"):
            self.assertIn('name="%s"' % name, text)
        self.assertIn('<table class="ledger-table pivot-table"', text)
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
        self.assertIn(self.seed["firm_a"].name, text)

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
        self.assertIn("Statistics is switched off in Settings", text)
        nav = text[text.index('<nav class="program-nav"'):text.index("</nav>")]
        self.assertNotIn(">Statistics</a>", nav)
