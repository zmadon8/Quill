from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
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


class SuiteName(models.Model):
    """A display name shared by every user: the Home page or one program in the suite.

    Only the name people see is stored. Internal identifiers (the ``diary`` app, URL names)
    never change. A missing row means the built-in default from ``accounts.suite`` is used.
    """

    key = models.CharField(max_length=30, unique=True)
    display_name = models.CharField(max_length=60)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.key}: {self.display_name}"


class Profile(models.Model):
    """A separate data space inside one program, like a separate notebook.

    For example "Madon - Case Law" and "Junior - Case Law" are two profiles of the Case Law Diary
    (program key ``diary``). Each holds its own Subjects and Items; nothing is shared between
    profiles. Names are unique per program among profiles that are not deleted, ignoring case.
    Deleting only sets ``deleted_at``.
    """

    program = models.CharField(max_length=30)
    name = models.CharField(max_length=60)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=~Q(name=""), name="profile_name_not_blank"),
            models.UniqueConstraint(
                Lower("name"),
                "program",
                condition=Q(deleted_at__isnull=True),
                name="profile_name_unique_live",
            ),
        ]

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    def __str__(self):
        return self.name


class ProfileMembership(models.Model):
    """Gives one user access to one profile. A user has at most one profile per program.

    ``program`` is copied from the profile on save so the database can enforce the rule
    "one profile per user per program". Several users may share a profile.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile_memberships")
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="memberships")
    program = models.CharField(max_length=30)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "program"], name="membership_one_profile_per_program"),
        ]

    def save(self, *args, **kwargs):
        self.program = self.profile.program
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"program"}
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user_id} in {self.profile_id} ({self.program})"


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
