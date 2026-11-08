"""Settings for the Judgment Diary. All configuration comes from the environment."""
import os
import sys
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def _csv(name):
    return [item.strip() for item in os.environ.get(name, "").split(",") if item.strip()]


def _int(name, default):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be an integer") from exc


DEBUG = os.environ.get("DJANGO_DEBUG") == "1"

ALLOW_SQLITE = os.environ.get("DJANGO_ALLOW_SQLITE") == "1"

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    # DJANGO_ALLOW_SQLITE=1 is a local dev/test flag, so it also permits a throwaway key.
    if DEBUG or ALLOW_SQLITE:
        SECRET_KEY = "insecure-debug-only-key"
    else:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set (or DJANGO_DEBUG=1).")

RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()

ALLOWED_HOSTS = _csv("DJANGO_ALLOWED_HOSTS")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
if DEBUG and not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]", "testserver"]

CSRF_FAILURE_VIEW = "backups.views.csrf_failure"
CSRF_TRUSTED_ORIGINS = _csv("CSRF_TRUSTED_ORIGINS")
if RENDER_EXTERNAL_HOSTNAME:
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_EXTERNAL_HOSTNAME}")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "backups",
    "diary",
    "fees",
    "mailer",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "fees.middleware.FeesEnabledMiddleware",
    "accounts.middleware.LastSeenMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "accounts.context_processors.suite_names",
                "accounts.context_processors.current_profile",
                "accounts.context_processors.program_label",
                "accounts.context_processors.header_style",
                "accounts.context_processors.suite_nav",
                "backups.context_processors.backup_banner",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Database: PostgreSQL via DATABASE_URL. SQLite only for local dev and tests.
_database_url = os.environ.get("DATABASE_URL", "").strip()
if _database_url:
    # ssl_require is off: Render's internal database URL does not need it.
    DATABASES = {
        "default": dj_database_url.parse(_database_url, conn_max_age=600, ssl_require=False)
    }
elif DEBUG or ALLOW_SQLITE:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    raise ImproperlyConfigured(
        "DATABASE_URL must be set (or DJANGO_DEBUG=1 / DJANGO_ALLOW_SQLITE=1 for SQLite)."
    )

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Sessions live in the database; nothing is stored on local disk.
SESSION_ENGINE = "django.contrib.sessions.backends.db"
# "Remember me" on the login page keeps the session this many days; without it the session ends when the browser closes.
REMEMBER_ME_DAYS = max(1, _int("REMEMBER_ME_DAYS", 30))

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
# Generated at build time by collectstatic; not stored data.
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # Hashed file names let browsers cache CSS/JS for a long time; collectstatic (build.sh) writes the manifest.
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
# Tests and CI never run collectstatic, so they use plain storage (the manifest storage would fail without it).
if "test" in sys.argv[1:2] or os.environ.get("DJANGO_TESTING") == "1":
    STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}

# Fee Register dark-launch flag (design U11). When False the Fee Register is invisible and unreachable: no Home
# button, no Settings tab, no landing choice, every /fees/ URL is a 404. The fees tables, migrations and the suite
# backup and restore still work, so data is never lost. FEES_ENABLED=1 turns it on, any other set value turns it off.
# When the variable is not set the default is ON for developer mode (DJANGO_DEBUG or DJANGO_ALLOW_SQLITE) and for
# the test runner, and OFF in production. render.yaml sets "0" until the owner's go-ahead; then set it to "1".
_FEES_DEFAULT_ON = DEBUG or ALLOW_SQLITE or "test" in sys.argv[1:2] or os.environ.get("DJANGO_TESTING") == "1"
FEES_ENABLED = (os.environ["FEES_ENABLED"] == "1") if "FEES_ENABLED" in os.environ else _FEES_DEFAULT_ON

# Backup settings (used by the backups app).
# Only the newest BACKUP_KEEP_COUNT backups are kept, of every kind (owner decision). Never below 1.
BACKUP_KEEP_COUNT = max(1, _int("BACKUP_KEEP_COUNT", 30))
BACKUP_STALE_HOURS = _int("BACKUP_STALE_HOURS", 36)
# Days a deleted profile can be restored before the purge job removes it for good.
PROFILE_RETENTION_DAYS = max(1, _int("PROFILE_RETENTION_DAYS", 30))
# Days a deleted user can be restored before the nightly job removes them for good (round 18, D94).
USER_RETENTION_DAYS = max(1, _int("USER_RETENTION_DAYS", 30))
# Days of edit history kept; older versions are purged nightly (the newest version of every record is always kept).
HISTORY_RETENTION_DAYS = max(1, _int("HISTORY_RETENTION_DAYS", 30))
MAX_BACKUP_UPLOAD_MB = _int("MAX_BACKUP_UPLOAD_MB", 30)
# Off-site copies: how many days to keep them (the storage itself is chosen by OFFSITE_BACKUP_* env vars).
OFFSITE_BACKUP_RETENTION_DAYS = max(30, _int("OFFSITE_BACKUP_RETENTION_DAYS", 90))

# Email (the mailer app: Forgot my password, and scheduled backups by email). Any SMTP service works (a mailbox with
# an app password, Amazon SES, Brevo, Mailgun...). With no EMAIL_HOST nothing can be sent: the "Forgot my password"
# link is hidden and the Admin's email screen says so. In DEBUG with no EMAIL_HOST, mail is printed to the console.
def _flag(name, default=False):
    raw = os.environ.get(name, "").strip().lower()
    return default if not raw else raw in ("1", "true", "yes", "on")


EMAIL_HOST = os.environ.get("EMAIL_HOST", "").strip()
EMAIL_PORT = _int("EMAIL_PORT", 587)
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_SSL = _flag("EMAIL_USE_SSL")  # port 465
EMAIL_USE_TLS = _flag("EMAIL_USE_TLS", default=not EMAIL_USE_SSL)  # port 587
EMAIL_TIMEOUT = _int("EMAIL_TIMEOUT", 20)
#: The name of the whole website (emails, browser tabs of the shared pages). "Case Law Diary" is one program inside it.
SITE_NAME = os.environ.get("SITE_NAME", "").strip() or "Madon.co.in"
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "").strip() or EMAIL_HOST_USER or f"{SITE_NAME} <noreply@localhost>"
SERVER_EMAIL = DEFAULT_FROM_EMAIL
if EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
elif DEBUG:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
else:
    EMAIL_BACKEND = "mailer.backends.NotConfiguredBackend"
# Compress pages and text on the way out (much less to download on a phone). Set GZIP_RESPONSES=0 to switch off.
if _flag("GZIP_RESPONSES", default=True):
    MIDDLEWARE.insert(1, "config.middleware.TextGZipMiddleware")  # right after SecurityMiddleware
# A "Forgot my password" link works for this many seconds (one hour).
PASSWORD_RESET_TIMEOUT = _int("PASSWORD_RESET_TIMEOUT", 3600)
# Largest total size of the files attached to one backup email (files grow by about a third when sent, and most mailboxes refuse more than about 25 MB; Amazon SES refuses more than 10 MB, so set 6 there).
EMAIL_BACKUP_MAX_MB = max(1, _int("EMAIL_BACKUP_MAX_MB", 15))

if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_REDIRECT_EXEMPT = [r"^healthz/?$"]
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # Short for now; raise (e.g. to one year) once HTTPS is confirmed stable.
    SECURE_HSTS_SECONDS = 3600
    X_FRAME_OPTIONS = "DENY"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"redact_offline_token": {"()": "diary.logfilters.RedactOfflineToken"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "filters": ["redact_offline_token"]}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
