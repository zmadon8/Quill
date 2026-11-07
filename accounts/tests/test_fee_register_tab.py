"""The Fee Register link of the suite Settings group shows only for users with a Fee Register profile."""
import re

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import ROLE_EDITOR, Profile, ProfileMembership
from accounts.suite import KEY_FEES
from diary.tests.helpers import join_main

User = get_user_model()
PASSWORD = "x-long-pass-123"


@override_settings(SECURE_SSL_REDIRECT=False)
class FeeRegisterTabTests(TestCase):
    def tabs(self, user):
        self.client.force_login(user)
        html = self.client.get(reverse("my_settings")).content.decode()
        parts = html.split('class="subnav"')
        nav = parts[1].split("</nav>")[0] if len(parts) > 1 else ""
        return re.findall(r">([^<]+)</a>", nav), nav

    def test_hidden_without_a_fees_profile(self):
        user = join_main(User.objects.create_user("diaryonly", password=PASSWORD), "editor")
        labels, nav = self.tabs(user)
        self.assertEqual(labels, ["My settings", "Case Law Diary settings"])
        self.assertNotIn(reverse("fees_settings"), nav)

    def test_visible_after_the_diary_link_with_a_fees_profile(self):
        user = join_main(User.objects.create_user("both", password=PASSWORD), "editor")
        profile = Profile.objects.create(program=KEY_FEES, name="Tab-Fees")
        ProfileMembership.objects.create(user=user, profile=profile, role=ROLE_EDITOR)
        labels, nav = self.tabs(user)
        self.assertEqual(labels, ["My settings", "Case Law Diary settings", "Fee Register settings"])
        self.assertIn('href="%s"' % reverse("fees_settings"), nav)

    def test_fees_only_user_sees_the_link(self):
        user = User.objects.create_user("feesonly", password=PASSWORD)
        profile = Profile.objects.create(program=KEY_FEES, name="Tab-Fees-2")
        ProfileMembership.objects.create(user=user, profile=profile, role=ROLE_EDITOR)
        labels, _nav = self.tabs(user)
        self.assertEqual(labels, ["My settings", "Fee Register settings"])
