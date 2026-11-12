"""The two personal Fee Register choices: Opening page (My settings > Start Screens) and Items per page (Fee Register > Settings >
Display), stored per user, per profile. A box that is not posted at all keeps its saved value."""
from django import forms

from fees.errors import FeesError
from fees.services import prefs
from fees.services import settings as settings_service

#: The pages offered as the Opening page, in the order of the Fee Register header.
OPENING_PAGES = (
    ("memos", "Memos"), ("dashboard", "Dashboard"), ("statistics", "Statistics"), ("firms", "Firms"),
    ("feebook", "Feebook"), ("outstanding", "Outstanding"), ("settings", "Settings"),
)


class FeesPersonalForm(forms.Form):
    """Blank means the standard choice (Memos; 50 items per page)."""

    default_tab = forms.ChoiceField(required=False, label="Opening page")
    items_per_page = forms.CharField(required=False, max_length=10, label="Items per page")

    def __init__(self, *args, profile, user, fees_settings, **kwargs):
        super().__init__(*args, **kwargs)
        self.profile = profile
        self.user = user
        # A switched-off Dashboard is not offered (the landing page would open Memos instead).
        offered = [c for c in OPENING_PAGES if c[0] != "dashboard" or getattr(fees_settings, "statistics_enabled", True)]
        self.fields["default_tab"].choices = [("", "Memos (standard)")] + offered
        self.fields["items_per_page"].widget.attrs.update({"size": 8, "inputmode": "numeric"})
        self.fields["items_per_page"].help_text = "A number, or All."
        if not self.is_bound:
            own = prefs.get_personal(profile, user)
            self.initial = {
                "default_tab": own.get("default_tab", ""),
                "items_per_page": "" if "items_per_page" not in own else ("All" if own["items_per_page"] == 0 else str(own["items_per_page"])),
            }

    def _unposted(self, name):
        return self.add_prefix(name) not in self.data

    def clean_items_per_page(self):
        if self._unposted("items_per_page"):
            return prefs.get_personal(self.profile, self.user).get("items_per_page")
        text = (self.cleaned_data.get("items_per_page") or "").strip()
        if not text:
            return None
        try:
            return settings_service._validate_candidate("items_per_page", text)
        except FeesError as err:
            raise forms.ValidationError(err.message) from err

    def clean_default_tab(self):
        if self._unposted("default_tab"):
            return prefs.get_personal(self.profile, self.user).get("default_tab")
        return self.cleaned_data.get("default_tab") or None

    def save(self):
        return prefs.set_personal(self.profile, self.user, {
            "default_tab": self.cleaned_data["default_tab"],
            "items_per_page": self.cleaned_data["items_per_page"],
        })
