from django import forms

from .models import EmailBackupSchedule
from .services import check_recipients


class EmailBackupForm(forms.ModelForm):
    day_of_month = forms.IntegerField(min_value=1, max_value=28, initial=1, label="Day of the month",
                                      help_text="1 to 28, so every month has it.")
    recipients = forms.CharField(
        required=False, label="Send to", widget=forms.Textarea(attrs={"rows": 2}),
        help_text="One or more email addresses, separated by commas or new lines (at most 10).",
    )

    class Meta:
        model = EmailBackupSchedule
        fields = ("enabled", "frequency", "weekday", "day_of_month", "recipients", "include_data", "include_word", "include_review")
        labels = {
            "enabled": "Send backups by email",
            "frequency": "How often",
            "weekday": "On",
            "include_data": "The full backup file (.json.gz) that can be restored on the Backups screen",
            "include_word": "The complete Word export (.docx) of each diary profile",
            "include_review": "Include For review markers in the Word file",
        }

    def clean_recipients(self):
        addresses, error = check_recipients(self.cleaned_data.get("recipients", ""))
        if error:
            raise forms.ValidationError(error)
        return ", ".join(addresses)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("enabled"):
            if not cleaned.get("recipients") and "recipients" not in self.errors:
                self.add_error("recipients", "Add at least one email address, or untick \u201cSend backups by email\u201d.")
            if not (cleaned.get("include_data") or cleaned.get("include_word")):
                raise forms.ValidationError("Tick the backup file, the Word file, or both.")
        return cleaned
