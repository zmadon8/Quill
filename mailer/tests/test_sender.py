"""The shared From helper, the diagnostics on the Email backups section, and the send log's error text."""
import smtplib
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from mailer import sender, services
from mailer.models import EmailBackupSchedule

User = get_user_model()
GMAIL = dict(EMAIL_HOST="smtp.gmail.com", EMAIL_PORT=587, EMAIL_USE_TLS=True, EMAIL_USE_SSL=False,
             EMAIL_HOST_USER="you@gmail.com", EMAIL_HOST_PASSWORD="abcdefghijklmnop")


@override_settings(**GMAIL, DEFAULT_FROM_EMAIL="Case Law Diary <you@gmail.com>")
class EffectiveFromTests(SimpleTestCase):
    """The From name is the website's (Madon.co.in): an old "Case Law Diary" name or a blank one becomes it."""

    @override_settings(DEFAULT_FROM_EMAIL="Chambers <you@gmail.com>")
    def test_another_configured_name_is_kept(self):
        self.assertEqual(sender.effective_from()[0], "Chambers <you@gmail.com>")

    def test_matching_gmail_from_is_kept_without_warning(self):
        from_email, warnings = sender.effective_from()
        self.assertEqual(from_email, "Madon.co.in <you@gmail.com>")
        self.assertEqual(warnings, [])

    @override_settings(DEFAULT_FROM_EMAIL="Chambers <other@example.com>")
    def test_gmail_host_forces_the_login_address_and_keeps_the_display_name(self):
        from_email, warnings = sender.effective_from()
        self.assertEqual(from_email, "Chambers <you@gmail.com>")
        self.assertEqual(warnings, [sender.WARN_FIXED])

    @override_settings(DEFAULT_FROM_EMAIL="")
    def test_gmail_host_with_empty_from_uses_the_login_address(self):
        self.assertEqual(sender.effective_from()[0], "Madon.co.in <you@gmail.com>")

    @override_settings(EMAIL_HOST="smtp.googlemail.com", DEFAULT_FROM_EMAIL="x@example.com")
    def test_googlemail_host_counts_as_gmail(self):
        self.assertIn("you@gmail.com", sender.effective_from()[0])

    @override_settings(EMAIL_HOST="smtp-relay.brevo.com", EMAIL_HOST_USER="login@brevo.example",
                       DEFAULT_FROM_EMAIL="Case Law Diary <me@example.org>")
    def test_other_hosts_keep_the_configured_from(self):
        self.assertEqual(sender.effective_from(), ("Madon.co.in <me@example.org>", []))

    @override_settings(EMAIL_HOST="smtp-relay.brevo.com", DEFAULT_FROM_EMAIL="Case Law Diary <you@gmail.com>")
    def test_gmail_from_through_another_server_is_warned_about(self):
        from_email, warnings = sender.effective_from()
        self.assertEqual(from_email, "Madon.co.in <you@gmail.com>")
        self.assertEqual(warnings, [sender.WARN_RELAY])

    @override_settings(EMAIL_HOST="")
    def test_no_host_warns(self):
        self.assertEqual(sender.effective_from()[1], [sender.WARN_NONE])

    @override_settings(DEFAULT_FROM_EMAIL="Chambers <other@example.com>")
    def test_build_message_sets_from_and_reply_to_to_the_same_address(self):
        message = sender.build_message("s", "b", ["a@example.com"])
        self.assertEqual(message.from_email, "Chambers <you@gmail.com>")
        self.assertEqual(message.reply_to, ["you@gmail.com"])

    def test_diagnostics_never_contain_the_password(self):
        info = sender.diagnostics()
        self.assertNotIn(GMAIL["EMAIL_HOST_PASSWORD"], repr(info))
        self.assertEqual((info["host"], info["port"], info["security"], info["user"]),
                         ("smtp.gmail.com", 587, "TLS", "you@gmail.com"))


class ErrorTextTests(SimpleTestCase):
    @override_settings(**GMAIL)
    def test_smtp_error_text_has_the_code_and_message_and_no_secret(self):
        exc = smtplib.SMTPDataError(550, b"5.7.30 blocked DKIM did not pass abcdefghijklmnop")
        text = sender.describe_smtp_error(exc)
        self.assertIn("550", text)
        self.assertIn("5.7.30", text)
        self.assertIn("docs/EMAIL.md", text)
        self.assertNotIn(GMAIL["EMAIL_HOST_PASSWORD"], text)

    def test_other_errors_show_type_and_message(self):
        self.assertEqual(sender.describe_smtp_error(TimeoutError("timed out")), "TimeoutError: timed out")


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", **GMAIL,
                   DEFAULT_FROM_EMAIL="Chambers <other@example.com>")
