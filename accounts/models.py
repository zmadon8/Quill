from datetime import timedelta

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

ROLE_ADMIN = "admin"
ROLE_EDITOR = "editor"
ROLE_READER = "reader"
ROLE_CHOICES = [
    (ROLE_ADMIN, "Admin"),
    (ROLE_EDITOR, "Editor"),
    (ROLE_READER, "Reader"),
]
ROLE_VALUES = [value for value, _label in ROLE_CHOICES]


def normalise_role(role, is_superuser):
    """Return a consistent ``(role, is_superuser)`` pair.

    The Admin role and Django's ``is_superuser`` flag always go together. If
    either says Admin, the result is Admin. An unknown or missing role becomes
    Reader (the safe default).
    """
    if is_superuser or role == ROLE_ADMIN:
        return ROLE_ADMIN, True
    if role not in ROLE_VALUES:
        return ROLE_READER, False
    return role, False


class User(AbstractUser):
    """Application user with one of three roles: Admin, Editor or Reader.

    Admin is tied to Django's ``is_superuser`` flag, and ``save()`` keeps the two
    in step (``is_staff`` follows too). To change someone's role, call
    ``set_role()``; it moves both. New accounts are Readers unless told otherwise.
    """

    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_READER)

    def set_role(self, role):
        self.role, self.is_superuser = normalise_role(role, False)
        self.is_staff = self.is_superuser

    def save(self, *args, **kwargs):
        self.role, self.is_superuser = normalise_role(self.role, self.is_superuser)
        self.is_staff = self.is_superuser
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"role", "is_superuser", "is_staff"}
        super().save(*args, **kwargs)

    @property
    def is_admin(self):
        return self.is_superuser

    @property
    def is_editor(self):
        """True for Editors and Admins (anyone who may change diary data)."""
        return self.is_superuser or self.role == ROLE_EDITOR

    @property
    def role_label(self):
        return dict(ROLE_CHOICES).get(self.role, self.role)


class FailedLogin(models.Model):
    """One failed login attempt, used to rate limit logins per username."""

    username_lower = models.CharField(max_length=150, db_index=True)
    ip = models.CharField(max_length=64, blank=True)
    at = models.DateTimeField(db_index=True)

    def __str__(self):
        return f"{self.username_lower} at {self.at:%Y-%m-%d %H:%M:%S}"


def prune_failed_logins(now=None, max_age=timedelta(days=1)):
    """Delete failed-login rows older than ``max_age``. Returns the number removed."""
    now = now or timezone.now()
    deleted, _ = FailedLogin.objects.filter(at__lt=now - max_age).delete()
    return deleted
