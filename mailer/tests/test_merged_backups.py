"""Admin > Backups is one page with two sections (Saved backups, Email backups). The old Email Backups address redirects."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from diary.tests.helpers import join_main
from mailer.models import EmailBackupSchedule

User = get_user_model()
PASSWORD = "x-long-pass-123"


@override_settings(SECURE_SSL_REDIRECT=False)
class MergedBackupsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("boss", password=PASSWORD, is_superuser=True, is_staff=True)
        self.editor = join_main(User.objects.create_user("ed", password=PASSWORD), "editor")

    def valid_post(self, **extra):
        data = {"frequency": "weekly", "weekday": "0", "day_of_month": "1", "delivery": "both_one",
                "recipients": "", "action": "save", **extra}
        return self.client.post(reverse("backup_email"), data)

    def test_the_page_has_both_sections_and_the_email_form_posts_to_the_old_name(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("backup_list")).content.decode()
        for key in ("saved", "email"):
            self.assertIn('data-section="%s"' % key, html)
            self.assertIn('data-section-link="%s"' % key, html)
        self.assertIn('action="%s"' % reverse("backup_email"), html)
        self.assertIn("You have unsaved changes.", html)
        self.assertIn("Backup Now", html)

    def test_the_old_email_backups_address_redirects_to_the_email_section(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("backup_email"))
        self.assertRedirects(resp, reverse("backup_list") + "?tab=email", fetch_redirect_response=False)

    def test_the_email_section_can_be_opened_from_the_address(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("backup_list") + "?tab=email").content.decode()
        self.assertIn('data-initial="email"', html)

    def test_saving_the_email_form_returns_to_the_email_section(self):
        self.client.force_login(self.admin)
        resp = self.valid_post(enabled="on", recipients="a@example.com", frequency="daily")
        self.assertRedirects(resp, reverse("backup_list") + "?tab=email", fetch_redirect_response=False)
        schedule = EmailBackupSchedule.load()
        self.assertTrue(schedule.enabled)
        self.assertEqual(schedule.recipients, "a@example.com")
        self.assertEqual(schedule.owner, self.admin)

    def test_an_invalid_email_form_shows_the_merged_page_with_the_error(self):
        self.client.force_login(self.admin)
        resp = self.valid_post(enabled="on", recipients="")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Add at least one email address")
        self.assertContains(resp, 'data-section="saved"')
        self.assertContains(resp, 'data-initial="email"')
        self.assertFalse(EmailBackupSchedule.load().enabled)

    def test_only_an_admin_may_use_it(self):
        self.client.force_login(self.editor)
        self.assertEqual(self.client.get(reverse("backup_email")).status_code, 403)
        self.assertEqual(self.client.post(reverse("backup_email"), {"action": "save"}).status_code, 403)
        self.assertEqual(self.client.get(reverse("backup_list")).status_code, 403)

    def test_the_admins_menu_has_four_tabs(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("backup_list")).content.decode()
        nav = html.split('class="subnav"')[1].split("</nav>")[0]
        for label in ("Users", "Profiles", "Appearance", "Backups"):
            self.assertIn(">%s</a>" % label, nav)
        self.assertNotIn("Email Backups", nav)
        self.assertNotIn("Import", nav)
