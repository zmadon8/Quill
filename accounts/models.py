import hashlib
import secrets
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
    # How the header bar shows its links (My settings): simple icons, or the words (round 15, D84).
    HEADER_ICONS, HEADER_WORDS = "icons", "words"
    HEADER_STYLE_CHOICES = [(HEADER_ICONS, "Icons"), (HEADER_WORDS, "Words")]
    header_style = models.CharField(max_length=10, choices=HEADER_STYLE_CHOICES, default=HEADER_ICONS)
    # Diary round (1.5): justify the text that is normally left-aligned. On screen only; off unless chosen (My settings, Display).
    justify_text = models.BooleanField(default=False)
    # Owner round (2026-11): the Home button in the header bar can be hidden (My settings, Display). Home stays
    # reachable with the Alt+H (Option+H) shortcut and from a program's own links; on unless switched off.
    show_home_button = models.BooleanField(default=True)
    # Owner round (2026-11): the accent colour of every page, per user (My settings, Display; an Admin can set it too). Only the
    # accent changes (buttons, the current tab, links); status colours, the Word memo and the exports never do. tokens.css has one
    # html[data-theme] block per choice; the default, oxblood, needs none.
    THEME_OXBLOOD = "oxblood"
    COLOUR_THEME_CHOICES = [
        (THEME_OXBLOOD, "Oxblood"), ("royal", "Royal Blue"), ("navy", "Navy"), ("violet", "Violet"), ("plum", "Plum"), ("teal", "Teal"),
    ]
    colour_theme = models.CharField("Colour theme", max_length=10, choices=COLOUR_THEME_CHOICES, default=THEME_OXBLOOD)
    # Owner round (2026-11): the letters in the round name badge in the header (My settings, Display). Blank: the badge shows the
    # first letters of the first and last name, as before.
    header_initials = models.CharField("Header letters", max_length=3, blank=True, default="")
    # Owner round (2026-11): the period behind the Investments Overview cards (Gain, Portfolio XIRR, index XIRR, Alpha) and the
    # Portfolio XIRR on Home (My settings, Display). Keys match investments.services.chartview.PERIODS; "all" is the whole history.
    INVESTMENTS_PERIOD_CHOICES = [
        ("1m", "1M"), ("3m", "3M"), ("6m", "6M"), ("1y", "1Y"), ("3y", "3Y"), ("5y", "5Y"), ("all", "All"),
    ]
    investments_period = models.CharField("Investments period for returns", max_length=3, choices=INVESTMENTS_PERIOD_CHOICES, default="all")
    # Owner round (2026-11): the (up to 3) figures on each program's Home card, {"diary": [ids], "fees": [...], "investments": [...]}
    # (My settings, Display). A missing or empty list means that program's defaults; see accounts/home_cards.py.
    home_metrics = models.JSONField("Home card figures", default=dict, blank=True)
    # Owner round (2026-11): extra Dashboard / Overview items shown below the cards on Home, {"fees": [ids], "investments": [ids]}
    # (My settings, Display). Missing or empty means none; see accounts/home_cards.py.
    home_details = models.JSONField("Home page extras", default=dict, blank=True)
    # Owner round (2026-11): Case Law Diary display. On: no " - " between the Item text and its inline citations. Off (default): as before.
    remove_citation_hyphen = models.BooleanField("Remove the hyphen before the citation", default=False)
    # Who is active (round: markers, payments, activity). ``last_seen_at`` is touched by accounts.middleware at most once
    # a minute; ``can_see_active`` lets an Admin show this user the Active Now panel on Home (Admins always see it).
    last_seen_at = models.DateTimeField(null=True, blank=True)
    can_see_active = models.BooleanField("Can See Who Is Active", default=False)
    # Round 18 (D94): a deleted user is kept for USER_RETENTION_DAYS so an Admin can restore them. While deleted they
    # cannot sign in (is_active is off) and keep their username and email address; ``was_active`` is what Restore puts
    # back. Who deleted them is kept as a name (not a link), so a backup file never depends on the order users load in.
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by_name = models.CharField(max_length=150, blank=True, default="")
    was_active = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        self.is_staff = self.is_superuser
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"is_staff"}
        super().save(*args, **kwargs)

    @property
    def is_admin(self):
        return self.is_superuser

    @property
    def is_deleted(self):
        return self.deleted_at is not None


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
    name>" (and on the Home program button); blank means the program name is shown as before. It is the Home Page
    Name on the screens.
    ``header_name`` is an optional, usually shorter, name for the header of the program's pages; blank means the
    ``display_name`` is used there too. Hovering over the header name shows the full Home page name.
    ``reading_all_mode`` decides what the side-panel Contents links open: the whole Subject (``always_on``), only
    that Topic or Sub-topic (``always_off``), or the view each browser used last (``remember``).
    ``reading_all_default`` is whether the whole Subject is what those links open for a browser that has no
    remembered view yet, when ``reading_all_mode`` is "remember".
    """

    READING_ALL_ALWAYS_ON = "always_on"
    READING_ALL_ALWAYS_OFF = "always_off"
    READING_ALL_REMEMBER = "remember"
    READING_ALL_MODE_CHOICES = [
        (READING_ALL_ALWAYS_ON, "The Whole Subject"),
        (READING_ALL_ALWAYS_OFF, "Only That Topic Or Sub-topic"),
        (READING_ALL_REMEMBER, "The View I Used Last"),
    ]

    program = models.CharField(max_length=30)
    name = models.CharField(max_length=60)
    export_name = models.CharField(max_length=100, blank=True, default="")
    display_name = models.CharField(max_length=DISPLAY_NAME_MAX_LENGTH, blank=True, default="")
    header_name = models.CharField(max_length=DISPLAY_NAME_MAX_LENGTH, blank=True, default="")
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

    def header_text(self):
        """The name for the program header: the Header Name, else the Home Page Name, else "" (program + profile)."""
        return " ".join((self.header_name or "").split()) or " ".join((self.display_name or "").split())

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
    """Gives one user access to one profile, as Editor or Reader (``role``).

    Round 18 (D95): a user may have several profiles in a program, each with its own role (one membership per user and
    profile). The one they are using is the membership used most recently (``last_used_at``, set when they switch);
    see ``accounts.profiles.get_membership_for``. ``program`` is copied from the profile on save. Several users may
    share a profile.

    When a profile is deleted its memberships are kept but ``suspended``: they give no access. Restoring the profile
    lifts the suspension.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile_memberships")
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="memberships")
    program = models.CharField(max_length=30)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_READER)
    suspended = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    # When the user last opened a page of this profile (accounts.middleware, at most once a minute), for the Active Now
    # panel on Home: someone working in a Case Law Diary profile and a Fee Register profile shows both.
    last_seen_at = models.DateTimeField(null=True, blank=True)
    # True for a membership made only to record which profile an Admin opened through Admin Profile Access (an Admin
    # may open any profile). Such a profile was not given to them on the Users screen, so Home does not list it.
    admin_access = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "profile"], name="membership_one_per_user_and_profile"),
        ]

    def save(self, *args, **kwargs):
        self.program = self.profile.program
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"program"}
        super().save(*args, **kwargs)

    @property
    def is_explicit(self):
        """True for a profile given to the user on the Users screen (not an Admin's stand-in or Admin Profile Access)."""
        return bool(self.pk) and not self.admin_access

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


