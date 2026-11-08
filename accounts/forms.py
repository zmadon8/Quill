from datetime import timedelta

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.template import loader
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, UserCreationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from . import landing, programs, suite
from .models import (
    ROLE_CHOICES,
    FailedLogin,
    Profile,
    prune_failed_logins,
)
from .profiles import live_memberships, set_user_profiles

User = get_user_model()

MAX_FAILED_ATTEMPTS = 5  # per username from one IP address
MAX_FAILED_PER_IP = 20  # from one IP address, any username
MAX_USERNAME_LENGTH = 150  # longer strings cannot be real usernames and are not recorded
LOCKOUT_MINUTES = 15
THROTTLE_MESSAGE = "Too many failed attempts. Try again in 15 minutes."


def _client_ip(request):
    if request is None:
        return ""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip = forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR", "")
    return ip[:64]


class ThrottledAuthenticationForm(AuthenticationForm):
    remember_me = forms.BooleanField(
        required=False,
        label="Remember me",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["remember_me"].help_text = (
            f"Stay signed in on this device for {settings.REMEMBER_ME_DAYS} days. Leave unticked on a shared computer."
        )

    def _is_throttled(self, username_lower, ip):
        """Keyed on username plus IP, so a stranger elsewhere cannot lock the owner out."""
        since = timezone.now() - timedelta(minutes=LOCKOUT_MINUTES)
        recent = FailedLogin.objects.filter(ip=ip, at__gte=since)
        if recent.count() >= MAX_FAILED_PER_IP:
            return True
        return bool(username_lower) and recent.filter(username_lower=username_lower).count() >= MAX_FAILED_ATTEMPTS

    def clean(self):
        username = (self.cleaned_data.get("username") or "").strip().lower()
        ip = _client_ip(self.request)
        if self._is_throttled(username, ip):
            raise ValidationError(THROTTLE_MESSAGE, code="throttled")
        try:
            cleaned = super().clean()
        except ValidationError:
            prune_failed_logins()
            if username and len(username) <= MAX_USERNAME_LENGTH:
                FailedLogin.objects.create(username_lower=username, ip=ip, at=timezone.now())
            raise
        if username:
            FailedLogin.objects.filter(username_lower=username).delete()
        return cleaned


#: Round 18 (D95): each live profile gets one choice on the user form, so a user may have several (each with its role).
PROFILE_ACCESS_CHOICES = [("", "No access")] + ROLE_CHOICES
PROFILE_FIELD_PREFIX = "profile_"


class ProfileAccessMixin:
    """Adds one "No access / Editor / Reader" field per live Case Law Diary profile (named ``profile_<pk>``)."""

    def _add_profile_fields(self, current=None):
        current = current or {}
        self.access_profiles = list(_live_profiles())
        # Other enabled programs (the Fee Register) get their own profile choices after the diary's.
        for key in programs.enabled_program_keys():
            if key != suite.KEY_DIARY:
                self.access_profiles.extend(_live_profiles(key))
        for profile in self.access_profiles:
            self.fields[f"{PROFILE_FIELD_PREFIX}{profile.pk}"] = forms.ChoiceField(
                choices=PROFILE_ACCESS_CHOICES, required=False, label=profile.name,
                initial=current.get(profile.pk, ""),
            )

    def profile_fields(self):
        """The Case Law Diary per-profile fields, for the template (in profile name order)."""
        return [self[f"{PROFILE_FIELD_PREFIX}{p.pk}"] for p in self.access_profiles if p.program == suite.KEY_DIARY]

    def program_profile_groups(self):
        """[(program name, [fields])] for each other program that has live profiles (the Fee Register)."""
        names = suite.get_names()
        groups = []
        for key in programs.enabled_program_keys():
            if key == suite.KEY_DIARY:
                continue
            fields = [self[f"{PROFILE_FIELD_PREFIX}{p.pk}"] for p in self.access_profiles if p.program == key]
            groups.append((names.get(key, key), fields))
        return groups

    def other_fields(self):
        """Every other field, in form order."""
        names = {f"{PROFILE_FIELD_PREFIX}{p.pk}" for p in self.access_profiles}
        return [field for field in self if field.name not in names]

    def chosen_roles(self, program=suite.KEY_DIARY):
        """{profile: role} for every profile of ``program`` given Editor or Reader."""
        roles = {}
        for profile in self.access_profiles:
            if profile.program != program:
                continue
            role = self.cleaned_data.get(f"{PROFILE_FIELD_PREFIX}{profile.pk}") or ""
            if role:
                roles[profile] = role
        return roles

    def save_profile_access(self, user):
        """Store the chosen roles, one program at a time (a user's profiles of one program are replaced together)."""
        for key in programs.enabled_program_keys():
            set_user_profiles(user, self.chosen_roles(key), key)


def _admin_field():
    return forms.BooleanField(
        required=False,
        label="Admin",
        help_text="Admins manage users, profiles, settings and backups. Their role inside each profile is set above.",
    )


def _landing_field(programs=None):
    return forms.ChoiceField(
        choices=landing.program_choices(programs),
        required=False,
        label="Open after login",
    )


def _live_profiles(program=suite.KEY_DIARY):
    """Live profiles of ``program`` in name order (the default program is the diary, as before)."""
    return Profile.objects.filter(program=program, deleted_at__isnull=True).order_by("name")


def _clean_unique_email(form):
    """A blank email is fine; a used one is refused (ignoring case) so that a reset link goes to one person only."""
    email = (form.cleaned_data.get("email") or "").strip()
    if email and User.objects.filter(email__iexact=email).exclude(pk=form.instance.pk).exists():
        raise ValidationError("Another account already uses this email address.")
    return email


class UserCreateForm(ProfileAccessMixin, UserCreationForm):
    is_admin = _admin_field()

    class Meta:
        model = User
        fields = ("username", "email", "can_see_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].help_text = "Optional. Needed for \u201cForgot my password\u201d and for emailed backups."
        self._add_profile_fields()

    def clean_email(self):
        return _clean_unique_email(self)

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_superuser = bool(self.cleaned_data.get("is_admin"))
        if commit:
            with transaction.atomic():
                user.save()
                self.save_profile_access(user)
        return user


class UserEditForm(ProfileAccessMixin, forms.ModelForm):
    new_password = forms.CharField(
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        label="New password (leave blank to keep the current one)",
    )

    is_admin = _admin_field()
    landing_program = forms.ChoiceField(required=False, label="Open after login")

    class Meta:
        model = User
        fields = ("username", "email", "is_active", "landing_program", "can_see_active")

    def clean_email(self):
        return _clean_unique_email(self)

    def __init__(self, *args, editing_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].help_text = "Optional. Needed for \u201cForgot my password\u201d."
        self.fields["landing_program"].choices = landing.program_choices()
        self.editing_user = editing_user
        self.fields["is_admin"].initial = self.instance.is_superuser
        # Stored roles of every program (the diary and the Fee Register), not the Admin-everywhere view.
        self._add_profile_fields(
            {m.profile_id: m.role for m in live_memberships(self.instance, None, raw=True) if not m.admin_access}
        )

    def clean_new_password(self):
        password = self.cleaned_data.get("new_password")
        if password:
            validate_password(password, self.instance)
        return password

    def clean(self):
        cleaned = super().clean()
        if "is_active" not in cleaned:
            return cleaned
        is_active = cleaned["is_active"]
        is_admin = bool(cleaned.get("is_admin"))
        target = self.instance
        if self.editing_user is not None and target.pk == self.editing_user.pk and not is_active:
            raise ValidationError("You cannot disable your own account.")
        was_active_admin = target.is_active and target.is_superuser
        stays_active_admin = is_active and is_admin
        if was_active_admin and not stays_active_admin:
            others = User.objects.filter(is_superuser=True, is_active=True).exclude(pk=target.pk)
            if not others.exists():
                raise ValidationError(
                    "This is the last active Admin. It cannot be disabled or lose the Admin flag."
                )
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_superuser = bool(self.cleaned_data.get("is_admin"))
        if self.cleaned_data.get("new_password"):
            user.set_password(self.cleaned_data["new_password"])
        if commit:
            with transaction.atomic():
                user.save()
                self.save_profile_access(user)
        return user


class MySettingsForm(forms.ModelForm):
    """What a signed-in user may change about themselves: where to land after login."""

    landing_program = forms.ChoiceField(required=False, label="Open after login")

    class Meta:
        model = User
        fields = ("email", "landing_program", "justify_text")
        labels = {"justify_text": "Justify text"}

    def clean_email(self):
        return _clean_unique_email(self)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "email" in self.fields:
            self.fields["email"].help_text = "Used only to email you a link if you forget your password."
        if "justify_text" in self.fields:
            self.fields["justify_text"].required = False
            self.fields["justify_text"].help_text = (
                "Lines up the right-hand edge of the text of Items, Sections and Notes on screen. Off: the text is left-aligned. "
                "The Word export is not affected."
            )
        self.fields["landing_program"].choices = landing.program_choices(landing.programs_for(self.instance))


class MyAccountForm(MySettingsForm):
    """The Account section of My settings: the email address only."""

    class Meta(MySettingsForm.Meta):
        fields = ("email",)


class MyDisplayForm(MySettingsForm):
    """The Display section of My settings: where to land after login and justified text."""

    class Meta(MySettingsForm.Meta):
        fields = ("landing_program", "justify_text")


class ProfileForm(forms.ModelForm):
    """Create or rename a profile, and set its Home Page Name and Header Name. Names are unique among live profiles of the
    same program, ignoring case.

    A new profile belongs to ``program`` (the diary by default). When the Fee Register is switched on, creating
    one offers a Program select (Case Law Diary or Fee Register); with only the diary the form is as before.
    Editing or restoring keeps the profile's own program.
    """

    field_order = ["program", "name", "display_name", "header_name"]

    def __init__(self, *args, program=suite.KEY_DIARY, **kwargs):
        super().__init__(*args, **kwargs)
        self.program = self.instance.program if self.instance.pk else program
        keys = programs.enabled_program_keys()
        if self.instance.pk or len(keys) < 2:
            del self.fields["program"]
        else:
            names = suite.get_names()
            self.fields["program"].choices = [(k, names.get(k, k)) for k in keys]
            self.fields["program"].initial = program

    # Not required: a post without a Program (the diary-only screen, older clients) creates a Case Law Diary profile.
    program = forms.ChoiceField(label="Program", choices=[], required=False)

    class Meta:
        model = Profile
        fields = ("name", "display_name", "header_name")
        labels = {"display_name": "Home Page Name", "header_name": "Header Name"}
        help_texts = {
            "display_name": "Optional. The name of this profile on the Home page (and in the browser tab). Leave blank to show the program name.",
            "header_name": "Optional. A shorter name for the header of the program's pages; pointing at it shows the Home Page Name. Leave blank to use the Home Page Name (or, if that is blank too, the program name and this profile's name).",
        }

    def clean_display_name(self):
        return " ".join((self.cleaned_data.get("display_name") or "").split())

    def clean_header_name(self):
        return " ".join((self.cleaned_data.get("header_name") or "").split())

    def clean_program(self):
        # A valid choice (enabled programs only), or the diary when none was posted; used by clean_name.
        self.program = self.cleaned_data.get("program") or suite.KEY_DIARY
        return self.program

    def clean_name(self):
        name = " ".join((self.cleaned_data.get("name") or "").split())
        if not name:
            raise ValidationError("Enter a name.")
        clash = Profile.objects.filter(program=self.program, name__iexact=name, deleted_at__isnull=True)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise ValidationError("A profile with this name already exists.")
        return name

    def save(self, commit=True):
        profile = super().save(commit=False)
        profile.program = self.program
        if commit:
            profile.save()
        return profile


#: The field label and the clash-message label for the Home page and each known program key. New programs
#: fall back to "<display name> name" / "<display name>" if not listed here, so the form keeps working even
#: before a key is given a bespoke label.
SUITE_NAME_LABELS = {
    suite.KEY_HOME: ("Home page name", "Home page"),
    suite.KEY_DIARY: ("Case law diary name", "Case law diary"),
}


class SuiteNamesForm(forms.Form):
    """Rename the Home page and each registered program. Names are shared by every user.

    One text field is built per key: the Home page is always shown, and each program registered in
    ``accounts.programs`` gets a field. While a program (such as the Fee Register) is not yet registered
    it has no field here, so the screen stays exactly as before. The field for key ``k`` is named
    ``<k>_name`` (so ``home_name`` and ``diary_name`` keep their names and behaviour).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name_keys = self._name_keys()
        names = suite.get_names()
        for key in self.name_keys:
            field_name = self._field_name(key)
            label = SUITE_NAME_LABELS.get(key, (f"{names.get(key, key)} name", None))[0]
            self.fields[field_name] = forms.CharField(
                label=label, max_length=suite.MAX_NAME_LENGTH, initial=names.get(key, ""),
            )
        # Words or Logo for the header bar of Home and each program on offer (round 20, 3.1; the Fee Register only
        # while that program is switched on). Not posted: the current choice is kept.
        self.brand_keys = [suite.KEY_HOME, *programs.enabled_program_keys()]
        modes = suite.get_brand_modes()
        for key in self.brand_keys:
            self.fields[self._brand_field(key)] = forms.ChoiceField(
                label=f"{names.get(key, key)} header bar", required=False, initial=modes.get(key, suite.BRAND_WORDS),
                choices=[(suite.BRAND_WORDS, "Words"), (suite.BRAND_LOGO, "Logo")], widget=forms.RadioSelect,
                help_text="Words: Trash, Export, Help, Settings and the other items as words. Logo: as icons.",
            )

    @staticmethod
    def _name_keys():
        """The Home page followed by every registered program key."""
        return [suite.KEY_HOME, *programs.program_keys()]

    @staticmethod
    def _field_name(key):
        return f"{key}_name"

    @staticmethod
    def _brand_field(key):
        return f"{key}_brand"

    def _clash_label(self, key):
        """The human label used in the "same name as" message for ``key``."""
        bespoke = SUITE_NAME_LABELS.get(key)
        if bespoke is not None:
            return bespoke[1]
        return suite.get_names().get(key, key)

    def clean(self):
        cleaned = super().clean()
        seen = {}
        for key in self.name_keys:
            field = self._field_name(key)
            value = cleaned.get(field)
            if not value:
                continue
            folded = " ".join(value.split()).casefold()
            label = self._clash_label(key)
            if folded in seen:
                self.add_error(field, f"{label} cannot have the same name as {seen[folded]}.")
            else:
                seen[folded] = label
        return cleaned

    def save(self):
        suite.set_names(
            {key: " ".join(self.cleaned_data[self._field_name(key)].split()) for key in self.name_keys}
        )
        suite.set_brand_modes(
            {key: self.cleaned_data[self._brand_field(key)] for key in self.brand_keys
             if self.cleaned_data.get(self._brand_field(key))}
        )


class UsernamePasswordResetForm(PasswordResetForm):
    """Forgot my password, by USERNAME (round 17, D91): the link goes to the email address on that account.

    Django's form looks people up by email; this one takes a username instead and finds the one active account with it
    (capitals ignored) that has a password and an email address. Nobody else is told whether such an account exists.
    ``cleaned_data["email"]`` carries the username, because Django's ``save`` passes that value to ``get_users``.
    """

    email = None  # not asked for
    username = forms.CharField(label="Username", max_length=150,
                               widget=forms.TextInput(attrs={"autocomplete": "username", "autofocus": True,
                                                             "autocapitalize": "none", "spellcheck": "false"}))

    def clean(self):
        cleaned = super().clean()
        cleaned["email"] = (cleaned.get("username") or "").strip()
        return cleaned

    def get_users(self, username):
        user = User._default_manager.filter(username__iexact=(username or "").strip(), is_active=True).first()
        if user is not None and user.has_usable_password() and (user.email or "").strip():
            yield user

    def send_mail(self, subject_template_name, email_template_name, context, from_email, to_email, html_email_template_name=None):
        """Same as Django's, but From (and Reply-To) come from the shared helper, as for the backup emails."""
        from mailer import sender  # lazy: keeps this module's imports light

        # The website's own name (Madon.co.in), not the host name Django would put here.
        context = {**context, "site_name": sender.site_name()}
        subject = "".join(loader.render_to_string(subject_template_name, context).splitlines())
        message = sender.build_message(subject, loader.render_to_string(email_template_name, context), [to_email])
        if html_email_template_name is not None:
            from django.core.mail import EmailMultiAlternatives

            message = EmailMultiAlternatives(subject, message.body, message.from_email, [to_email], reply_to=message.reply_to)
            message.attach_alternative(loader.render_to_string(html_email_template_name, context), "text/html")
        message.send()

