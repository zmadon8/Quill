from django import forms

from accounts.models import Profile


class ProfileSettingsForm(forms.ModelForm):
    """Settings an Editor can change for their profile (the export file name and whether "All" starts ticked)."""

    class Meta:
        model = Profile
        fields = ("export_name", "reading_all_default")
        labels = {"export_name": "Export file name", "reading_all_default": 'Show "All" ticked by default'}
        help_texts = {
            "export_name": "Leave blank to use the default, for example Case Law Diary Main.",
            "reading_all_default": 'Whether "All" starts ticked on the reading pages. A choice made in a browser by ticking or unticking "All" is kept there and wins.',
        }

    def clean_export_name(self):
        return " ".join((self.cleaned_data.get("export_name") or "").split())
