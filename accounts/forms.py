from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import FailedLogin

User = get_user_model()

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15
THROTTLE_MESSAGE = "Too many failed attempts. Try again in 15 minutes."


def _client_ip(request):
    if request is None:
        return ""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip = forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR", "")
    return ip[:64]


class ThrottledAuthenticationForm(AuthenticationForm):
    def _recent_failures(self, username_lower):
        since = timezone.now() - timedelta(minutes=LOCKOUT_MINUTES)
        return FailedLogin.objects.filter(username_lower=username_lower, at__gte=since)

    def clean(self):
        username = (self.cleaned_data.get("username") or "").strip().lower()
        if username and self._recent_failures(username).count() >= MAX_FAILED_ATTEMPTS:
            raise ValidationError(THROTTLE_MESSAGE, code="throttled")
        try:
            cleaned = super().clean()
        except ValidationError:
            if username:
                FailedLogin.objects.create(
                    username_lower=username,
                    ip=_client_ip(self.request),
                    at=timezone.now(),
                )
            raise
        if username:
            FailedLogin.objects.filter(username_lower=username).delete()
        return cleaned


class UserCreateForm(UserCreationForm):
    is_admin = forms.BooleanField(required=False, label="Admin")

    class Meta:
        model = User
        fields = ("username",)

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_superuser = self.cleaned_data["is_admin"]
        user.is_staff = user.is_superuser
        if commit:
            user.save()
        return user


class UserEditForm(forms.ModelForm):
    is_admin = forms.BooleanField(required=False, label="Admin")
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
        self.fields["is_admin"].initial = self.instance.is_superuser

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
        is_admin = cleaned.get("is_admin", False)
        target = self.instance
        if self.editing_user is not None and target.pk == self.editing_user.pk and not is_active:
            raise ValidationError("You cannot disable your own account.")
        was_active_admin = target.is_active and target.is_superuser
        stays_active_admin = is_active and is_admin
        if was_active_admin and not stays_active_admin:
            others = User.objects.filter(is_superuser=True, is_active=True).exclude(pk=target.pk)
            if not others.exists():
                raise ValidationError(
                    "This is the last active Admin. It cannot be disabled or lose Admin rights."
                )
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_superuser = self.cleaned_data["is_admin"]
        user.is_staff = user.is_superuser
        if self.cleaned_data.get("new_password"):
            user.set_password(self.cleaned_data["new_password"])
        if commit:
            user.save()
        return user
