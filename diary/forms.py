from django import forms

from accounts.models import Profile


class ProfileSettingsForm(forms.ModelForm):
    """Settings an Editor can change for their profile (the export file name and whether "All" starts ticked)."""

    class Meta:
        model = Profile
        fields = ("export_name", "reading_all_mode", "reading_all_default")
        labels = {
            "export_name": "Export file name",
            "reading_all_mode": '"All" starts',
            "reading_all_default": 'First-time "All" is ticked',
        }
        help_texts = {
            "export_name": "Leave blank to use the default, for example Case Law Diary Main.",
            "reading_all_mode": 'Always ticked or always unticked starts every page as set (ticking "All" still works until the next page). "Remember each user\'s choice" keeps what each browser last chose.',
            "reading_all_default": 'Used only with "Remember each user\'s choice", for a browser that has not chosen yet.',
        }

    def clean_export_name(self):
        return " ".join((self.cleaned_data.get("export_name") or "").split())
