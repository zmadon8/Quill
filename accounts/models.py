from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

ROLE_EDITOR = "editor"
ROLE_READER = "reader"
#: A role belongs to a user's membership of one profile (not to the user). Admin is a separate,
#: suite-wide flag on the user (``is_superuser``).
ROLE_CHOICES = [
    (ROLE_EDITOR, "Editor"),
    (ROLE_READER, "Reader"),
]
ROLE_VALUES = [value for value, _label in ROLE_CHOICES]


class User(AbstractUser):
    """Application user. Admin is a suite-wide flag; Editor or Reader is set per profile.

    Admin is tied to Django's ``is_superuser`` flag, and ``save()`` keeps ``is_staff`` in step.
    Admins manage users, profiles, settings and backups. What anyone may do inside a program
    (change data or only read it) comes from the role on their ``ProfileMembership`` for that
    program, Admins included. New accounts are not Admins.
    """

    def save(self, *args, **kwargs):
        self.is_staff = self.is_superuser
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"is_staff"}
        super().save(*args, **kwargs)

    @property
    def is_admin(self):
        return self.is_superuser


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
    Deleting only sets ``deleted_at`` (and ``deleted_by``); the profile can be restored until the
    purge job removes it for good after the retention period (``PROFILE_RETENTION_DAYS``).
    ``export_name`` is the name this profile's exported files start with; blank means the default
    "<program name> <profile name>" (see ``accounts.profiles.effective_export_name``).
    ``reading_all_default`` is whether the "All" tick on the reading pages starts ticked for this profile
    when the browser has no choice yet (no cookie and no saved value).
    """

    program = models.CharField(max_length=30)
    name = models.CharField(max_length=60)
    export_name = models.CharField(max_length=100, blank=True, default="")
    reading_all_default = models.BooleanField(default=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
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
    """Gives one user access to one profile, as Editor or Reader (``role``). One profile per program.

    ``program`` is copied from the profile on save so the database can enforce the rule
    "one profile per user per program". Several users may share a profile.

    When a profile is deleted its memberships are kept but ``suspended``: they give no access and
    do not count towards the one-profile rule, so the user can be given another profile meanwhile.
    Restoring the profile lifts the suspension (refused if that user has since been given another).
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile_memberships")
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="memberships")
    program = models.CharField(max_length=30)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_READER)
    suspended = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "program"],
                condition=Q(suspended=False),
                name="membership_one_profile_per_program",
            ),
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


class PurgeLog(models.Model):
    """One run of the job that permanently removes deleted profiles (Admin can read it).

    Never included in backup files themselves (like the backup log).
    """

    ran_at = models.DateTimeField(default=timezone.now)
    success = models.BooleanField(default=False)
    message = models.TextField(blank=True)
    #: Rows removed, by model label (empty when nothing was removed).
    counts = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"purge {'ok' if self.success else 'REFUSED'} at {self.ran_at:%Y-%m-%d %H:%M}"


def prune_failed_logins(now=None, max_age=timedelta(days=1)):
    """Delete failed-login rows older than ``max_age``. Returns the number removed."""
    now = now or timezone.now()
    deleted, _ = FailedLogin.objects.filter(at__lt=now - max_age).delete()
    return deleted