def hash_token(token):
    """sha256 hex of an offline-link token (what the public page looks the link up by)."""
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


class OfflineLink(models.Model):
    """Round 21 (D100): the secret, password-less link that downloads one profile's saved Offline copy.

    One per profile, made by an Admin. The token is kept in plain text so the Admin can copy the link again; the public
    page finds the row by ``token_hash``. ``copy_data`` is the pre-made file (rebuilt by the Admin's button and by the
    nightly job, never by a visitor). Never included in backup files: it is derived data and the token is a secret.
    """

    profile = models.OneToOneField(Profile, on_delete=models.CASCADE, related_name="offline_link")
    token = models.CharField(max_length=64)
    token_hash = models.CharField(max_length=64, unique=True)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    # The Admin who made or renewed the link or last pressed "Make a copy now": their formats are used for the file.
    made_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    copy_data = models.BinaryField(null=True, blank=True)
    copy_name = models.CharField(max_length=255, blank=True)
    copy_made_at = models.DateTimeField(null=True, blank=True)
    copy_items = models.PositiveIntegerField(default=0)
    copy_size = models.PositiveIntegerField(default=0)
    # The last failed refresh (plain words), shown to the Admin; blank after a good one.
    copy_error = models.CharField(max_length=300, blank=True)

    def new_token(self):
        """Set a fresh random token (and its hash). The caller saves."""
        self.token = secrets.token_urlsafe(32)
        self.token_hash = hash_token(self.token)

    @property
    def has_copy(self):
        return self.copy_made_at is not None and self.copy_size > 0

    def __str__(self):
        return f"offline link of profile {self.profile_id}"


class OfflineDownload(models.Model):
    """One counted download of a saved Offline copy, used to limit downloads per visitor and per link. Short-lived."""

    link = models.ForeignKey(OfflineLink, on_delete=models.CASCADE)
    ip = models.CharField(max_length=64, blank=True)
    at = models.DateTimeField(db_index=True)

    def __str__(self):
        return f"{self.link_id} at {self.at:%Y-%m-%d %H:%M:%S}"


def forget_copy(profile):
    """Erase the saved copy of ``profile`` (the link itself stays). Used by Delete all data."""
    OfflineLink.objects.filter(profile=profile).update(
        copy_data=None, copy_name="", copy_made_at=None, copy_items=0, copy_size=0, copy_error=""
    )


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


def prune_offline_downloads(now=None, max_age=timedelta(days=1)):
    """Delete download-count rows older than ``max_age``. Returns the number removed."""
    now = now or timezone.now()
    deleted, _ = OfflineDownload.objects.filter(at__lt=now - max_age).delete()
    return deleted
