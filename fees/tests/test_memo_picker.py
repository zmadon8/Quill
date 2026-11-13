"""New Memo: one Firm then Matter picker (active only unless "Show archived" is ticked), defaults loaded when a matter is chosen,
and the firm / matter checks on save."""
from django.urls import reverse

from fees.models import Matter, Memo
from fees.services import firms, matters
from fees.tests import test_views_write as w


class PickerBase(w.WriteBase):
    def setUp(self):
        super().setUp()
        self.firm_a, self.firm_b = self.seed["firm_a"], self.seed["firm_b"]
        self.m1, self.m2, self.m3 = self.seed["matter_1"], self.seed["matter_2"], self.seed["matter_3"]
        self.url = reverse("fees_memo_new")

    def page(self, query=""):
        response = self.client.get(self.url + query)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def picker_json(self, **params):
        return self.client.get(reverse("fees_memo_picker"), params).json()


class PickerPageTests(PickerBase):
    def test_one_picker_and_no_second_matter_select_or_defaults_button(self):
        text = self.page()
        self.assertEqual(text.count('name="matter_id"'), 1)
        self.assertIn('<input type="hidden" name="matter_id"', text)
        self.assertNotIn("Load Defaults", text)
        self.assertNotIn("Start from a matter", text)
        self.assertIn('name="firm"', text)
        self.assertIn('name="matter"', text)
        self.assertIn("Show archived firms and matters", text)
        self.assertIn("js/fees/memo-picker.js", text)

    def test_only_active_firms_are_listed_by_default_and_the_matter_list_waits_for_a_firm(self):
        firms.set_firm_status(self.profile, self.firm_b.pk, "archived")
        text = self.page()
        self.assertIn("Alpha &amp; Co", text)
        self.assertNotIn("Beta Ltd", text)
        self.assertIn("Choose a firm first", text)
        self.assertNotIn("Matter One", text)

    def test_firm_param_lists_that_firms_active_matters_grouped_by_group(self):
        text = self.page("?firm=%d" % self.firm_a.pk)
        self.assertIn("Matter One", text)
        self.assertIn("Matter Two", text)
        self.assertNotIn("Matter Three", text)
        self.assertIn('<optgroup label="Second Group">', text)

    def test_archived_matters_and_firms_need_the_tick_box(self):
        matters.archive_matter(self.profile, self.m2.pk)
        firms.set_firm_status(self.profile, self.firm_b.pk, "archived")
        plain = self.page("?firm=%d" % self.firm_a.pk)
        self.assertNotIn("Matter Two", plain)
        self.assertNotIn("Beta Ltd", plain)
        self.assertNotIn(" checked", plain.split('data-picker-archived')[1].split(">")[0])
        ticked = self.page("?firm=%d&archived=1" % self.firm_a.pk)
        self.assertIn("Matter Two (archived)", ticked)
        self.assertIn("Beta Ltd (archived)", ticked)
        self.assertIn(" checked", ticked.split('data-picker-archived')[1].split(">")[0])

    def test_matter_link_preselects_firm_and_matter_and_fills_the_defaults(self):
        text = self.page("?matter=%d" % self.m1.pk)
        self.assertIn('<option value="%d" selected>Alpha &amp; Co</option>' % self.firm_a.pk, text)
        self.assertIn('<option value="%d" selected>Matter One</option>' % self.m1.pk, text)
        self.assertIn('name="matter_id" value="%d"' % self.m1.pk, text)
        self.assertIn('name="firm_id" value="%d"' % self.firm_a.pk, text)
        self.assertIn('name="court_name" rows="4">High Court</textarea>', text)

    def test_a_matter_of_another_firm_in_the_query_is_dropped_when_the_firm_was_changed(self):
        text = self.page("?firm=%d&matter=%d" % (self.firm_b.pk, self.m1.pk))
        self.assertIn('name="matter_id" value=""', text)
        self.assertNotIn("High Court", text)
        self.assertIn("Matter Three", text)

    def test_an_archived_matter_link_turns_the_tick_box_on_and_shows_the_note(self):
        matters.archive_matter(self.profile, self.m2.pk)
        text = self.page("?matter=%d" % self.m2.pk)
        self.assertIn('<option value="%d" selected>Matter Two (archived)</option>' % self.m2.pk, text)
        self.assertIn(" checked", text.split('data-picker-archived')[1].split(">")[0])
        self.assertNotIn("data-archived-note hidden", text)

    def test_another_profiles_matter_link_is_a_404(self):
        self.assertEqual(self.client.get(self.url, {"matter": self.other_seed["matter_1"].pk}).status_code, 404)

    def test_the_form_shown_again_after_an_error_keeps_the_firm_and_matter(self):
        response = self.client.post(self.url, {"matter_id": str(self.m3.pk), "date": "", "action": "save"})
        self.assertEqual(response.status_code, 422)
        text = response.content.decode()
        self.assertIn('<option value="%d" selected>Matter Three</option>' % self.m3.pk, text)
        self.assertIn('name="firm_id" value="%d"' % self.firm_b.pk, text)

    def test_the_form_shown_again_after_an_error_keeps_a_firm_chosen_without_a_matter_and_the_archived_tick(self):
        firms.set_firm_status(self.profile, self.firm_b.pk, "archived")
        response = self.client.post(self.url, {"firm_id": str(self.firm_b.pk), "show_archived": "1", "date": "", "action": "save"})
        self.assertEqual(response.status_code, 422)
        text = response.content.decode()
        self.assertIn('<option value="%d" selected>Beta Ltd (archived)</option>' % self.firm_b.pk, text)
        self.assertIn('name="firm_id" value="%d"' % self.firm_b.pk, text)
        self.assertIn(" checked", text.split("data-picker-archived")[1].split(">")[0])
        self.assertIn('name="show_archived" value="1"', text)

    def test_the_form_shown_again_after_an_error_marks_only_the_unchanged_defaults_as_filled_in_for_you(self):
        defaults = self.client.get(reverse("fees_memo_matter_defaults"), {"matter": self.m1.pk}).json()["fields"]
        posted = {"matter_id": str(self.m1.pk), "date": "", "action": "save"}
        posted.update(defaults)
        posted["client"] = "Typed by hand"
        text = self.client.post(self.url, posted).content.decode()
        marker = text.split("data-autofilled-fields=")[1].split('"')[1] if "data-autofilled-fields=" in text else ""
        names = marker.split()
        self.assertNotIn("client", names)
        for name in defaults:
            if name != "client":
                self.assertIn(name, names)

    def test_a_fresh_page_marks_the_settings_cause_title_as_filled_in_for_you(self):
        from fees.services import settings as settings_service
        settings_service.update_settings(self.profile, {"default_court_name": "High Court"})
        text = self.page()
        self.assertIn("High Court", text)
        self.assertIn("court_name", text.split("data-autofilled-fields=")[1].split('"')[1].split())

    def test_defaults_endpoint_sends_the_settings_defaults_as_a_fallback(self):
        from fees.services import settings as settings_service
        settings_service.update_settings(self.profile, {"default_court_name": "High Court"})
        out = self.client.get(reverse("fees_memo_matter_defaults"), {"matter": self.m1.pk}).json()
        self.assertEqual(out["fallback"].get("court_name"), "High Court")


