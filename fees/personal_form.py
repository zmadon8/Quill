"""The two personal Fee Register choices on My settings: Opening page and Items per page (stored per user, per profile)."""
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
    """Blank means "use the profile's choice" (then the standard one)."""

    default_tab = forms.ChoiceField(required=False, label="Opening page")
    items_per_page = forms.CharField(required=False, max_length=10, label="Items per page")

    def __init__(self, *args, profile, user, fees_settings, **kwargs):
        super().__init__(*args, **kwargs)
        self.profile = profile
        self.user = user
        shared = getattr(fees_settings, "default_tab", "") or "memos"
        names = dict(OPENING_PAGES)
        self.fields["default_tab"].choices = [("", f"Same as the profile ({names.get(shared, shared)})")] + list(OPENING_PAGES)
        self.fields["items_per_page"].widget.attrs.update({"size": 8, "inputmode": "numeric"})
        self.fields["items_per_page"].help_text = "A number, or All."
        self.profile_items = getattr(fees_settings, "items_per_page", 50)
        if not self.is_bound:
            own = prefs.get_personal(profile, user)
            self.initial = {
                "default_tab": own.get("default_tab", ""),
                "items_per_page": "" if "items_per_page" not in own else ("All" if own["items_per_page"] == 0 else str(own["items_per_page"])),
            }

    def clean_items_per_page(self):
        text = (self.cleaned_data.get("items_per_page") or "").strip()
        if not text:
            return None
        try:
            return settings_service._validate_candidate("items_per_page", text)
        except FeesError as err:
            raise forms.ValidationError(err.message) from err

    def clean_default_tab(self):
        return self.cleaned_data.get("default_tab") or None

    def save(self):
        return prefs.set_personal(self.profile, self.user, {
            "default_tab": self.cleaned_data["default_tab"],
            "items_per_page": self.cleaned_data["items_per_page"],
        })
