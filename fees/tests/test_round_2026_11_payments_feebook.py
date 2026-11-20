"""Owner round 2026-11: the payment form's memo rows and Mode drop-down, Feebook links and the Unaccounted tick box, Memos' Reset Filters."""
import re

from django.urls import reverse

from fees.models import FeesSettings, Payment
from fees.services import settings as settings_service
from fees.tests.test_ui_pages import UiPageBase
from fees.tests.test_views_write import WriteBase


class PaymentModeTests(WriteBase):
    def test_the_mode_is_a_drop_down_with_the_default_choices_and_custom(self):
        self.assertEqual(settings_service.get_settings(self.profile)["payment_modes"], ["RTGS", "NEFT", "Cheque", "UPI"])
        html = self.client.get(reverse("fees_payment_new")).content.decode()
        select = re.search(r'<select name="payment_mode_choice"[^>]*>(.*?)</select>', html, re.S).group(1)
        self.assertEqual(re.findall(r'<option value="([^"]*)"', select), ["", "RTGS", "NEFT", "Cheque", "UPI", "__custom__"])
        self.assertIn('name="payment_mode_custom"', html)
        self.assertIn("js/fees/party-type.js", html)

    def test_a_chosen_or_custom_mode_is_saved(self):
        base = {"amount": "500", "tds_rate": "0", "date_of_payment": "2026-09-01", "alloc_memo_0": ""}
        self.post("fees_payment_new", {**base, "payment_mode_choice": "UPI", "payment_mode_custom": ""})
        self.assertEqual(Payment.objects.filter(profile=self.profile).order_by("-pk").first().payment_mode, "UPI")
        self.post("fees_payment_new", {**base, "payment_mode_choice": "__custom__", "payment_mode_custom": "Demand draft"})
        self.assertEqual(Payment.objects.filter(profile=self.profile).order_by("-pk").first().payment_mode, "Demand draft")

    def test_the_list_is_edited_in_settings(self):
        page = self.client.get(reverse("fees_settings") + "?tab=payments").content.decode()
        self.assertIn('name="payment_modes"', page)
        self.post("fees_settings", {"tab": "payments", "payment_modes": "IMPS\r\nCash\r\n"})
        self.assertEqual(FeesSettings.objects.get(profile=self.profile).payment_modes, ["IMPS", "Cash"])


class FeebookTests(UiPageBase):
    def test_firm_and_matter_names_link_to_their_pages(self):
        text = self.html(self.page("fees_feebook"))
        body = text.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
        firm = self.seed["firm_a"]
        self.assertIn('href="%s"' % reverse("fees_firm_detail", args=[firm.pk]), body)
        self.assertRegex(body, r'href="/fees/matters/\d+/"')

    def test_unaccounted_only_is_on_the_bar_after_reset_filters(self):
        text = self.html(self.page("fees_feebook"))
        bar = text[text.index('class="filters"'):text.index("</form>", text.index('class="filters"'))]
        dialog = bar[bar.index("<dialog"):]
        self.assertNotIn('name="unaccounted"', dialog)
        self.assertLess(bar.index(">Reset Filters</a>"), bar.index('name="unaccounted"'))
        self.assertLess(bar.index('name="unaccounted"'), bar.index("<dialog"))