class PickerEndpointTests(PickerBase):
    def test_picker_json_lists_active_firms_only_and_a_firms_matters_by_group(self):
        firms.set_firm_status(self.profile, self.firm_b.pk, "archived")
        out = self.picker_json(firm=self.firm_a.pk)
        self.assertEqual([f["name"] for f in out["firms"]], ["Alpha & Co"])
        self.assertEqual({g["name"]: [m["name"] for m in g["matters"]] for g in out["groups"]}.get("Second Group"), ["Matter Two"])
        self.assertEqual(self.picker_json()["groups"], [])

    def test_picker_json_with_archived_includes_archived_firms_and_matters(self):
        firms.set_firm_status(self.profile, self.firm_b.pk, "archived")
        matters.archive_matter(self.profile, self.m2.pk)
        out = self.picker_json(firm=self.firm_a.pk, archived=1)
        self.assertEqual([(f["name"], f["archived"]) for f in out["firms"]], [("Alpha & Co", False), ("Beta Ltd", True)])
        names = [(m["name"], m["archived"]) for g in out["groups"] for m in g["matters"]]
        self.assertIn(("Matter Two", True), names)

    def test_picker_json_ignores_another_profiles_firm(self):
        out = self.picker_json(firm=self.other_seed["firm_a"].pk)
        self.assertIsNone(out["firm_id"])
        self.assertEqual(out["groups"], [])

    def test_defaults_endpoint_returns_the_matters_filled_fields_only(self):
        out = self.client.get(reverse("fees_memo_matter_defaults"), {"matter": self.m1.pk}).json()
        self.assertTrue(out["ok"])
        self.assertEqual((out["matter_id"], out["firm_id"], out["archived"]), (self.m1.pk, self.firm_a.pk, False))
        self.assertEqual(out["fields"]["court_name"], "High Court")
        self.assertEqual(out["fields"]["addressee_line1"], "Alpha & Co")   # "use the firm's name" wins
        self.assertNotIn("plaintiff_name", out["fields"])
        self.assertNotIn("notes", out["fields"])

    def test_defaults_endpoint_refuses_another_profiles_matter_and_a_missing_one(self):
        url = reverse("fees_memo_matter_defaults")
        self.assertEqual(self.client.get(url, {"matter": self.other_seed["matter_1"].pk}).status_code, 404)
        self.assertEqual(self.client.get(url, {"matter": "x"}).status_code, 422)

    def test_a_reader_may_read_both_endpoints(self):
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(reverse("fees_memo_picker")).status_code, 200)
        self.assertEqual(self.client.get(reverse("fees_memo_matter_defaults"), {"matter": self.m1.pk}).status_code, 200)


class PickerSaveTests(PickerBase):
    def test_a_matter_that_is_not_in_the_chosen_firm_is_rejected(self):
        before = Memo.objects.count()
        response = self.post("fees_memo_new", self.memo_post(matter_id=str(self.m3.pk), firm_id=str(self.firm_a.pk)))
        self.assertEqual(response.status_code, 422)
        self.assertIn("does not belong to the chosen firm", response.content.decode())
        self.assertEqual(Memo.objects.count(), before)

    def test_a_matter_in_the_chosen_firm_saves(self):
        response = self.post("fees_memo_new", self.memo_post(matter_id=str(self.m2.pk), firm_id=str(self.firm_a.pk)))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Memo.objects.order_by("-pk").first().matter_id, self.m2.pk)

    def test_the_firm_is_optional_on_save(self):
        self.assertEqual(self.post("fees_memo_new", self.memo_post(matter_id=str(self.m3.pk))).status_code, 302)

    def test_an_archived_matter_still_cannot_get_a_finished_memo_but_can_get_a_draft(self):
        matters.archive_matter(self.profile, self.m2.pk)
        refused = self.post("fees_memo_new", self.memo_post(matter_id=str(self.m2.pk)))
        self.assertNotEqual(refused.status_code, 302)
        self.assertIn("Active Matters", refused.content.decode())
        draft = self.post("fees_memo_new", self.memo_post(matter_id=str(self.m2.pk), action="draft"))
        self.assertEqual(draft.status_code, 302)
        self.assertTrue(Matter.objects.get(pk=self.m2.pk).is_archived)
