from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import (
    ROLE_ADMIN,
    ROLE_CHOICES,
    ROLE_READER,
    FailedLogin,
    prune_failed_logins,
)

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


class UserCreateForm(UserCreationForm):
    role = forms.ChoiceField(
        choices=ROLE_CHOICES,
        initial=ROLE_READER,
        label="Role",
        help_text="Reader: view only. Editor: view and edit. Admin: everything, including users and backups.",
    )

    class Meta:
        model = User
        fields = ("username",)

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_role(self.cleaned_data["role"])
        if commit:
            user.save()
        return user


class UserEditForm(forms.ModelForm):
    role = forms.ChoiceField(
        choices=ROLE_CHOICES,
        label="Role",
        help_text="Reader: view only. Editor: view and edit. Admin: everything, including users and backups.",
    )
    new_password = forms.CharField(
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        label="New password (leave blank to keep the current one)",
    )

    class Meta:
        model = User
        fields = ("username", "is_active")

    def __init__(self, *args, editing_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.editing_user = editing_user
        self.fields["role"].initial = self.instance.role

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
        is_admin = cleaned.get("role") == ROLE_ADMIN
        target = self.instance
        if self.editing_user is not None and target.pk == self.editing_user.pk and not is_active:
            raise ValidationError("You cannot disable your own account.")
        was_active_admin = target.is_active and target.is_superuser
        stays_active_admin = is_active and is_admin
        if was_active_admin and not stays_active_admin:
            others = User.objects.filter(is_superuser=True, is_active=True).exclude(pk=target.pk)
            if not others.exists():
                raise ValidationError(
                    "This is the last active Admin. It cannot be disabled or lose the Admin role."
                )
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_role(self.cleaned_data["role"])
        if self.cleaned_data.get("new_password"):
            user.set_password(self.cleaned_data["new_password"])
        if commit:
            user.save()
        return user
