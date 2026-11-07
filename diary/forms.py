from django import forms

from accounts.models import Profile

from .models import DATE_FORMAT_CHOICES, FORMAT_CHOICES, SECTION_FORMAT_CHOICES, Subject, UserSettings


#: The Display tab Yes/No toggle values (round 19, user item 4). Yes means clicking a Subject opens the whole
#: Subject; No means it opens the scoped Contents page with its "Read Whole Subject" button.
VIEW_WHOLE_YES = "yes"
VIEW_WHOLE_NO = "no"
VIEW_WHOLE_CHOICES = [(VIEW_WHOLE_YES, "Yes"), (VIEW_WHOLE_NO, "No")]


class ProfileSettingsForm(forms.ModelForm):
    """Settings an Editor can change for their profile: the Display Name and what the Contents links open (Settings >
    Display, round 18/19). The export file name is on the Export page (ExportSettingsForm).

    Round 19 (user item 4) has a plain Yes/No toggle on the Display tab, ``view_whole_subject``, as the only reading
    control: Yes means clicking a Subject opens the whole Subject (``reading_all_mode = always_on``), No means it
    opens the scoped Contents page with a "Read Whole Subject" button (``always_off``). The "The view I used last"
    (remember) choice and the ``reading_all_default`` checkbox are no longer offered. ``reading_all_mode`` now only
    ever becomes ``always_on`` or ``always_off`` from the toggle; an older row still on ``remember`` is shown as
    Yes/No (Yes if its ``reading_all_default`` is True, else No) and is mapped to ``always_on``/``always_off`` on its
    next save."""

    view_whole_subject = forms.ChoiceField(
        choices=VIEW_WHOLE_CHOICES,
        widget=forms.RadioSelect,
        label="When I click a Subject, open the whole Subject",
        help_text="Yes: clicking a Subject opens the whole Subject. No: it opens the Contents page with a "
                  "\"Read Whole Subject\" button.",
    )

    class Meta:
        model = Profile
        fields = ("display_name",)
        labels = {
            "display_name": "Display Name",
        }
        help_texts = {
            "display_name": "Shown at the top of every page instead of the program name. Leave blank to show the program name and the profile name.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            # The toggle reflects the saved mode: always_on -> Yes, always_off -> No. An older row still on the
            # "remember" mode (no longer offered) falls back to the effective default (reading_all_default), which is
            # still a model attribute on the instance even though it is no longer a form field.
            mode = self.instance.reading_all_mode
            if mode == Profile.READING_ALL_ALWAYS_ON:
                self.fields["view_whole_subject"].initial = VIEW_WHOLE_YES
            elif mode == Profile.READING_ALL_ALWAYS_OFF:
                self.fields["view_whole_subject"].initial = VIEW_WHOLE_NO
            else:
                self.fields["view_whole_subject"].initial = (
                    VIEW_WHOLE_YES if self.instance.reading_all_default else VIEW_WHOLE_NO
                )

    def clean_display_name(self):
        return " ".join((self.cleaned_data.get("display_name") or "").split())

    def save(self, commit=True):
        instance = super().save(commit=False)
        # The Yes/No toggle is the only reading control: it always decides the mode (remember is no longer offered).
        # reading_all_default is left untouched; it is simply no longer used by the UI.
        instance.reading_all_mode = (
            Profile.READING_ALL_ALWAYS_ON
            if self.cleaned_data.get("view_whole_subject") == VIEW_WHOLE_YES
            else Profile.READING_ALL_ALWAYS_OFF
        )
        if commit:
            instance.save()
        return instance



class ExportSettingsForm(forms.Form):
    """The export file name (Case Law Diary settings > Data). The file name belongs to the profile and only its Editors
    change it. The date format is the user's own and is set on My settings; this form still accepts it (blank leaves it
    as it is) so an older client that posts both keeps working."""

    export_name = forms.CharField(
        max_length=Profile._meta.get_field("export_name").max_length, required=False, label="Export file name",
        help_text="The start of every exported file name, for everyone using this profile. Leave blank for the default.",
    )
    export_date_format = forms.ChoiceField(
        choices=DATE_FORMAT_CHOICES, label="Date in Word file names", required=False,
        help_text="Your own choice: the date at the end of the file names you export, and on the front page. "
                  "The time zone is India (Asia/Kolkata, IST).",
    )

    def __init__(self, *args, user, profile, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.profile = profile
        if not self.is_bound:
            row = UserSettings.objects.filter(user=user).first() or UserSettings(user=user)
            self.initial = {"export_name": profile.export_name, "export_date_format": row.export_date_format}

    def clean_export_name(self):
        return " ".join((self.cleaned_data.get("export_name") or "").split())

    def save(self):
        if self.profile.export_name != self.cleaned_data["export_name"]:
            self.profile.export_name = self.cleaned_data["export_name"]
            self.profile.save(update_fields=["export_name", "updated_at"])
        chosen = self.cleaned_data.get("export_date_format")
        if not chosen:
            return
        row = UserSettings.objects.get_or_create(user=self.user)[0]
        if row.export_date_format != chosen:
            row.export_date_format = chosen
            row.save(update_fields=["export_date_format"])


#: Opening pages offered inside the Case Law Diary (the stored legacy value "other_subjects" is shown as "home").
OPENING_PAGE_OFFERED = [
    ("home", "Subjects (Index of Subjects)"),
    ("search", "Global Search"),
    ("last", "The last page I viewed"),
    ("subject", "A chosen Subject"),
]

#: Form field -> UserSettings column, for the five number formats.
FORMAT_FIELDS = (
    "topic_format", "subtopic_format", "section_format", "item_format", "multi_citation_format",
)


class DiarySettingsForm(forms.Form):
    """A user's own Case Law Diary settings: the page to open and the number formats.

    Every field is optional: a field that is not posted (or is posted empty) leaves the current value
    unchanged, so a form that posts only some fields never resets the others. A value that is posted
    but is not one of the choices is an error. Numbers are only ever shown differently; stored data is untouched.
    """

    opening_page = forms.ChoiceField(choices=OPENING_PAGE_OFFERED, required=False, label="Page inside the case law diary")
    opening_subject = forms.ModelChoiceField(
        queryset=Subject.objects.none(), required=False, empty_label="(choose a Subject)", label="Subject"
    )
    topic_format = forms.ChoiceField(choices=FORMAT_CHOICES, required=False, label="Topics")
    subtopic_format = forms.ChoiceField(choices=FORMAT_CHOICES, required=False, label="Sub-topics")
    section_format = forms.ChoiceField(choices=SECTION_FORMAT_CHOICES, required=False, label="Sections")
    item_format = forms.ChoiceField(choices=FORMAT_CHOICES, required=False, label="Items")
    multi_citation_format = forms.ChoiceField(
        choices=FORMAT_CHOICES, required=False, label="Citations of an Item with several"
    )
    export_date_format = forms.ChoiceField(
        choices=DATE_FORMAT_CHOICES, required=False, label="Date in Word file names"
    )

    def __init__(self, *args, user, profile, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.profile = profile
        # An unsaved row carries the model defaults, so a user without a row sees the standard formats.
        self.settings = UserSettings.objects.filter(user=user).first() or UserSettings(user=user)
        self.fields["opening_subject"].queryset = Subject.objects.filter(
            profile=profile, deleted_at__isnull=True
        ).order_by("name", "pk")
        for name in FORMAT_FIELDS:  # read by static/js/my-settings.js for "Use the standard formats"
            self.fields[name].widget.attrs["data-default"] = UserSettings._meta.get_field(name).default
        if not self.is_bound:
            self.initial = self.current()

    def current(self):
        """The saved values, as the form shows them."""
        row = self.settings
        values = {name: getattr(row, name) for name in FORMAT_FIELDS}
        values["opening_page"] = "home" if row.opening_page == "other_subjects" else row.opening_page
        values["opening_subject"] = row.opening_subject_id
        values["export_date_format"] = row.export_date_format
        return values

    def _posted(self, name):
        return self.data.get(name, "") != ""

    def clean(self):
        cleaned = super().clean()
        row = self.settings
        for name in ("opening_page", "export_date_format") + FORMAT_FIELDS:
            if name in self.errors:
                continue
            if not self._posted(name):
                cleaned[name] = self.current()[name]
        if "opening_subject" not in self.errors and "opening_subject" not in self.data:
            cleaned["opening_subject"] = (
                row.opening_subject if row.opening_subject_id and self.fields["opening_subject"].queryset.filter(
                    pk=row.opening_subject_id).exists() else None
            )
        if cleaned.get("opening_page") == "subject" and not cleaned.get("opening_subject") \
                and "opening_page" not in self.errors and "opening_subject" not in self.errors:
            self.add_error("opening_subject", "Choose a Subject to open, or pick another page.")
        return cleaned

    def effective(self):
        """Values to show on the page: the valid posted/cleaned ones, else the saved ones."""
        values = self.current()
        if self.is_bound:
            for name in ("opening_page",) + FORMAT_FIELDS:
                posted = self.data.get(name, "")
                if posted:
                    values[name] = posted
            if "opening_subject" in self.data:
                values["opening_subject"] = self.data.get("opening_subject") or None
        return values

    def save(self):
        row = UserSettings.objects.get_or_create(user=self.user)[0]
        for name in FORMAT_FIELDS:
            setattr(row, name, self.cleaned_data[name])
        page = self.cleaned_data["opening_page"]
        if not (page == "home" and row.opening_page == "other_subjects"):
            row.opening_page = page  # a stored legacy "other_subjects" stays unless another page is chosen
        row.opening_subject = self.cleaned_data["opening_subject"]
        row.export_date_format = self.cleaned_data["export_date_format"]
        row.save()
        return row


def allowed_formats():
    """For each ``*_format`` name, the set of format keys that may be chosen."""
    allowed = {name: {key for key, _label in FORMAT_CHOICES} for name in FORMAT_FIELDS}
    allowed["section_format"] = {key for key, _label in SECTION_FORMAT_CHOICES}
    return allowed


def preview_rows(chosen):
    """Sample rows (diary.preview) for ``chosen``, a mapping of ``*_format`` names to stored format names.

    A missing, junk or not-allowed value is replaced by the standard format, so any query string is safe.
    """
    from . import preview, reading

    allowed = allowed_formats()
    standard = {name: UserSettings._meta.get_field(name).default for name in FORMAT_FIELDS}
    formats = {}
    for key in preview.KEYS:
        name = f"{key}_format"
        value = chosen.get(name)
        if value not in allowed[name]:
            value = standard[name]
        formats[key] = reading.FORMAT_KEYS[value]
    return preview.build_preview(formats)
