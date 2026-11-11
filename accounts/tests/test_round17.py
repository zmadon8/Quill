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

    def sections(self, tab=None):
        html = self.client.get(reverse("my_settings"), {"tab": tab} if tab else {}).content.decode()
        return html, {name for name in ("account", "display", "diary", "fees") if f'data-section="{name}"' in html}

    def test_left_hand_sections_each_with_their_own_form_and_save(self):
        html, found = self.sections()
        self.assertEqual(found, {"account", "display", "diary"})  # the Fee Register section needs a Fee Register profile
        self.assertEqual(html.count("data-section-form"), 3)
        self.assertEqual(html.count(">Save</button>"), 3)
        self.assertEqual(html.count("You have unsaved changes."), 3)
        for field in ('name="email"', 'name="justify_text"', 'name="topic_format"', 'name="tab" value="diary"'):
            self.assertIn(field, html)
        self.assertNotIn('name="diary-view_whole_subject"', html)  # reading is a Case Law Diary settings (profile) choice
        self.assertNotIn('name="export_date_format"', html.split('data-section="account"')[1].split('data-section="diary"')[0])
        self.assertIn('data-section-link="diary"', html)

    def test_the_section_asked_for_is_marked_and_an_old_tab_name_still_works(self):
        html, _found = self.sections("display")
        self.assertIn('data-section-link="display" class="on" aria-current="page"', html)
        html, _found = self.sections("numbers")  # the old name of the Case Law Diary tab
        self.assertIn('data-section-link="diary" class="on" aria-current="page"', html)
        html, _found = self.sections("bogus")
        self.assertIn('data-section-link="account" class="on" aria-current="page"', html)

    def test_every_setting_has_help_and_a_who_tag(self):
        html, _found = self.sections()
        self.assertGreaterEqual(html.count("setting-help"), 8)
        self.assertGreaterEqual(html.count("Only you"), 8)
        self.assertNotIn("Everyone in this profile", html)  # nothing shared lives on My settings

    def test_the_home_button_is_always_shown(self):
        # Round 23: the "Show the Home button" option is gone; Home is always in the header.
        home = 'class="home-button"'
        self.assertFalse(hasattr(self.user, "show_home_button"))
        html = self.client.get(reverse("my_settings")).content.decode()
        self.assertIn(home, html)
        self.assertNotIn("show_home_button", html)
        self.client.post(reverse("my_settings"), {"tab": "display", "landing_program": ""})
        html = self.client.get(reverse("my_settings")).content.decode()
        self.assertIn(home, html)
        self.assertIn('data-home="', html)   # the Alt+H shortcut still knows where Home is

    def test_saving_a_section_keeps_the_others_and_returns_to_it(self):
        self.user.justify_text = True
        self.user.save()
        resp = self.client.post(reverse("my_settings"), {"tab": "account", "email": "e@example.com"})
        self.assertRedirects(resp, reverse("my_settings"), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "e@example.com")
        self.assertTrue(self.user.justify_text)  # the Display section was not posted, so it is untouched
        resp = self.client.post(reverse("my_settings"), {"tab": "display", "landing_program": ""})
        self.assertRedirects(resp, reverse("my_settings") + "?tab=display", fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "e@example.com")  # the Account section is untouched
        self.assertFalse(self.user.justify_text)  # an unticked box in the posted section turns it off

    def test_the_user_name_opens_the_settings_area(self):
        diary = self.client.get(reverse("diary_home")).content.decode()
        # No Settings link in the diary header; the user name in the header opens My settings.
        self.assertNotIn('aria-label="Settings"', diary)
        self.assertIn('class="who" href="%s"' % reverse("my_settings"), diary)
        display = self.client.get(reverse("my_settings"), {"tab": "display"}).content.decode()
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
        resp = self.client.get(reverse("diary_history"))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('<h1 class="visually-hidden">History</h1>', html)  # "My edits" is now History in the diary menu
        self.assertNotIn("Theirs", html)
        self.assertLess(html.index("Changed Item"), html.index("Added Item"))
        self.assertLess(html.index("Added Item"), html.index("Added Topic"))
        self.assertIn('href="%s"' % reverse("history", args=["item", self.item.pk]), html)
        self.assertIn("#n-item-%d" % self.item.pk, html)

    def test_the_old_my_edits_address_redirects_to_history(self):
        resp = self.client.get(reverse("my_edits"))
        self.assertRedirects(resp, reverse("diary_history"), status_code=301, fetch_redirect_response=False)
        self.assertEqual(reverse("diary_history"), "/caselaw/history/")

    def test_history_is_in_the_diary_menu(self):
        html = self.client.get(reverse("diary_home")).content.decode()
        self.assertIn('href="%s"' % reverse("diary_history"), html)
        self.assertIn('aria-label="History"', html)

    def test_a_delete_of_a_topic_with_its_items_is_one_line(self):
        svc.delete(self.profile, self.me, "topic", self.topic.pk)
        html = self.client.get(reverse("diary_history")).content.decode()
        self.assertIn("Moved to Trash Topic", html)
        self.assertIn("and 2 more", html)
        self.assertIn("in Trash or gone", html)

    def test_needs_a_profile(self):
        self.client.force_login(User.objects.create_user("lone", password=PASSWORD))
        self.assertEqual(self.client.get(reverse("diary_history")).status_code, 403)
