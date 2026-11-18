"""The Plaintiff type and Defendant type drop-down lists: the defaults, the Settings save, the memo and matter forms, and the backups."""
from django.urls import reverse

from fees.errors import FeesError
from fees.models import DEFAULT_DEFENDANT_TYPES, DEFAULT_PLAINTIFF_TYPES, FeesSettings, Group, Matter, Memo
from fees.services import matters, memos
from fees.services.excel_backup import export_workbook
from fees.services import settings as settings_service
from accounts.models import Profile
from accounts.suite import KEY_FEES
from fees.services.excel_restore import RESTORE_CONFIRMATION, restore_workbook
from fees.tests import xlsx_support as xs
from fees.tests.xlsx_support import build_workbook, no_backup
from fees.tests.test_views_write import WriteBase

PLAINTIFFS = ["Applicant", "Applicants", "Claimant", "Claimants", "Petitioner", "Petitioners", "Plaintiff", "Plaintiffs", "Querist", "Querists"]
DEFENDANTS = ["Defendant", "Defendants", "Respondent", "Respondents"]


def fees_profile(name):
    return Profile.objects.create(program=KEY_FEES, name=name)


def restore(profile, source):
    return restore_workbook(profile, source, RESTORE_CONFIRMATION, backup_func=no_backup)


def minimal_sheets():
    """The smallest valid workbook: key columns only, one firm, partner, matter and memo."""
    return {
        "Firms": [["id", "name"], [1, "F"]],
        "Partners": [["id", "firm_id", "name"], [1, 1, "G"]],
        "Matters": [["id", "firm_id", "partner_id", "name"], [1, 1, 1, "M"]],
        "BankAccounts": [["id", "name"]],
        "Memos": [["id", "matter_id", "date"], [1, 1, "2026-05-17"]],
        "Payments": [["id", "amount", "date_of_payment"]],
        "Settings": [["id"], [1]],
    }


class PartyTypeSettingsTests(WriteBase):
    def test_a_new_profile_has_the_initial_lists(self):
        config = settings_service.get_settings(self.profile)
        self.assertEqual(config["plaintiff_types"], PLAINTIFFS)
        self.assertEqual(config["defendant_types"], DEFENDANTS)
        self.assertEqual(list(DEFAULT_PLAINTIFF_TYPES), PLAINTIFFS)
        self.assertEqual(list(DEFAULT_DEFENDANT_TYPES), DEFENDANTS)

    def test_lists_are_not_shared_between_profiles(self):
        first = FeesSettings.objects.get(profile=self.profile)
        first.plaintiff_types.append("Extra")
        self.assertEqual(FeesSettings._meta.get_field("plaintiff_types").get_default(), PLAINTIFFS)

    def test_save_from_the_settings_page(self):
        response = self.post("fees_settings", {"tab": "memos", "plaintiff_types": "Appellant\r\n  Respondent  \r\n\r\nappellant2\r\n", "defendant_types": "Opposite party"})
        self.assertEqual(response.status_code, 302)
        config = settings_service.get_settings(self.profile)
        self.assertEqual(config["plaintiff_types"], ["Appellant", "Respondent", "appellant2"])
        self.assertEqual(config["defendant_types"], ["Opposite party"])

    def test_the_page_shows_one_type_per_line(self):
        response = self.client.get(reverse("fees_settings"))
        self.assertContains(response, 'name="plaintiff_types"')
        self.assertContains(response, "Applicant\nApplicants\nClaimant")

    def test_validation(self):
        for text in ("A\na", "x" * 101, "\n".join(f"T{i}" for i in range(51))):
            response = self.post("fees_settings", {"tab": "memos", "plaintiff_types": text})
            self.assertEqual(response.status_code, 422, text[:20])
        self.assertEqual(settings_service.get_settings(self.profile)["plaintiff_types"], PLAINTIFFS)

    def test_service_limits(self):
        update = settings_service.update_settings
        self.assertEqual(update(self.profile, {"plaintiff_types": ["T%d" % i for i in range(50)]})["plaintiff_types"][49], "T49")
        self.assertEqual(update(self.profile, {"defendant_types": ["y" * 100]})["defendant_types"], ["y" * 100])
        self.assertEqual(update(self.profile, {"defendant_types": []})["defendant_types"], [])
        with self.assertRaises(FeesError):
            update(self.profile, {"defendant_types": ["Same", "SAME"]})
        self.assertEqual(update(self.profile, {"defendant_types": None})["defendant_types"], DEFENDANTS)

    def test_a_reader_cannot_save(self):
        self.client.force_login(self.reader)
        response = self.post("fees_settings", {"tab": "memos", "plaintiff_types": "Z"})
        self.assertEqual(response.status_code, 403)


