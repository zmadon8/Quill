from django import forms

from accounts.models import Profile


class ProfileSettingsForm(forms.ModelForm):
    """Settings an Editor can change for their profile (today only the export file name)."""

    class Meta:
        model = Profile
        fields = ("export_name",)
        labels = {"export_name": "Export file name"}
        help_texts = {"export_name": "Leave blank to use the default, for example Case Law Diary Main."}

    def clean_export_name(self):
        return " ".join((self.cleaned_data.get("export_name") or "").split())
