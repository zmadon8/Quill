"""Round 17: Forgot my password by username (D91), My edits (D92), the Settings tabs and Change my password (D93)."""
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from diary import services as svc
from diary.tests.helpers import join_main, main_profile

User = get_user_model()
PASSWORD = "x-long-pass-123"


@override_settings(SECURE_SSL_REDIRECT=False, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ForgotPasswordTests(TestCase):
    def setUp(self):
        self.with_email = User.objects.create_user("Rita", password=PASSWORD, email="rita@example.com")
        self.without_email = User.objects.create_user("sam", password=PASSWORD)

    def ask(self, username):
        return self.client.post(reverse("password_reset"), {"username": username})

    def test_the_page_asks_for_a_username(self):
        page = self.client.get(reverse("password_reset"))
        self.assertContains(page, 'name="username"')
        self.assertNotContains(page, 'name="email"')

    def test_a_known_username_with_an_email_gets_the_link(self):
        resp = self.ask("  rita ")  # capitals and spaces do not matter
        self.assertRedirects(resp, reverse("password_reset_done"), fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse("password_reset_done")), "Email sent")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["rita@example.com"])
        self.assertIn('"Rita"', mail.outbox[0].body)
        self.assertIn("/password-reset/", mail.outbox[0].body)

    def test_a_known_username_without_an_email_says_so(self):
        self.assertContains(self.ask("sam"), "No recovery email address found with this user.")
        self.assertEqual(mail.outbox, [])

    def test_an_unknown_or_disabled_username_is_not_found(self):
        self.assertContains(self.ask("nobody"), "User not found.")
        User.objects.filter(pk=self.with_email.pk).update(is_active=False)
        self.assertContains(self.ask("rita"), "User not found.")
        self.assertEqual(mail.outbox, [])

    def test_three_requests_an_hour_per_account(self):
        for _ in range(3):
            self.ask("rita")
        self.assertContains(self.ask("RITA"), "Too many requests")
        self.assertEqual(len(mail.outbox), 3)


@override_settings(SECURE_SSL_REDIRECT=False)
class SettingsTabsTests(TestCase):
    def setUp(self):
        self.user = join_main(User.objects.create_user("eddie", password=PASSWORD, email="e@example.com"), "editor")
        self.client.force_login(self.user)

    def visible(self, tab):
        html = self.client.get(reverse("my_settings"), {"tab": tab}).content.decode()
        return {name for name in ("account", "display", "numbers", "export")
                if f'data-settings-tab="{name}">' in html}

    def test_one_tab_at_a_time_and_every_field_stays_in_the_form(self):
        self.assertEqual(self.visible("account"), {"account"})
        self.assertEqual(self.visible("display"), {"display"})
        self.assertEqual(self.visible("numbers"), {"numbers"})
        self.assertEqual(self.visible("export"), {"account"})  # round 18: Word export moved to the Export page
        self.assertEqual(self.visible("bogus"), {"account"})
        html = self.client.get(reverse("my_settings"), {"tab": "numbers"}).content.decode()
        for field in ('name="email"', 'name="header_style"', 'name="topic_format"', 'name="diary-reading_all_mode"',
                      'name="tab" value="numbers"'):
            self.assertIn(field, html)
        self.assertNotIn('name="export_date_format"', html)

    def test_saving_a_tab_keeps_the_others_and_returns_to_it(self):
        self.client.post(reverse("my_settings"), {"tab": "display", "email": "e@example.com", "header_style": "words",
                                                  "landing_program": ""})
        resp = self.client.post(reverse("my_settings"), {"tab": "display", "email": "e@example.com",
                                                         "header_style": "words", "landing_program": ""})
        self.assertRedirects(resp, reverse("my_settings") + "?tab=display", fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertEqual((self.user.header_style, self.user.email), ("words", "e@example.com"))

    def test_the_gear_and_home_open_the_settings_area(self):
        diary = self.client.get(reverse("diary_home")).content.decode()
        self.assertIn('href="%s" class="nav-icon" aria-label="Settings"' % reverse("my_settings"), diary)
        display = self.client.get(reverse("my_settings"), {"tab": "display"}).content.decode()
        self.assertIn("<h2>Case Law Diary</h2>", display)  # round 18: the old Diary tab is part of Display
        self.assertIn('class="subnav"', display)

    def test_change_my_password(self):
        page = self.client.get(reverse("password_change"))
        self.assertContains(page, 'name="old_password"')
        resp = self.client.post(reverse("password_change"), {"old_password": PASSWORD, "new_password1": "a-New-pass-456!",
                                                             "new_password2": "a-New-pass-456!"})
        self.assertRedirects(resp, reverse("my_settings"), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("a-New-pass-456!"))
        self.assertContains(self.client.get(reverse("my_settings")), "Your password is changed.")  # still signed in


@override_settings(SECURE_SSL_REDIRECT=False)
class MyEditsTests(TestCase):
    def setUp(self):
        self.profile = main_profile()
        self.me = join_main(User.objects.create_user("eddie", password=PASSWORD), "editor")
        self.other = join_main(User.objects.create_user("olga", password=PASSWORD), "editor")
        subject = svc.create(self.profile, self.me, "subject", name="Contract").record
        self.topic = svc.create(self.profile, self.me, "topic", parent=("subject", subject.pk), name="Formation").record
        self.item = svc.create(self.profile, self.me, "item", parent=("topic", self.topic.pk), text="<p>Offer rule</p>").record
        svc.create(self.profile, self.other, "item", parent=("topic", self.topic.pk), text="<p>Theirs</p>")
        svc.edit(self.profile, self.me, "item", self.item.pk, {"text": "<p>Offer rule, changed</p>"})
        self.client.force_login(self.me)

    def test_my_own_changes_newest_first_with_links(self):
        resp = self.client.get(reverse("my_edits"))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("Edits", html)  # round 19: the page heading is now "Edits" (inside Settings > Case Law Diary)
        self.assertNotIn("Theirs", html)
        self.assertLess(html.index("Changed Item"), html.index("Added Item"))
        self.assertLess(html.index("Added Item"), html.index("Added Topic"))
        self.assertIn('href="%s"' % reverse("history", args=["item", self.item.pk]), html)
        self.assertIn("#n-item-%d" % self.item.pk, html)

    def test_a_delete_of_a_topic_with_its_items_is_one_line(self):
        svc.delete(self.profile, self.me, "topic", self.topic.pk)
        html = self.client.get(reverse("my_edits")).content.decode()
        self.assertIn("Moved to Trash Topic", html)
        self.assertIn("and 2 more", html)
        self.assertIn("in Trash or gone", html)

    def test_needs_a_profile(self):
        self.client.force_login(User.objects.create_user("lone", password=PASSWORD))
        self.assertEqual(self.client.get(reverse("my_edits")).status_code, 403)
