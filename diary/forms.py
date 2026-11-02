from django import forms

from accounts.models import Profile


class ProfileSettingsForm(forms.ModelForm):
    """Settings an Editor can change for their profile (the Display Name, the export file name and what the Contents links open)."""

    class Meta:
        model = Profile
        fields = ("display_name", "export_name", "reading_all_mode", "reading_all_default")
        labels = {
            "display_name": "Display Name",
            "export_name": "Export file name",
            "reading_all_mode": "Contents links open",
            "reading_all_default": "If there is no last view yet, Contents links open the whole Subject",
        }
        help_texts = {
            "display_name": "Shown at the top of every page instead of the program name. Leave blank to show the program name and the profile name.",
            "export_name": "Leave blank to use the default, for example Case Law Diary Main.",
            "reading_all_mode": "The Contents links in the side panel. Clicking a Topic or Sub-topic heading in the text always switches between the whole Subject and that one Topic or Sub-topic, whatever this says.",
            "reading_all_default": "Used only with \"The view I used last\", for a browser that has not read anything yet.",
        }

    def clean_display_name(self):
        return " ".join((self.cleaned_data.get("display_name") or "").split())

    def clean_export_name(self):
        return " ".join((self.cleaned_data.get("export_name") or "").split())
