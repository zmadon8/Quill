"""One place that decides who an email is "From", used by every email path (backups, test email, password reset).

Why: Gmail's receiving servers reject (550 5.7.30, DKIM) any message that says it is From a gmail.com address but did
not leave through Google's own servers signed by Google. Mail sent by logging in to smtp.gmail.com with an account's
app password, From that same address, is signed by Google and passes. So when the server is Gmail, the From address is
forced to the login address. Nothing here ever reads or shows the password.
"""
import logging
import smtplib
from email.utils import formataddr, parseaddr

from django.conf import settings
from django.core.mail import EmailMessage

logger = logging.getLogger(__name__)

GMAIL_HOSTS = ("smtp.gmail.com", "smtp.googlemail.com")
GMAIL_DOMAINS = ("gmail.com", "googlemail.com")
DEFAULT_NAME = "Case Law Diary"

WARN_FIXED = "From address differs from the Gmail login, fixed to the login address."
WARN_RELAY = ("Using a Gmail From address with a non-Gmail server: Gmail recipients will reject this (DKIM). Use "
              "smtp.gmail.com with an app password, or use a From address on a domain the server can sign.")
WARN_NONE = "No email server configured."


def _host():
    return (getattr(settings, "EMAIL_HOST", "") or "").strip().lower()


def is_gmail_host():
    return _host() in GMAIL_HOSTS


def _domain(address):
    return address.rsplit("@", 1)[-1].lower() if "@" in address else ""


def _login_address():
    name, address = parseaddr(getattr(settings, "EMAIL_HOST_USER", "") or "")
    return address if "@" in address else ""


def effective_from():
    """(From header text, [warnings]). Gmail host: the login address with the display name of DEFAULT_FROM_EMAIL."""
    default = settings.DEFAULT_FROM_EMAIL
    warnings = []
    if not _host():
        return default, [WARN_NONE]
    name, address = parseaddr(default)
    if is_gmail_host():
        login = _login_address()
        if login:
            if address.lower() != login.lower():
                warnings.append(WARN_FIXED)
            return formataddr((name or DEFAULT_NAME, login)), warnings
        return default, warnings
    if _domain(address) in GMAIL_DOMAINS:
        warnings.append(WARN_RELAY)
    return default, warnings


def from_and_reply_to():
    """(From, Reply-To list) for a new message; logs a warning when the configured From had to be changed."""
    from_email, warnings = effective_from()
    if WARN_FIXED in warnings:
        logger.warning("DEFAULT_FROM_EMAIL differs from EMAIL_HOST_USER on a Gmail server; sending from the login address.")
    return from_email, [parseaddr(from_email)[1]] if parseaddr(from_email)[1] else []


def build_message(subject, body, to):
    """An EmailMessage with the effective From and the same address as Reply-To."""
    from_email, reply_to = from_and_reply_to()
    return EmailMessage(subject=subject, body=body, to=list(to), from_email=from_email, reply_to=reply_to)


def diagnostics():
    """Non-secret facts about how mail will be sent, for the Admin's screen."""
    from_email, warnings = effective_from()
    host = _host()
    return {
        "host": host or "(none)", "port": getattr(settings, "EMAIL_PORT", ""),
        "security": "SSL" if getattr(settings, "EMAIL_USE_SSL", False) else ("TLS" if getattr(settings, "EMAIL_USE_TLS", False) else "none"),
        "user": getattr(settings, "EMAIL_HOST_USER", "") or "(none)",
        "from_email": from_email, "warnings": warnings, "gmail": is_gmail_host(),
    }


def _scrub(text):
    secret = getattr(settings, "EMAIL_HOST_PASSWORD", "") or ""
    if len(secret) >= 4:
        text = text.replace(secret, "***").replace(secret.replace(" ", ""), "***")
    return text


def describe_smtp_error(exc):
    """The server's own words for a failed send (no secrets), for the send log."""
    if isinstance(exc, smtplib.SMTPResponseException):
        msg = exc.smtp_error.decode("utf-8", "replace") if isinstance(exc.smtp_error, bytes) else str(exc.smtp_error)
        text = f"{exc.__class__.__name__}: {exc.smtp_code} {msg}"
    elif isinstance(exc, smtplib.SMTPRecipientsRefused):
        text = f"{exc.__class__.__name__}: " + "; ".join(f"{who}: {code} {m.decode('utf-8', 'replace') if isinstance(m, bytes) else m}" for who, (code, m) in exc.recipients.items())
    else:
        text = exc.__class__.__name__ + (f": {exc}" if str(exc) else "")
    text = _scrub(" ".join(text.split()))
    if "5.7.30" in text or "DKIM" in text:
        text += " (Gmail rejected the sender: see docs/EMAIL.md, Gmail 550 5.7.30 DKIM)"
    return text[:300]
