"""The email backend used when no SMTP server is configured (no EMAIL_HOST) outside DEBUG.

Sending raises a plain error instead of silently dropping the message, so nothing ever looks sent when it was not.
"""
from django.core.mail.backends.base import BaseEmailBackend


class EmailNotConfigured(Exception):
    """Email is not set up on this server (EMAIL_HOST is missing)."""


class NotConfiguredBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        raise EmailNotConfigured("Email is not set up on this server (EMAIL_HOST is missing).")
