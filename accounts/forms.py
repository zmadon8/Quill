from datetime import timedelta

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, UserCreationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from . import landing, suite
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
        self.access_profiles = list(_live_diary_profiles())
        for profile in self.access_profiles:
            self.fields[f"{PROFILE_FIELD_PREFIX}{profile.pk}"] = forms.ChoiceField(
                choices=PROFILE_ACCESS_CHOICES, required=False, label=profile.name,
                initial=current.get(profile.pk, ""),
            )

    def profile_fields(self):
        """The per-profile fields, for the template (in profile name order)."""
        return [self[f"{PROFILE_FIELD_PREFIX}{p.pk}"] for p in self.access_profiles]

    def other_fields(self):
        """Every other field, in form order."""
        names = {f"{PROFILE_FIELD_PREFIX}{p.pk}" for p in self.access_profiles}
        return [field for field in self if field.name not in names]

    def chosen_roles(self):
        """{profile: role} for every profile given Editor or Reader."""
        roles = {}
        for profile in self.access_profiles:
            role = self.cleaned_data.get(f"{PROFILE_FIELD_PREFIX}{profile.pk}") or ""
            if role:
                roles[profile] = role
        return roles


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


def _live_diary_profiles():
    return Profile.objects.filter(program=suite.KEY_DIARY, deleted_at__isnull=True).order_by("name")


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
        fields = ("username", "email")

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
                set_user_profiles(user, self.chosen_roles())
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
        fields = ("username", "email", "is_active", "landing_program")

    def clean_email(self):
        return _clean_unique_email(self)

    def __init__(self, *args, editing_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].help_text = "Optional. Needed for \u201cForgot my password\u201d."
        self.fields["landing_program"].choices = landing.program_choices()
        self.editing_user = editing_user
        self.fields["is_admin"].initial = self.instance.is_superuser
        self._add_profile_fields({m.profile_id: m.role for m in live_memberships(self.instance)})

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
                set_user_profiles(user, self.chosen_roles())
        return user


class MySettingsForm(forms.ModelForm):
    """What a signed-in user may change about themselves: where to land after login."""

    landing_program = forms.ChoiceField(required=False, label="Open after login")

    class Meta:
        model = User
        fields = ("email", "landing_program", "header_style")
        labels = {"header_style": "Header bar"}
        widgets = {"header_style": forms.RadioSelect}

    def clean_email(self):
        return _clean_unique_email(self)

    def clean_header_style(self):
        return self.cleaned_data.get("header_style") or self.instance.header_style or User.HEADER_ICONS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].help_text = "Used only to email you a link if you forget your password."
        self.fields["header_style"].required = False  # not posted: keep the current choice (see clean_header_style)
        self.fields["header_style"].help_text = (
            "Icons: Trash is a dustbin, Export a page with a W, Offline a downward arrow, Help a question mark, Settings a gear, and Search and "
            "Home their usual icons (hover or long-press to see the name). Words: the names instead."
        )
        self.fields["landing_program"].choices = landing.program_choices(landing.programs_for(self.instance))


class ProfileForm(forms.ModelForm):
    """Create or rename a Case Law Diary profile, and set its Display Name. Names are unique among live profiles, ignoring case."""

    class Meta:
        model = Profile
        fields = ("name", "display_name")
        labels = {"display_name": "Display Name"}
        help_texts = {
            "display_name": "Optional. Shown at the top of the program's pages instead of the program name. Leave blank to show the program name and this profile's name."
        }

    def clean_display_name(self):
        return " ".join((self.cleaned_data.get("display_name") or "").split())

    def clean_name(self):
        name = " ".join((self.cleaned_data.get("name") or "").split())
        if not name:
            raise ValidationError("Enter a name.")
        clash = Profile.objects.filter(program=suite.KEY_DIARY, name__iexact=name, deleted_at__isnull=True)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise ValidationError("A profile with this name already exists.")
        return name

    def save(self, commit=True):
        profile = super().save(commit=False)
        profile.program = suite.KEY_DIARY
        if commit:
            profile.save()
        return profile


class SuiteNamesForm(forms.Form):
    """Rename the Home page and each program. Names are shared by every user."""

    home_name = forms.CharField(label="Home page name", max_length=suite.MAX_NAME_LENGTH)
    diary_name = forms.CharField(label="Case law diary name", max_length=suite.MAX_NAME_LENGTH)

    FIELD_KEYS = {"home_name": suite.KEY_HOME, "diary_name": suite.KEY_DIARY}

    def clean(self):
        cleaned = super().clean()
        seen = {}
        for field, label in (("home_name", "Home page"), ("diary_name", "Case law diary")):
            value = cleaned.get(field)
            if not value:
                continue
            folded = " ".join(value.split()).casefold()
            if folded in seen:
                self.add_error(field, f"{label} cannot have the same name as {seen[folded]}.")
            else:
                seen[folded] = label
        return cleaned

    def save(self):
        suite.set_names(
            {key: " ".join(self.cleaned_data[field].split()) for field, key in self.FIELD_KEYS.items()}
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

