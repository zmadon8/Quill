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
    ``landing_program`` is the program key (see ``accounts.suite``) the user lands in after signing in;
    blank means the Home page.
    """

    landing_program = models.CharField(max_length=30, blank=True, default="")
    # Last Case Law Diary page viewed (path and query), used by the "last page I viewed" opening option.
    last_diary_path = models.CharField(max_length=500, blank=True, default="")

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


#: Longest Profile.display_name.
DISPLAY_NAME_MAX_LENGTH = 80


class Profile(models.Model):
    """A separate data space inside one program, like a separate notebook.

    For example "Madon - Case Law" and "Junior - Case Law" are two profiles of the Case Law Diary
    (program key ``diary``). Each holds its own Subjects and Items; nothing is shared between
    profiles. Names are unique per program among profiles that are not deleted, ignoring case.
    Deleting only sets ``deleted_at`` (and ``deleted_by``); the profile can be restored until the
    purge job removes it for good after the retention period (``PROFILE_RETENTION_DAYS``).
    ``export_name`` is the name this profile's exported files start with; blank means the default
    "<program name> <profile name>" (see ``accounts.profiles.effective_export_name``).
    ``display_name`` is an optional name shown at the top of the program's pages instead of "<program name> · <profile
    name>" (and on the Home program button); blank means the program name is shown as before.
    ``reading_all_mode`` decides what the side-panel Contents links open: the whole Subject (``always_on``), only
    that Topic or Sub-topic (``always_off``), or the view each browser used last (``remember``).
    ``reading_all_default`` is whether the whole Subject is what those links open for a browser that has no
    remembered view yet, when ``reading_all_mode`` is "remember".
    """

    READING_ALL_ALWAYS_ON = "always_on"
    READING_ALL_ALWAYS_OFF = "always_off"
    READING_ALL_REMEMBER = "remember"
    READING_ALL_MODE_CHOICES = [
        (READING_ALL_ALWAYS_ON, "The whole Subject"),
        (READING_ALL_ALWAYS_OFF, "Only that Topic or Sub-topic"),
        (READING_ALL_REMEMBER, "The view I used last"),
    ]

    program = models.CharField(max_length=30)
    name = models.CharField(max_length=60)
    export_name = models.CharField(max_length=100, blank=True, default="")
    display_name = models.CharField(max_length=DISPLAY_NAME_MAX_LENGTH, blank=True, default="")
    reading_all_default = models.BooleanField(default=True)
    reading_all_mode = models.CharField(
        max_length=10, choices=READING_ALL_MODE_CHOICES, default=READING_ALL_REMEMBER
    )
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


class ResetRequest(models.Model):
    """One "Forgot my password" request, used to limit how many reset emails one address or visitor can cause.

    Short-lived and never included in backup files (like FailedLogin). The address is kept lower-cased.
    """

    email_lower = models.CharField(max_length=254, db_index=True)
    ip = models.CharField(max_length=64, blank=True)
    at = models.DateTimeField(db_index=True)

    def __str__(self):
        return f"{self.email_lower} at {self.at:%Y-%m-%d %H:%M:%S}"


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


def prune_reset_requests(now=None, max_age=timedelta(days=1)):
    """Delete reset-request rows older than ``max_age``. Returns the number removed."""
    now = now or timezone.now()
    deleted, _ = ResetRequest.objects.filter(at__lt=now - max_age).delete()
    return deleted