class SendingTests(TestCase):
    def test_test_email_goes_out_from_the_login_address_and_says_so(self):
        ok, message = services.send_test_email(["me@example.com"])
        self.assertTrue(ok)
        self.assertEqual(mail.outbox[0].from_email, "Chambers <you@gmail.com>")
        self.assertEqual(mail.outbox[0].reply_to, ["you@gmail.com"])
        self.assertIn("Chambers <you@gmail.com>", message)
        self.assertIn("smtp.gmail.com", message)

    def test_emails_name_the_website_not_the_case_law_diary(self):
        services.send_test_email(["me@example.com"])
        self.assertEqual(mail.outbox[0].subject, "Madon.co.in: test email")
        self.assertNotIn("Case Law Diary", mail.outbox[0].body)

    def test_password_reset_email_names_the_website(self):
        from accounts.forms import UsernamePasswordResetForm

        User.objects.create_user("sam", password="x-long-pass-123", email="sam@example.com")
        form = UsernamePasswordResetForm({"username": "sam"})
        self.assertTrue(form.is_valid())
        form.save(domain_override="testserver", use_https=True, request=None,
                  email_template_name="registration/password_reset_email.txt",
                  subject_template_name="registration/password_reset_subject.txt")
        self.assertEqual(mail.outbox[-1].subject, "Madon.co.in: choose a new password")
        self.assertIn("for the Madon.co.in account", mail.outbox[-1].body)

    def test_scheduled_backup_uses_the_same_from(self):
        schedule = EmailBackupSchedule.load()
        schedule.recipients = "me@example.com"
        schedule.word_enabled = False  # the regular backup only
        schedule.save()
        ok, _ = services.send_scheduled_backup(schedule)
        self.assertTrue(ok)
        self.assertEqual(mail.outbox[0].from_email, "Chambers <you@gmail.com>")

    def test_a_failed_send_stores_the_smtp_error_in_the_log(self):
        schedule = EmailBackupSchedule.load()
        schedule.recipients = "me@example.com"
        schedule.word_enabled = False  # the regular backup only
        schedule.save()
        boom = smtplib.SMTPDataError(550, b"5.7.30 DKIM did not pass")
        with mock.patch("django.core.mail.message.EmailMessage.send", side_effect=boom):
            ok, _ = services.send_scheduled_backup(schedule)
        schedule.refresh_from_db()
        self.assertFalse(ok)
        self.assertIn("550", schedule.last_message)
        self.assertIn("5.7.30", schedule.last_message)
        self.assertNotIn(GMAIL["EMAIL_HOST_PASSWORD"], schedule.last_message)

    def test_password_reset_email_uses_the_same_from(self):
        user = User.objects.create_user("pat", password="x-long-pass-123", email="pat@example.com")
        from accounts.forms import UsernamePasswordResetForm

        form = UsernamePasswordResetForm({"username": "pat"})
        self.assertTrue(form.is_valid())
        form.save(domain_override="testserver", use_https=True, request=None,
                  email_template_name="registration/password_reset_email.txt",
                  subject_template_name="registration/password_reset_subject.txt")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].from_email, "Chambers <you@gmail.com>")
        self.assertEqual(mail.outbox[0].to, [user.email])


@override_settings(SECURE_SSL_REDIRECT=False)
class DiagnosticsPageTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("boss", password="x-long-pass-123", is_superuser=True, is_staff=True)
        self.client.force_login(self.admin)

    def page(self):
        return self.client.get(reverse("backup_list") + "?tab=email").content.decode()

    @override_settings(**GMAIL, DEFAULT_FROM_EMAIL="Chambers <other@example.com>")
    def test_page_shows_effective_settings_and_a_warning_but_not_the_password(self):
        html = self.page()
        self.assertIn("data-email-diagnostics", html)
        self.assertIn("smtp.gmail.com", html)
        self.assertIn("you@gmail.com", html)
        self.assertIn("fixed to the login address", html)
        self.assertIn("BOTH the web service and the cron job", html)
        self.assertNotIn(GMAIL["EMAIL_HOST_PASSWORD"], html)

    @override_settings(EMAIL_HOST="smtp-relay.brevo.com", EMAIL_HOST_USER="login", DEFAULT_FROM_EMAIL="Case Law Diary <you@gmail.com>")
    def test_page_warns_about_a_gmail_from_on_another_server(self):
        self.assertIn("Gmail recipients will reject this", self.page())

    @override_settings(EMAIL_HOST="")
    def test_page_says_when_no_server_is_configured(self):
        self.assertIn("No email server configured", self.page())


@override_settings(SECURE_SSL_REDIRECT=False, **GMAIL, DEFAULT_FROM_EMAIL="")
class SiteNameSettingTests(TestCase):
    """Admins > Appearance > Site name: the website's name in emails and on the shared pages."""

    def setUp(self):
        from diary.tests.helpers import join_main

        self.admin = join_main(User.objects.create_user("boss", password="x-long-pass-123", is_superuser=True), "editor")
        self.client.force_login(self.admin)

    def save(self, value):
        return self.client.post(reverse("settings"), {"site_name": value, "home_name": "Home", "diary_name": "Case Law Diary",
                                                     "fees_name": "Fee Register"})

    def test_default_is_madon_co_in(self):
        self.assertEqual(sender.site_name(), "Madon.co.in")
        self.assertContains(self.client.get(reverse("settings")), 'value="Madon.co.in"')

    def test_a_new_name_is_used_in_emails_and_page_titles(self):
        self.assertEqual(self.save("  Madon   Chambers ").status_code, 302)
        self.assertEqual(sender.site_name(), "Madon Chambers")
        self.assertEqual(sender.effective_from()[0], "Madon Chambers <you@gmail.com>")
        services.send_test_email(["me@example.com"])
        self.assertEqual(mail.outbox[-1].subject, "Madon Chambers: test email")
        self.assertContains(self.client.get(reverse("user_list")), "<title>Users - Madon Chambers</title>")

    def test_blank_goes_back_to_the_default(self):
        self.save("Other")
        self.save("")
        self.assertEqual(sender.site_name(), "Madon.co.in")
