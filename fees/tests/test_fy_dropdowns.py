"""Financial year drop-downs and the Items per page setting (owner round)."""
import datetime
import re
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from accounts.models import Profile
from accounts.suite import KEY_FEES
from fees.models import FeesSettings, Memo, Payment
from fees.services import filter_options, fy_options, memo_lists, payments
from fees.services.financial_year import current_financial_year
from fees.tests.test_views_write import WriteBase

ALL_YEARS = {"fy": ""}  # an explicit blank year is All years; the seeded memos span two financial years
NOW = datetime.date(2026, 8, 1)  # the financial year 2026-27


class FyOptionsServiceTests(TestCase):
    def setUp(self):
        self.profile = Profile.objects.create(program=KEY_FEES, name="Fy-Options")

    def test_no_data_offers_only_the_current_year(self):
        self.assertEqual(fy_options.financial_year_options(self.profile, now=NOW), ["2026-27"])

    def test_start_year_options_reach_ten_years_back_without_data(self):
        options = fy_options.start_year_options(self.profile, now=NOW)
        self.assertEqual(options[0], "2026-27")
        self.assertEqual(options[-1], "2016-17")
        self.assertEqual(len(options), 11)

    def test_saved_values_outside_the_range_are_kept(self):
        options = fy_options.start_year_options(self.profile, selected=("2030-31", "2010-11", "bogus"), now=NOW)
        self.assertEqual(options[0], "2030-31")
        self.assertEqual(options[-1], "2010-11")
        self.assertNotIn("bogus", options)

    def test_label_check(self):
        self.assertTrue(fy_options.is_financial_year_label("2026-27"))
        self.assertTrue(fy_options.is_financial_year_label("2099-00"))
        for bad in ("", None, "2026", "2026-28", "26-27", "2026-27x"):
            self.assertFalse(fy_options.is_financial_year_label(bad), bad)


