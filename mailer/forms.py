from django import forms

from .models import KIND_GROUPS, KINDS, EmailBackupSchedule
from .services import check_recipients

#: Largest size the Admin may set for the files in one email.
MAX_LIMIT_MB = 100


#: Fields of kinds added after the page first existed (see ``__init__``).
LATER_FIELDS = ("archive_frequency", "archive_weekday", "archive_day_of_month", "archive_version",
                "invbook_frequency", "invbook_weekday", "invbook_day_of_month")


def _kind_fields():
    return [f"{kind}_{name}" for kind, _ in KINDS for name in ("enabled", "frequency", "weekday", "day_of_month")]


class EmailBackupForm(forms.ModelForm):
    recipients = forms.CharField(
        required=False, label="Send to", widget=forms.Textarea(attrs={"rows": 2}),
        help_text="One or more email addresses, separated by commas or new lines (at most 10).",
    )
    max_attachment_mb = forms.IntegerField(
        min_value=1, max_value=MAX_LIMIT_MB, initial=15, label="Most attachments in one email (MB)",
        help_text="Gmail refuses an email over 25 MB, and files grow by about a third when emailed, so 15 is safe for Gmail.",
    )

    class Meta:
        model = EmailBackupSchedule
        fields = ("enabled", "recipients", *_kind_fields(), "archive_version", "include_review", "split_emails", "max_attachment_mb")
        labels = {
            "enabled": "Send backups by email",
            "archive_version": "Price archive version (while old prices are not pruned)",
            "include_review": "Include the Flags in the Word and HTML copies",
            "split_emails": "Split into several emails when the files are larger than the limit below",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for kind, label in KINDS:
            self.fields[f"{kind}_enabled"].label = label
            self.fields[f"{kind}_frequency"].label = "How often"
            self.fields[f"{kind}_weekday"].label = "On"
            self.fields[f"{kind}_day_of_month"] = forms.IntegerField(
                min_value=1, max_value=28, initial=1, label="Day of the month",
                help_text="1 to 28, so every month has it.",
            )

        # The price archive and the Holdings and Transactions workbook (Investments) were added later: a post that leaves their fields out
        # (an older client, a test) keeps the current values.
        for name in LATER_FIELDS:
            self.fields[name].required = False

    def _clean_archive_defaults(self, cleaned):
        for name in LATER_FIELDS:
            if cleaned.get(name) in (None, "") and name not in self.errors:
                cleaned[name] = getattr(self.instance, name)
        return cleaned

    def kind_rows(self):
        """One row per kind of file for the page, under the program it belongs to: the program heading, the label and the four bound fields."""
        from accounts.suite import get_names

        names = get_names()
        rows = []
        for program, kinds in KIND_GROUPS:
            heading = "Whole website" if program == "suite" else names.get(program, program)
            for kind, label in kinds:
                rows.append({"key": kind, "group": heading, "label": label, "enabled": self[f"{kind}_enabled"], "frequency": self[f"{kind}_frequency"],
                             "weekday": self[f"{kind}_weekday"], "day_of_month": self[f"{kind}_day_of_month"]})
        return rows

    def clean_recipients(self):
        addresses, error = check_recipients(self.cleaned_data.get("recipients", ""))
        if error:
            raise forms.ValidationError(error)
        return ", ".join(addresses)

    def clean(self):
        cleaned = self._clean_archive_defaults(super().clean())
        if cleaned.get("enabled"):
            if not cleaned.get("recipients") and "recipients" not in self.errors:
                self.add_error("recipients", "Add at least one email address, or untick \u201cSend backups by email\u201d.")
            if not any(cleaned.get(f"{kind}_enabled") for kind, _ in KINDS):
                self.add_error(None, "Tick at least one kind of file to send, or untick \u201cSend backups by email\u201d.")
        return cleaned