class MemoFormPartyTypeTests(WriteBase):
    def memo_post(self, **over):
        data = {"matter_id": str(self.seed["matter_1"].pk), "date": "2026-08-10", "addressee_line1": "A", "num_appearances": "1",
                "fees_per_appearance": "1000", "action": "save"}
        data.update(over)
        return data

    def saved(self):
        return Memo.objects.filter(profile=self.profile).order_by("-pk").first()

    def test_the_form_has_drop_downs_with_the_lists_and_custom(self):
        response = self.client.get(reverse("fees_memo_new"))
        html = response.content.decode()
        self.assertContains(response, 'name="plaintiff_type_choice"')
        self.assertContains(response, 'name="defendant_type_choice"')
        self.assertContains(response, 'name="plaintiff_type_custom"')
        self.assertNotContains(response, 'name="plaintiff_type"')
        self.assertContains(response, '<option value="Querists">Querists</option>', html=False)
        self.assertContains(response, '<option value="Respondents">Respondents</option>', html=False)
        self.assertContains(response, "Custom…")
        self.assertLess(html.index('<option value="">(none)</option>'), html.index('<option value="Applicant"'))

    def test_the_form_follows_the_settings_list(self):
        settings_service.update_settings(self.profile, {"plaintiff_types": ["Only one"]})
        response = self.client.get(reverse("fees_memo_new"))
        self.assertContains(response, '<option value="Only one">Only one</option>', html=False)
        self.assertNotContains(response, '<option value="Querists">')

    def test_a_choice_is_stored(self):
        self.post("fees_memo_new", self.memo_post(plaintiff_type_choice="Petitioners", defendant_type_choice="Respondent"))
        memo = self.saved()
        self.assertEqual((memo.plaintiff_type, memo.defendant_type), ("Petitioners", "Respondent"))

    def test_custom_with_text_is_stored(self):
        self.post("fees_memo_new", self.memo_post(plaintiff_type_choice="__custom__", plaintiff_type_custom="  Next friend ",
                                                  defendant_type_choice="", defendant_type_custom="Proforma party"))
        memo = self.saved()
        self.assertEqual((memo.plaintiff_type, memo.defendant_type), ("Next friend", "Proforma party"))

    def test_a_choice_wins_over_a_filled_custom_box(self):
        self.post("fees_memo_new", self.memo_post(plaintiff_type_choice="Claimant", plaintiff_type_custom="ignored"))
        self.assertEqual(self.saved().plaintiff_type, "Claimant")

    def test_none_stores_blank(self):
        self.post("fees_memo_new", self.memo_post(plaintiff_type_choice="", plaintiff_type_custom=""))
        self.assertEqual(self.saved().plaintiff_type, "")

    def test_a_plain_post_still_works(self):
        self.post("fees_memo_new", self.memo_post(plaintiff_type="Plaintiff", defendant_type="Defendant"))
        memo = self.saved()
        self.assertEqual((memo.plaintiff_type, memo.defendant_type), ("Plaintiff", "Defendant"))

    def test_too_long_custom_type_is_refused_and_shown_again(self):
        response = self.post("fees_memo_new", self.memo_post(plaintiff_type_choice="__custom__", plaintiff_type_custom="x" * 101))
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "x" * 101, status_code=422)

    def test_an_existing_custom_value_opens_as_custom(self):
        memo = memos.create_memo(self.profile, xs.memo_input(self.seed["matter_1"].pk, plaintiff_type="Guardian", defendant_type="Respondent"))
        response = self.client.get(reverse("fees_memo_edit", kwargs={"memo_id": memo.pk}))
        html = response.content.decode()
        self.assertIn('<option value="__custom__" selected>', html)
        self.assertIn('name="plaintiff_type_custom" value="Guardian"', html)
        self.assertIn('<option value="Respondent" selected>', html)
        self.assertEqual(html.count('<option value="__custom__" selected>'), 1)

    def test_a_listed_value_is_preselected_and_the_custom_box_is_empty(self):
        memo = memos.create_memo(self.profile, xs.memo_input(self.seed["matter_1"].pk, plaintiff_type="Claimants"))
        html = self.client.get(reverse("fees_memo_edit", kwargs={"memo_id": memo.pk})).content.decode()
        self.assertIn('<option value="Claimants" selected>', html)
        self.assertIn('name="plaintiff_type_custom" value=""', html)

    def test_a_matter_fills_the_new_memo_form(self):
        matter = self.seed["matter_1"]
        matters.update_matter(self.profile, matter.pk, plaintiff_type="Querist", defendant_type="Their own")
        html = self.client.get(reverse("fees_memo_new"), {"matter": matter.pk}).content.decode()
        self.assertIn('<option value="Querist" selected>', html)
        self.assertIn('name="defendant_type_custom" value="Their own"', html)

    def test_the_matter_defaults_json_carries_the_types(self):
        matter = self.seed["matter_1"]
        matters.update_matter(self.profile, matter.pk, plaintiff_type="Querist")
        data = self.client.get(reverse("fees_memo_matter_defaults"), {"matter": matter.pk}).json()
        self.assertEqual(data["fields"]["plaintiff_type"], "Querist")