class FyDropdownPageTests(WriteBase):
    def data_years(self):
        labels = Memo.objects.filter(profile=self.profile, is_draft=False).values_list("financial_year", flat=True)
        return {label for label in labels if fy_options.is_financial_year_label(label)}

    def select_for(self, html, name):
        match = re.search(r'<select name="%s"[^>]*>(.*?)</select>' % name, html, re.S)
        self.assertIsNotNone(match, name)
        return match.group(1)

    def values(self, select_html):
        return re.findall(r'<option value="([^"]*)"', select_html)

    def test_memos_drafts_and_feebook_use_a_drop_down_newest_first(self):
        FeesSettings.objects.update_or_create(
            profile=self.profile, defaults={"memos_start_year": "2000-01", "feebook_start_year": "2000-01"}
        )
        for name in ("fees_memos", "fees_memo_drafts", "fees_feebook"):
            # The page opens on the current year now, so ask for every year to see the whole list.
            html = self.client.get(reverse(name), {"fy": ""}).content.decode()
            self.assertNotRegex(html, r'<input[^>]*name="fy"', name)
            values = self.values(self.select_for(html, "fy"))
            self.assertEqual(values[0], "", name)  # All years
            self.assertIn("All Years", html)
            years = values[1:]
            self.assertEqual(years, sorted(years, reverse=True), name)
            if name == "fees_memos":  # the years that have memos; the Drafts and Feebook lists have their own rows
                for year in self.data_years():
                    self.assertIn(year, years, name)

    def test_the_pages_open_on_the_current_year_and_all_years_sticks_when_chosen(self):
        FeesSettings.objects.update_or_create(
            profile=self.profile, defaults={"memos_start_year": "2000-01", "feebook_start_year": "2000-01"}
        )
        current = current_financial_year()
        for name in ("fees_memos", "fees_memo_drafts", "fees_feebook"):
            html = self.client.get(reverse(name)).content.decode()
            self.assertIn('<option value="%s" selected>%s</option>' % (current, current), self.select_for(html, "fy"), name)
            chosen = self.client.get(reverse(name), {"fy": ""}).content.decode()
            self.assertRegex(self.select_for(chosen, "fy"), r'<option value="">All Years</option>', name)
            self.assertNotRegex(self.select_for(chosen, "fy"), r'value="[^"]+" selected', name)

    def test_the_export_link_carries_the_year_the_page_shows(self):
        html = self.client.get(reverse("fees_memos")).content.decode()
        self.assertIn("fy=%s" % current_financial_year(), html)
        self.assertEqual(self.client.get(reverse("fees_memos"), {"fy": ""}).context["filters"].get("financial_year"), None)

    def test_the_chosen_year_stays_selected_even_when_it_has_no_data(self):
        html = self.client.get(reverse("fees_memos"), {"fy": "2015-16"}).content.decode()
        self.assertIn('<option value="2015-16" selected>2015-16</option>', html)

    def test_years_before_the_start_year_are_not_offered(self):
        FeesSettings.objects.update_or_create(profile=self.profile, defaults={"memos_start_year": current_financial_year()})
        html = self.client.get(reverse("fees_memos")).content.decode()
        years = self.values(self.select_for(html, "fy"))[1:]
        self.assertTrue(years)
        for year in years:
            self.assertGreaterEqual(year, current_financial_year())

    def test_filtering_by_a_year_still_uses_the_fy_parameter(self):
        year = sorted(self.data_years())[0]
        response = self.client.get(reverse("fees_memos"), {"fy": year})
        self.assertEqual(response.status_code, 200)
        for item in response.context["items"]:
            self.assertEqual(item["financial_year"], year)

    def test_statistics_uses_drop_downs(self):
        for query in ("?tab=standard", "?tab=explore"):
            html = self.client.get(reverse("fees_statistics") + query).content.decode()
            self.assertNotRegex(html, r'<input(?![^>]*type="hidden")[^>]*name="(fy|from_fy|to_fy)"', query)
        standard = self.client.get(reverse("fees_statistics") + "?tab=standard&fy=2026-27").content.decode()
        self.assertIn('<option value="2026-27" selected>2026-27</option>', standard)
        explore = self.client.get(reverse("fees_statistics") + "?tab=explore&from_fy=2025-26").content.decode()
        self.assertIn("Earliest", explore)
        self.assertIn("Latest", explore)
        self.assertIn('<option value="2025-26" selected>2025-26</option>', self.select_for(explore, "from_fy"))
        self.assertTrue(self.select_for(explore, "to_fy"))

    def test_explore_starts_from_the_present_financial_year(self):
        from fees.services.financial_year import current_financial_year

        now = current_financial_year()
        explore = self.client.get(reverse("fees_statistics") + "?tab=explore").content.decode()
        self.assertIn('<option value="%s" selected>%s</option>' % (now, now), self.select_for(explore, "from_fy"))
        # Choosing Earliest (an empty value) is kept: no lower limit.
        earliest = self.client.get(reverse("fees_statistics") + "?tab=explore&from_fy=").content.decode()
        self.assertNotIn(" selected>", self.select_for(earliest, "from_fy"))

    def test_a_saved_view_with_earliest_keeps_earliest(self):
        from fees.views_statistics import saved_view_query

        query = saved_view_query({"measure": "billed", "row_dim": "firm", "col_dim": "none", "from_fy": None})
        self.assertIn("from_fy=&", query + "&")

    def test_settings_start_years_are_drop_downs(self):
        html = self.client.get(reverse("fees_settings")).content.decode()
        for name in ("initial_financial_year", "memos_start_year", "feebook_start_year"):
            self.assertNotRegex(html, r'<input[^>]*name="%s"' % name, name)
            select = self.select_for(html, name)
            self.assertIn('<option value="2026-27" selected>2026-27</option>', select, name)
            years = self.values(select)
            self.assertEqual(years, sorted(years, reverse=True), name)

    def test_a_start_year_chosen_from_the_drop_down_is_saved(self):
        self.post("fees_settings", {"memos_start_year": "2024-25"})
        self.assertEqual(FeesSettings.objects.get(profile=self.profile).memos_start_year, "2024-25")
        html = self.client.get(reverse("fees_settings")).content.decode()
        self.assertIn('<option value="2024-25" selected>2024-25</option>', self.select_for(html, "memos_start_year"))


