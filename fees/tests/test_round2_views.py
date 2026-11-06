"""Round 2 views: the signature box on the memo form, Settings keys, the memo move page and the renamed label."""
from django.urls import reverse

from fees.models import FeesSettings, Matter, Memo, WordTemplate
from fees.services import memos, word_template
from fees.tests import docx_support as ds
from fees.tests.test_views_write import WriteBase


class SignatureBoxTests(WriteBase):
    def memo_post(self, **over):
        data = {
            "matter_id": str(self.seed["matter_1"].pk),
            "date": "2026-08-10",
            "addressee_line1": "Typed addressee",
            "num_appearances": "1",
            "fees_per_appearance": "1000",
            "action": "save",
        }
        data.update(over)
        return data

    def remove_signature(self):
        # The seed stores a signature; take it away for the "no signature" cases.
        WordTemplate.objects.filter(profile=self.profile).update(signature_data=None, signature_filename="")

    def add_signature(self):
        word_template.upload_signature(self.profile, "sig.png", "image/png", ds.png_bytes())

    def test_the_box_is_removed_from_the_form_when_there_is_no_signature(self):
        self.remove_signature()
        response = self.client.get(reverse("fees_memo_new"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="include_signature"')

    def test_the_box_is_on_the_form_when_a_signature_exists(self):
        self.add_signature()
        response = self.client.get(reverse("fees_memo_new"))
        self.assertContains(response, 'name="include_signature"')
        self.assertNotContains(response, 'name="include_signature" value="1" checked')

    def test_a_new_memo_starts_ticked_when_the_setting_is_on(self):
        self.add_signature()
        FeesSettings.objects.update_or_create(profile=self.profile, defaults={"memo_signature_default": True})
        response = self.client.get(reverse("fees_memo_new"))
        self.assertContains(response, 'name="include_signature" value="1" checked')

    def test_the_setting_has_no_effect_on_the_form_without_a_signature(self):
        self.remove_signature()
        FeesSettings.objects.update_or_create(profile=self.profile, defaults={"memo_signature_default": True})
        response = self.client.get(reverse("fees_memo_new"))
        self.assertNotContains(response, 'name="include_signature"')

    def test_ticking_the_box_saves_it_and_leaving_it_off_does_not(self):
        self.add_signature()
        self.post("fees_memo_new", self.memo_post(addressee_line1="Ticked", include_signature=["0", "1"]))
        self.post("fees_memo_new", self.memo_post(addressee_line1="Unticked", include_signature="0"))
        self.assertTrue(Memo.objects.get(profile=self.profile, addressee_line1="Ticked").include_signature)
        self.assertFalse(Memo.objects.get(profile=self.profile, addressee_line1="Unticked").include_signature)

    def test_a_form_without_the_box_leaves_the_memo_flag_alone_on_edit(self):
        memo = self.new_memo(include_signature=True)
        self.post("fees_memo_edit", self.memo_post(), kwargs={"memo_id": memo.pk})
        self.assertTrue(Memo.objects.get(pk=memo.pk).include_signature)

    def test_edit_shows_the_stored_flag(self):
        self.add_signature()
        memo = self.new_memo(include_signature=True)
        response = self.client.get(reverse("fees_memo_edit", kwargs={"memo_id": memo.pk}))
        self.assertContains(response, 'name="include_signature" value="1" checked')
        other = self.new_memo()
        response = self.client.get(reverse("fees_memo_edit", kwargs={"memo_id": other.pk}))
        self.assertNotContains(response, 'name="include_signature" value="1" checked')

    def test_based_on_copies_the_flag(self):
        self.add_signature()
        memo = self.new_memo(include_signature=True)
        response = self.client.get(reverse("fees_memo_based_on", kwargs={"memo_id": memo.pk}))
        self.assertContains(response, 'name="include_signature" value="1" checked')


class SettingsKeysTests(WriteBase):
    def config(self):
        return FeesSettings.objects.get(profile=self.profile)

    def test_the_new_settings_are_saved(self):
        response = self.post(
            "fees_settings",
            {"memo_signature_default": ["0", "1"], "list_default_filter": "active", "default_court_name": "Line one\r\nLine two"},
        )
        self.assertRedirects(response, reverse("fees_settings"), fetch_redirect_response=False)
        config = self.config()
        self.assertTrue(config.memo_signature_default)
        self.assertEqual(config.list_default_filter, "active")
        self.assertEqual(config.default_court_name, "Line one\nLine two")

    def test_a_bad_list_filter_is_refused_and_nothing_changes(self):
        self.post("fees_settings", {"list_default_filter": "bogus"})
        self.assertEqual(self.config().list_default_filter, "all")

    def test_the_settings_page_shows_the_new_controls(self):
        response = self.client.get(reverse("fees_settings"))
        self.assertContains(response, 'name="memo_signature_default"')
        self.assertContains(response, 'name="list_default_filter"')


class MultiLineCaptionTests(WriteBase):
    def test_a_memo_keeps_line_breaks_in_the_court_text_beyond_300_characters(self):
        text = "First line\n" + "x" * 400
        response = self.post(
            "fees_memo_new",
            {
                "matter_id": str(self.seed["matter_1"].pk),
                "date": "2026-08-10",
                "addressee_line1": "Multi",
                "court_name": text,
                "action": "save",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Memo.objects.get(profile=self.profile, addressee_line1="Multi").court_name, text)


class PaymentLabelTests(WriteBase):
    def test_the_payment_form_says_additional_details(self):
        response = self.client.get(reverse("fees_payment_new"))
        self.assertContains(response, "Additional Details")
        self.assertNotContains(response, "Internal")
        self.assertContains(response, 'name="payment_details"')


class MoveMemoViewTests(WriteBase):
    def setUp(self):
        super().setUp()
        self.memo = self.seed["memo_a"]
        self.target = self.seed["matter_3"]

    def move(self, target_id, memo_id=None):
        return self.post("fees_memo_move", {"matter_id": str(target_id)}, kwargs={"memo_id": memo_id or self.memo.pk})

    def test_the_page_lists_other_active_matters_grouped_by_firm(self):
        response = self.client.get(reverse("fees_memo_move", kwargs={"memo_id": self.memo.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<optgroup")
        self.assertContains(response, 'value="%d"' % self.target.pk)
        self.assertNotContains(response, 'value="%d"' % self.seed["matter_1"].pk)

    def test_an_archived_matter_is_not_offered(self):
        Matter.objects.filter(pk=self.target.pk).update(is_archived=True)
        response = self.client.get(reverse("fees_memo_move", kwargs={"memo_id": self.memo.pk}))
        self.assertNotContains(response, 'value="%d"' % self.target.pk)

    def test_an_editor_moves_a_memo_and_the_number_and_payments_stay(self):
        before = Memo.objects.get(pk=self.memo.pk)
        response = self.move(self.target.pk)
        self.assertRedirects(
            response, reverse("fees_memo_detail", kwargs={"memo_id": self.memo.pk}), fetch_redirect_response=False
        )
        after = Memo.objects.get(pk=self.memo.pk)
        self.assertEqual(after.matter_id, self.target.pk)
        self.assertEqual(after.firm_id, self.target.firm_id)
        self.assertEqual(after.group_id, self.target.group_id)
        self.assertEqual(after.memo_number, before.memo_number)
        self.assertEqual(after.amount_paid, before.amount_paid)
        self.assertEqual(after.total_fees, before.total_fees)
        self.assertEqual(memos.get_memo(self.profile, self.memo.pk)["firm_id"], self.target.firm_id)

    def test_an_archived_target_is_refused(self):
        Matter.objects.filter(pk=self.target.pk).update(is_archived=True)
        response = self.move(self.target.pk)
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "Active Matter", status_code=409)
        self.assertEqual(Memo.objects.get(pk=self.memo.pk).matter_id, self.seed["matter_1"].pk)

    def test_no_choice_is_a_422_on_the_same_page(self):
        response = self.post("fees_memo_move", {}, kwargs={"memo_id": self.memo.pk})
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "Choose the matter", status_code=422)

    def test_another_profiles_matter_or_memo_is_a_404(self):
        self.assertEqual(self.move(self.other_seed["matter_3"].pk).status_code, 404)
        self.assertEqual(self.move(self.target.pk, self.other_seed["memo_a"].pk).status_code, 404)
        self.assertEqual(
            self.client.get(reverse("fees_memo_move", kwargs={"memo_id": self.other_seed["memo_a"].pk})).status_code, 404
        )

    def test_a_reader_cannot_open_or_post_the_page(self):
        self.client.force_login(self.reader)
        url = reverse("fees_memo_move", kwargs={"memo_id": self.memo.pk})
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, {"matter_id": str(self.target.pk)}).status_code, 403)
        self.assertEqual(Memo.objects.get(pk=self.memo.pk).matter_id, self.seed["matter_1"].pk)

    def test_the_more_menu_is_only_for_an_editor(self):
        url = reverse("fees_memo_detail", kwargs={"memo_id": self.memo.pk})
        move_url = reverse("fees_memo_move", kwargs={"memo_id": self.memo.pk})
        self.assertContains(self.client.get(url), move_url)
        self.client.force_login(self.reader)
        self.assertNotContains(self.client.get(url), move_url)


class ListDefaultFilterTests(WriteBase):
    def test_firms_list_uses_the_setting_unless_the_url_says_otherwise(self):
        from django.utils.html import escape
        from fees.models import Firm
        firm = self.seed["matter_1"].firm
        Firm.objects.filter(pk=firm.pk).update(status="archived")
        url = reverse("fees_firms")
        self.assertContains(self.client.get(url), escape(firm.name))  # "Alpha & Co" is shown as "Alpha &amp; Co"
        FeesSettings.objects.update_or_create(profile=self.profile, defaults={"list_default_filter": "active"})
        self.assertNotContains(self.client.get(url), 'href="%s"' % reverse("fees_firm_detail", args=[firm.pk]))
        self.assertContains(self.client.get(url + "?status=all"), 'href="%s"' % reverse("fees_firm_detail", args=[firm.pk]))
        self.assertContains(self.client.get(url), "Active only")

    def test_firm_page_matters_use_the_setting_unless_the_url_says_otherwise(self):
        matter = self.seed["matter_1"]
        Matter.objects.filter(pk=matter.pk).update(is_archived=True)
        url = reverse("fees_firm_detail", args=[matter.firm_id])
        link = 'href="%s"' % reverse("fees_matter_detail", args=[matter.pk])
        self.assertContains(self.client.get(url), link)
        FeesSettings.objects.update_or_create(profile=self.profile, defaults={"list_default_filter": "active"})
        self.assertNotContains(self.client.get(url), link)
        self.assertContains(self.client.get(url + "?matters=all"), link)


class ResizableColumnsAndSearchTests(WriteBase):
    """Items 2.14 and 2.15: stable table ids, the embedded widths, the search url and the combobox wiring."""

    def table_pages(self):
        seed = self.seed
        return [
            reverse("fees_memos"),
            reverse("fees_memo_drafts"),
            reverse("fees_dashboard"),
            reverse("fees_outstanding"),
            reverse("fees_outstanding_detail"),
            reverse("fees_feebook"),
            reverse("fees_statistics") + "?tab=standard",
            reverse("fees_statistics") + "?tab=edit",
            reverse("fees_statistics") + "?tab=explore",
            reverse("fees_matter_detail", args=[seed["matter_1"].pk]),
            reverse("fees_firm_ledger", args=[seed["firm_a"].pk]),
            reverse("fees_firm_statement", args=[seed["firm_a"].pk]),
            reverse("fees_search_page") + "?q=Alpha",
        ]

    def test_every_table_has_a_stable_id(self):
        import re

        for url in self.table_pages():
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)
            html = response.content.decode()
            for tag in re.findall(r"<table\b[^>]*>", html):
                self.assertRegex(tag, r'data-table-id="[a-z0-9][a-z0-9_-]{0,39}"', f"{url}: {tag}")
            again = re.findall(r'data-table-id="([^"]+)"', self.client.get(url).content.decode())
            self.assertEqual(again, re.findall(r'data-table-id="([^"]+)"', html), url)

    def test_the_main_lists_use_the_agreed_ids(self):
        for url, table_id in (
            (reverse("fees_memos"), "memos"),
            (reverse("fees_memo_drafts"), "drafts"),
            (reverse("fees_feebook"), "feebook"),
            (reverse("fees_outstanding"), "outstanding-firms"),
            (reverse("fees_dashboard"), "dashboard-recent"),
            (reverse("fees_matter_detail", args=[self.seed["matter_1"].pk]), "matter-memos"),
        ):
            self.assertContains(self.client.get(url), f'data-table-id="{table_id}"')

    def test_prefs_round_trip_per_user_and_profile(self):
        url = reverse("fees_prefs")
        saved = self.client.post(
            url, data='{"key": "col-widths:memos", "data": {"date": 150}}', content_type="application/json"
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(self.client.get(url, {"key": "col-widths:memos"}).json()["data"], {"date": 150})
        # The saved widths are embedded in the page for the user who saved them ...
        self.assertContains(self.client.get(reverse("fees_memos")), '"memos": {"date": 150}')
        # ... and not for another user of the same profile.
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(url, {"key": "col-widths:memos"}).json()["data"], {})
        self.assertNotContains(self.client.get(reverse("fees_memos")), '"date": 150')

    def test_the_page_loads_the_scripts_and_the_widths_json(self):
        html = self.client.get(reverse("fees_memos")).content.decode()
        self.assertIn('id="fees-col-widths"', html)
        self.assertIn("js/fees/columns.js", html)
        self.assertIn("js/fees/search-suggest.js", html)
        self.assertIn('data-prefs-url="%s"' % reverse("fees_prefs"), html)
        self.assertIn('data-search-url="%s"' % reverse("fees_search"), html)

    def test_search_results_carry_the_item_url(self):
        firm = self.seed["firm_a"]
        data = self.client.get(reverse("fees_search"), {"q": firm.name}).json()
        hit = [r for r in data["results"] if r["kind"] == "firm" and r["id"] == firm.pk][0]
        self.assertEqual(hit["url"], reverse("fees_firm_detail", args=[firm.pk]))
        for r in data["results"]:
            self.assertTrue(r["url"].startswith("/"))
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(reverse("fees_search"), {"q": firm.name}).status_code, 200)

    def test_clear_all_data_anchor_exists_on_the_backup_page(self):
        self.assertContains(self.client.get(reverse("fees_backup")), 'id="clear"')