class MatterFormPartyTypeTests(WriteBase):
    def matter_post(self, **over):
        firm = self.seed["firm_a"]
        data = {"firm_id": str(firm.pk), "group_id": str(Group.objects.filter(firm=firm).first().pk), "name": "Party Matter"}
        data.update(over)
        return data

    def test_the_form_has_drop_downs(self):
        response = self.client.get(reverse("fees_matter_new"), {"firm": self.seed["firm_a"].pk})
        self.assertContains(response, 'name="plaintiff_type_choice"')
        self.assertContains(response, 'name="defendant_type_choice"')
        self.assertContains(response, '<option value="Applicants">Applicants</option>', html=False)
        self.assertContains(response, "Custom…")

    def test_choice_and_custom_are_stored(self):
        self.post("fees_matter_new", self.matter_post(plaintiff_type_choice="Plaintiffs", defendant_type_choice="__custom__", defendant_type_custom="Garnishee"))
        matter = Matter.objects.get(profile=self.profile, name="Party Matter")
        self.assertEqual((matter.plaintiff_type, matter.defendant_type), ("Plaintiffs", "Garnishee"))

    def test_a_plain_post_still_works(self):
        self.post("fees_matter_new", self.matter_post(plaintiff_type="Plaintiff"))
        self.assertEqual(Matter.objects.get(profile=self.profile, name="Party Matter").plaintiff_type, "Plaintiff")

    def test_an_existing_custom_value_opens_as_custom(self):
        matter = self.seed["matter_1"]
        matters.update_matter(self.profile, matter.pk, plaintiff_type="Decree holder")
        html = self.client.get(reverse("fees_matter_edit", kwargs={"matter_id": matter.pk})).content.decode()
        self.assertIn('<option value="__custom__" selected>', html)
        self.assertIn('name="plaintiff_type_custom" value="Decree holder"', html)

    def test_a_failed_save_shows_the_typed_custom_again(self):
        response = self.post("fees_matter_new", self.matter_post(name="", plaintiff_type_choice="__custom__", plaintiff_type_custom="Mine"))
        self.assertGreaterEqual(response.status_code, 400)
        self.assertContains(response, 'name="plaintiff_type_custom" value="Mine"', status_code=response.status_code)


class PartyTypeBackupTests(WriteBase):
    def test_excel_round_trip_keeps_edited_lists(self):
        settings_service.update_settings(self.profile, {"plaintiff_types": ["One", "Two words"], "defendant_types": []})
        out = export_workbook(self.profile)
        target = fees_profile("Party-Target")
        restore(target, out)
        out.close()
        config = settings_service.get_settings(target)
        self.assertEqual(config["plaintiff_types"], ["One", "Two words"])
        self.assertEqual(config["defendant_types"], [])

    def test_an_old_file_without_the_lists_keeps_the_defaults(self):
        target = fees_profile("Party-Old")
        settings_service.update_settings(target, {"plaintiff_types": ["Changed"]})
        sheets = minimal_sheets()
        sheets["WebSettings"] = [["key", "value"], ["list_default_filter", "active"]]
        restore(target, build_workbook(sheets))
        config = settings_service.get_settings(target)
        self.assertEqual(config["plaintiff_types"], PLAINTIFFS)
        self.assertEqual(config["defendant_types"], DEFENDANTS)

    def test_a_file_with_no_web_sheet_keeps_the_defaults(self):
        target = fees_profile("Party-Older")
        restore(target, build_workbook(minimal_sheets()))
        self.assertEqual(settings_service.get_settings(target)["plaintiff_types"], PLAINTIFFS)

    def test_a_messy_list_in_a_file_is_cleaned(self):
        target = fees_profile("Party-Messy")
        sheets = minimal_sheets()
        sheets["WebSettings"] = [["key", "value"], ["plaintiff_types", " A \n\na\nB\n" + "c" * 150]]
        restore(target, build_workbook(sheets))
        self.assertEqual(settings_service.get_settings(target)["plaintiff_types"], ["A", "B", "c" * 100])