class ItemsPerPageTests(WriteBase):
    def set_per_page(self, value):
        FeesSettings.objects.update_or_create(profile=self.profile, defaults={"items_per_page": value})

    def memo_count(self, drafts=False):
        return Memo.objects.filter(profile=self.profile, is_draft=drafts).count()

    def test_page_size_for(self):
        self.assertIsNone(memo_lists.page_size_for(0))
        self.assertIsNone(memo_lists.page_size_for(None))
        self.assertIsNone(memo_lists.page_size_for(-5))
        self.assertEqual(memo_lists.page_size_for(25), 25)
        self.assertEqual(memo_lists.page_size_for(5000), 1000)

    def test_the_default_is_fifty(self):
        self.assertEqual(FeesSettings._meta.get_field("items_per_page").get_default(), 50)

    def test_memos_break_into_pages_of_the_chosen_size(self):
        for _ in range(3):
            self.new_memo()
        total = self.memo_count()
        self.assertGreaterEqual(total, 4)
        self.set_per_page(2)
        response = self.client.get(reverse("fees_memos"), ALL_YEARS)
        self.assertEqual(len(response.context["items"]), 2)
        self.assertEqual(response.context["meta"]["total_pages"], (total + 1) // 2)
        self.assertEqual(response.context["totals"]["count"], total)  # footer covers the whole filtered set
        self.assertContains(response, "Page 1 of %d" % ((total + 1) // 2))
        second = self.client.get(reverse("fees_memos"), {"page": 2, "fy": ""})
        self.assertEqual(second.context["meta"]["page"], 2)

    def test_all_shows_everything_on_one_page(self):
        for _ in range(3):
            self.new_memo()
        self.set_per_page(0)
        response = self.client.get(reverse("fees_memos"), ALL_YEARS)
        self.assertEqual(len(response.context["items"]), self.memo_count())
        self.assertEqual(response.context["meta"]["total_pages"], 1)
        self.assertNotContains(response, 'aria-label="Pages"')

    def test_totals_are_the_same_whatever_the_page_size(self):
        for _ in range(2):
            self.new_memo()
        everything = self.client.get(reverse("fees_memos"), ALL_YEARS).context["totals"]
        self.set_per_page(1)
        paged = self.client.get(reverse("fees_memos"), ALL_YEARS).context["totals"]
        self.assertEqual(everything, paged)

    def test_drafts_use_the_setting(self):
        for _ in range(2):
            self.post("fees_memo_new", {
                "matter_id": str(self.seed["matter_1"].pk), "date": "", "addressee_line1": "Draft", "num_appearances": "1",
                "fees_per_appearance": "1000", "action": "draft",
            })
        drafts = self.memo_count(drafts=True)
        self.assertGreaterEqual(drafts, 2)
        self.set_per_page(1)
        response = self.client.get(reverse("fees_memo_drafts"), ALL_YEARS)
        self.assertEqual(len(response.context["items"]), 1)
        self.assertEqual(response.context["totals"]["count"], drafts)

    def test_feebook_uses_the_setting(self):
        everything = self.client.get(reverse("fees_feebook")).context
        total = everything["totals"]["count"]
        self.assertGreaterEqual(total, 2)
        self.set_per_page(1)
        response = self.client.get(reverse("fees_feebook"))
        self.assertEqual(len(response.context["entries"]), 1)
        self.assertEqual(response.context["meta"]["total_pages"], total)
        self.assertEqual(response.context["totals"], everything["totals"])
        self.set_per_page(0)
        self.assertEqual(len(self.client.get(reverse("fees_feebook")).context["entries"]), total)

    def test_the_setting_is_saved_from_settings_and_shows_all_for_zero(self):
        self.post("fees_settings", {"items_per_page": "All"})
        self.assertEqual(FeesSettings.objects.get(profile=self.profile).items_per_page, 0)
        html = self.client.get(reverse("fees_settings")).content.decode()
        self.assertIn('name="items_per_page"', html)
        self.assertRegex(html, r'name="items_per_page"[^>]*value="All"')
        self.post("fees_settings", {"items_per_page": "25"})
        self.assertEqual(FeesSettings.objects.get(profile=self.profile).items_per_page, 25)
        html = self.client.get(reverse("fees_settings")).content.decode()
        self.assertRegex(html, r'name="items_per_page"[^>]*value="25"')

    def test_a_bad_value_is_refused_and_nothing_changes(self):
        response = self.post("fees_settings", {"items_per_page": "1001"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(FeesSettings.objects.get(profile=self.profile).items_per_page, 50)
        self.assertEqual(self.post("fees_settings", {"items_per_page": "lots"}).status_code, 422)


class DefaultYearTests(WriteBase):
    """With no ``fy`` in the link a list opens on the current year, or the newest year that has rows, or All years."""

    CURRENT = "2026-27"

    def setUp(self):
        super().setUp()
        Payment.objects.filter(profile=self.profile).delete()
        Memo.objects.filter(profile=self.profile).delete()

    def open(self, name, query=None):
        with mock.patch("fees.views_memos.current_financial_year", return_value=self.CURRENT), mock.patch(
            "fees.views_feebook.current_financial_year", return_value=self.CURRENT
        ):
            return self.client.get(reverse(name), query or {})

    def pay(self, day):
        payments.add_unaccounted_payment(self.profile, {"amount": 700, "date_of_payment": day, "payee": "Payer"})

    def test_default_year_rule(self):
        self.assertEqual(filter_options.default_year({"2026-27", "2024-25"}, "2026-27"), "2026-27")
        self.assertEqual(filter_options.default_year({"2025-26", "2024-25"}, "2026-27"), "2025-26")
        self.assertIsNone(filter_options.default_year(set(), "2026-27"))

    def test_memos_open_on_the_current_year_when_it_has_rows(self):
        self.new_memo(date="2026-07-15")
        self.new_memo(date="2025-05-02")
        response = self.open("fees_memos")
        self.assertEqual(response.context["filters"]["financial_year"], "2026-27")
        self.assertEqual(len(response.context["items"]), 1)

    def test_memos_open_on_the_newest_year_with_rows_when_the_current_year_is_empty(self):
        self.new_memo(date="2025-05-02")
        self.new_memo(date="2023-05-02")
        response = self.open("fees_memos")
        self.assertEqual(response.context["filters"]["financial_year"], "2025-26")
        self.assertEqual(len(response.context["items"]), 1)
        self.assertEqual(len(response.context["firm_choices"]), 1)
        self.assertIn('<option value="2025-26" selected>2025-26</option>', response.content.decode())

    def test_memos_open_on_all_years_when_there_are_no_rows(self):
        response = self.open("fees_memos")
        self.assertNotIn("financial_year", response.context["filters"])
        self.assertEqual(response.status_code, 200)

    def test_an_explicit_year_is_kept_even_when_it_is_empty(self):
        self.new_memo(date="2025-05-02")
        response = self.open("fees_memos", {"fy": "2026-27"})
        self.assertEqual(response.context["filters"]["financial_year"], "2026-27")
        self.assertEqual(len(response.context["items"]), 0)
        self.assertEqual(len(self.open("fees_memos", {"fy": ""}).context["items"]), 1)

    def test_drafts_follow_the_same_rule(self):
        memo = self.new_memo(date="2025-05-02")
        Memo.objects.filter(pk=memo.pk).update(is_draft=True)
        self.assertEqual(self.open("fees_memo_drafts").context["filters"]["financial_year"], "2025-26")
        Memo.objects.filter(pk=memo.pk).update(is_draft=False)
        self.assertNotIn("financial_year", self.open("fees_memo_drafts").context["filters"])

    def test_feebook_opens_on_the_current_year_when_it_has_payments(self):
        self.pay("2026-08-09")
        self.pay("2025-06-09")
        response = self.open("fees_feebook")
        self.assertEqual(response.context["filters"]["financial_year"], "2026-27")
        self.assertEqual(len(response.context["entries"]), 1)

    def test_feebook_opens_on_the_newest_year_with_payments_when_the_current_year_is_empty(self):
        FeesSettings.objects.update_or_create(profile=self.profile, defaults={"feebook_start_year": "2020-21"})
        self.pay("2025-06-09")
        self.pay("2023-06-09")
        response = self.open("fees_feebook")
        self.assertEqual(response.context["filters"]["financial_year"], "2025-26")
        self.assertEqual(len(response.context["entries"]), 1)

    def test_feebook_never_offers_or_defaults_to_a_year_before_its_start_year(self):
        FeesSettings.objects.update_or_create(profile=self.profile, defaults={"feebook_start_year": "2025-26"})
        self.pay("2025-06-09")
        self.pay("2023-06-09")
        response = self.open("fees_feebook")
        self.assertEqual(response.context["filters"]["financial_year"], "2025-26")
        self.assertEqual(len(response.context["entries"]), 1)
        html = response.content.decode()
        self.assertNotIn('<option value="2023-24"', html)
        self.assertEqual(filter_options.feebook_options(self.profile, {}, [])["years"], {"2025-26"})

    def test_feebook_opens_on_all_years_when_there_are_no_payments(self):
        self.assertNotIn("financial_year", self.open("fees_feebook").context["filters"])
        self.pay("2025-06-09")
        self.assertEqual(len(self.open("fees_feebook", {"fy": "2026-27"}).context["entries"]), 0)
