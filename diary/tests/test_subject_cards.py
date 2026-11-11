"""Owner round 2026-11: the Index of Subjects as cards (topic count), with a Cards / List switch."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from diary.models import Subject, Topic
from diary.tests.helpers import join_main, main_profile

User = get_user_model()


@override_settings(SECURE_SSL_REDIRECT=False)
class SubjectCardTests(TestCase):
    def setUp(self):
        self.profile = main_profile()
        self.subject = Subject.objects.create(profile=self.profile, name="Arbitration", show_on_landing=True, landing_position=1)
        for n, name in enumerate(["Waiver", "Fraud", "Interim relief", "Appointment"]):
            Topic.objects.create(profile=self.profile, subject=self.subject, name=name, position=n + 1)
        Topic.objects.create(profile=self.profile, subject=self.subject, name="Gone", position=9,
                             deleted_at="2026-01-01T00:00:00Z")
        self.user = join_main(User.objects.create_user("cara", password="x-long-pass-123"), "editor")
        self.client.force_login(self.user)

    def test_cards_show_topic_count_not_names_and_the_switch(self):
        html = self.client.get(reverse("diary_home")).content.decode()
        self.assertIn('class="home-column subjects-page subjects-cards"', html)
        self.assertIn('data-initial="A"', html)
        self.assertIn("0 items &middot; 4 topics", html)
        self.assertNotIn("subject-tag", html)                        # the cards no longer list Topic names
        for name in ["Waiver", "Fraud", "Interim relief", "Appointment"]:
            self.assertNotIn(name, html)
        self.assertNotIn(">Gone<", html)
        self.assertIn('data-subjects-view="list"', html)
        self.assertIn('id="subjects-search-q"', html)
        self.assertIn("js/subjects-view.js", html)

    def test_edit_mode_keeps_the_list(self):
        html = self.client.get(reverse("diary_home") + "?edit=1").content.decode()
        self.assertNotIn("subjects-page subjects-cards", html)
        self.assertNotIn("data-subjects-view", html)
