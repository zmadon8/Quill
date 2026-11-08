"""Owner round rules: filter drop-downs list only values with rows under the other filters (and keep the chosen
one), every multi-select has All and None, and the year drop-downs open on the current financial year."""
import re
from pathlib import Path

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from accounts.models import Profile
from accounts.suite import KEY_FEES
from fees.models import FeesSettings
from fees.services import fy_options
from fees.services.filter_options import narrow_outstanding_choices
from fees.tests.test_views_write import WriteBase

ROOT = Path(__file__).resolve().parent.parent.parent


def options_of(html, name):
    """The (value, text) pairs of the ``<select name=...>`` called ``name``."""
    match = re.search(r'<select name="%s"[^>]*>(.*?)</select>' % name, html, re.S)
    assert match, name
    return re.findall(r'<option value="([^"]*)"[^>]*>([^<]*)</option>', match.group(1))


def texts(html, name):
    return [text for _value, text in options_of(html, name)]


class MemoFilterNarrowingTests(WriteBase):
    def setUp(self):
        super().setUp()
        FeesSettings.objects.update_or_create(
            profile=self.profile, defaults={"memos_start_year": "2000-01", "feebook_start_year": "2000-01", "initial_financial_year": "2000-01"},
        )
        self.alpha = self.seed["firm_a"]

    def page(self, name, **query):
        return self.client.get(reverse(name), query).content.decode()

    def test_choosing_a_year_limits_the_firm_list_to_firms_with_memos_that_year(self):
        current = self.page("fees_memos", fy="2026-27")
        self.assertIn("Alpha &amp; Co", texts(current, "firm"))
        self.assertNotIn("Beta Ltd", texts(current, "firm"))
        earlier = self.page("fees_memos", fy="2025-26")
        self.assertIn("Beta Ltd", texts(earlier, "firm"))
        self.assertNotIn("Alpha &amp; Co", texts(earlier, "firm"))
        every = self.page("fees_memos", fy="")
        self.assertEqual(texts(every, "firm")[1:], ["Alpha &amp; Co", "Beta Ltd"])

    def test_choosing_a_firm_limits_the_year_list_to_that_firms_years(self):
        html = self.page("fees_memos", fy="", firm=str(self.alpha.pk))
        years = [v for v, _t in options_of(html, "fy") if v]
        self.assertEqual(years, ["2026-27"])

    def test_the_chosen_firm_stays_in_the_list_even_when_it_has_no_rows(self):
        html = self.page("fees_memos", fy="2026-27", firm=str(self.beta_pk()))
        self.assertRegex(html, r'<option value="%d" selected>Beta Ltd</option>' % self.beta_pk())

    def beta_pk(self):
        from fees.models import Firm

        return Firm.objects.get(profile=self.profile, name="Beta Ltd").pk

    def test_drafts_list_only_firms_with_drafts(self):
        html = self.page("fees_memo_drafts", fy="")
        self.assertEqual(texts(html, "firm")[1:], ["Alpha &amp; Co"])

    def test_feebook_firms_follow_the_year(self):
        html = self.page("fees_feebook", fy="2026-27")
        self.assertIn("Alpha &amp; Co", texts(html, "firm"))
        self.assertNotIn("Beta Ltd", texts(html, "firm"))
        self.assertEqual(texts(self.page("fees_feebook", fy="2025-26"), "firm"), ["All"])

    def test_feebook_years_come_from_the_payments(self):
        html = self.page("fees_feebook", fy="")
        self.assertEqual([v for v, _t in options_of(html, "fy") if v], ["2026-27"])

    def test_feebook_banks_follow_the_other_filters(self):
        self.assertIn("HDFC Current", texts(self.page("fees_feebook", fy="2026-27"), "bank"))
        self.assertNotIn("HDFC Current", texts(self.page("fees_feebook", fy="2025-26"), "bank"))

    def test_outstanding_groups_follow_the_chosen_firm(self):
        response = self.client.get(reverse("fees_outstanding_detail"), {"written_off": "1", "firm": str(self.beta_pk())})
        partners = response.context["choices"]["partners"]
        self.assertTrue(partners)
        self.assertTrue(all(p["firm_id"] == self.beta_pk() for p in partners))
        firms_listed = [f["id"] for f in response.context["choices"]["firms"]]
        self.assertIn(self.beta_pk(), firms_listed)

    def test_outstanding_keeps_a_chosen_firm_with_nothing_outstanding(self):
        response = self.client.get(reverse("fees_outstanding_detail"), {"firm": str(self.beta_pk())})
        self.assertIn(self.beta_pk(), [f["id"] for f in response.context["choices"]["firms"]])

    def test_narrow_outstanding_choices_by_group_limits_the_firms(self):
        choices = {"firms": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}],
                   "partners": [{"id": 10, "firm_id": 1, "name": "G1"}, {"id": 20, "firm_id": 2, "name": "G2"}]}
        narrowed = narrow_outstanding_choices(self.profile, choices, {"group_id": 20})
        self.assertEqual([f["id"] for f in narrowed["firms"]], [2])
        self.assertEqual(len(narrowed["partners"]), 2)

    def test_explore_firms_follow_the_from_and_to_years(self):
        html = self.page("fees_statistics", tab="explore", from_fy="2026-27")
        self.assertIn("Alpha &amp; Co", texts(html, "firm_id"))
        self.assertNotIn("Beta Ltd", texts(html, "firm_id"))
        years = [v for v, _t in options_of(self.page("fees_statistics", tab="explore", firm_id=str(self.beta_pk())), "to_fy") if v]
        self.assertEqual(years, ["2025-26"])


