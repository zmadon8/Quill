"""Fee Register user interface (Phase 8): the page shell, and a base class later UI tests reuse.

``UiPageBase`` renders a page as a signed-in user and checks the things every page must have: status 200, the
landmarks (header, main, program navigation), the skip link, the stylesheet, a single page heading, and no em dash.
Later screens subclass it and add their own checks on top of ``assert_page``.
"""
import re

from django.test import override_settings
from django.urls import reverse

from fees.models import FeesSettings
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