class FyOptionsOnlyYearsTests(TestCase):
    def test_only_years_replaces_the_data_years_and_keeps_the_selected_one(self):
        profile = Profile.objects.create(program=KEY_FEES, name="Only-Years")
        options = fy_options.financial_year_options(profile, selected="2020-21", only_years={"2024-25", "bad"})
        self.assertEqual(options, ["2024-25", "2020-21"])

    def test_no_only_years_still_offers_the_current_year(self):
        profile = Profile.objects.create(program=KEY_FEES, name="Plain-Years")
        self.assertEqual(len(fy_options.financial_year_options(profile)), 1)


class AllNoneControlsTests(WriteBase):
    def test_the_dashboard_customise_form_has_real_submit_buttons(self):
        FeesSettings.objects.update_or_create(profile=self.profile, defaults={"dashboard_kpis_enabled": True})
        html = self.client.get(reverse("fees_dashboard")).content.decode()
        self.assertIn('data-select-all-none="kpi"', html)
        self.assertIn('<button type="submit" name="select" value="all"', html)
        self.assertIn('<button type="submit" name="select" value="none"', html)

    def test_all_and_none_reshow_the_boxes_and_save_nothing(self):
        FeesSettings.objects.update_or_create(profile=self.profile, defaults={"dashboard_kpis_enabled": True})
        before = FeesSettings.objects.get(profile=self.profile).dashboard_kpis
        response = self.post("fees_dashboard_kpis", {"select": "all"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("tick=all", response["Location"])
        self.assertEqual(FeesSettings.objects.get(profile=self.profile).dashboard_kpis, before)
        every = self.client.get(reverse("fees_dashboard"), {"customise": "1", "tick": "all"}).content.decode()
        none = self.client.get(reverse("fees_dashboard"), {"customise": "1", "tick": "none"}).content.decode()
        boxes = re.findall(r'<input type="checkbox" name="kpi"[^>]*>', every)
        self.assertTrue(boxes)
        self.assertTrue(all(" checked" in box for box in boxes))
        self.assertFalse(any(" checked" in box for box in re.findall(r'<input type="checkbox" name="kpi"[^>]*>', none)))

    def test_the_outstanding_tick_boxes_have_all_and_none(self):
        html = self.client.get(reverse("fees_outstanding_detail")).content.decode()
        self.assertIn('data-select-all-none="memo"', html)
        self.assertRegex(html, r'data-select-all-none="memo"[^>]*hidden')  # shown by the script
        self.assertNotRegex(html, r'data-select-all-none="memo"[^>]*data-max=')  # All ticks every memo: no limit
        self.assertIn('data-select="all">All</button>', html)
        self.assertIn('data-select="none">None</button>', html)

    def test_the_user_form_role_pickers_have_all_and_none(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("user_create")).content.decode()
        self.assertIn('data-select-kind="selects"', html)
        self.assertIn('data-select="none">None</button>', html)


class AllNoneSourceTests(SimpleTestCase):
    def test_the_script_and_include_exist_and_the_script_is_loaded_everywhere(self):
        self.assertTrue((ROOT / "static/js/select-all-none.js").exists())
        self.assertIn("data-select-all-none", (ROOT / "templates/_select_all_none.html").read_text())
        self.assertIn("js/select-all-none.js", (ROOT / "templates/base_suite.html").read_text())

    def test_the_search_ticks_have_all_and_none(self):
        source = (ROOT / "templates/diary/search.html").read_text()
        self.assertIn('name="citations flags headers"', source)

    def test_the_column_menu_has_all_and_none(self):
        source = (ROOT / "static/js/fees/columns.js").read_text()
        self.assertIn('["All", true], ["None", false]', source)


class CurrentYearDefaultTests(WriteBase):
    def test_every_year_drop_down_opens_on_the_current_year(self):
        from fees.services.financial_year import current_financial_year

        current = current_financial_year()
        FeesSettings.objects.update_or_create(
            profile=self.profile, defaults={"memos_start_year": "2000-01", "feebook_start_year": "2000-01"}
        )
        for name, query in (
            ("fees_memos", ""), ("fees_memo_drafts", ""), ("fees_feebook", ""), ("fees_statistics", "?tab=standard"),
        ):
            html = self.client.get(reverse(name) + query).content.decode()
            self.assertIn('<option value="%s" selected>%s</option>' % (current, current), html, name)

    def test_the_default_filters_the_rows_and_all_years_shows_everything(self):
        from fees.services.financial_year import current_financial_year

        default = self.client.get(reverse("fees_memos")).context["items"]
        every = self.client.get(reverse("fees_memos"), {"fy": ""}).context["items"]
        self.assertTrue(all(i["financial_year"] == current_financial_year() for i in default))
        self.assertGreaterEqual(len(every), len(default))
        self.assertEqual({i["financial_year"] for i in every} >= {"2025-26", "2026-27"}, True)

    def test_start_year_settings_keep_their_stored_values(self):
        FeesSettings.objects.update_or_create(profile=self.profile, defaults={"memos_start_year": "2024-25"})
        html = self.client.get(reverse("fees_settings")).content.decode()
        self.assertIn('<option value="2024-25" selected>2024-25</option>', html)
