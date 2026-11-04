"""Query counts stay bounded however much data there is (Milestone 7 performance pass)."""
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from diary.models import Case, Item, Note, NoteLink, Section, Subject, Subtopic, Topic
from diary.tests.helpers import join_main, main_profile

PASSWORD = "x-long-pass-123"


def build_subject(profile, topics, items_per_container, name="Big Subject"):
    """One Subject with ``topics`` Topics, each with a Sub-topic, Section, Items (some with citations on separate lines), Notes and links."""
    subject = Subject.objects.create(profile=profile, name=name, landing_position=1)
    first_item = Item.objects.create(profile=profile, subject=subject, text="<p>first</p>", text_plain="first")
    for t in range(topics):
        topic = Topic.objects.create(profile=profile, subject=subject, name=f"Topic {t}")
        sub = Subtopic.objects.create(profile=profile, topic=topic, name=f"Sub {t}")
        section = Section.objects.create(profile=profile, topic=topic, name=f"Section {t}", position=1)
        for n in range(items_per_container):
            top = Item.objects.create(
                profile=profile, subtopic=sub, text=f"<p>item {t}-{n}</p>", text_plain=f"item {t}-{n}",
                flag="pending" if n % 2 == 0 else "none", flag_text="check" if n % 2 == 0 else "", position=n + 1,
            )
            Item.objects.filter(pk=top.pk).update(citation_layout="lines")
            Case.objects.create(profile=profile, item=top, citation=f"A v B {t}-{n}", comment="<p>why</p>", position=1,
                                url=f"https://example.com/Case/{t}-{n}")
            Case.objects.create(profile=profile, item=top, citation=f"C v D {t}-{n}", position=2)
            note = Note.objects.create(profile=profile, item=top, text="<p>note</p>", text_plain="note")
            NoteLink.objects.create(profile=profile, note=note, item=first_item)
            NoteLink.objects.create(profile=profile, note=note, section=section, position=2)
            NoteLink.objects.create(profile=profile, note=note, topic=topic, position=3)
        note = Note.objects.create(profile=profile, section=section, text="<p>s</p>", text_plain="s")
        NoteLink.objects.create(profile=profile, note=note, subtopic=sub)
    return subject


@override_settings(SECURE_SSL_REDIRECT=False)
class QueryCountTests(TestCase):
    CEILING = 40

    @classmethod
    def setUpTestData(cls):
        cls.user = join_main(get_user_model().objects.create_user("quentin", password=PASSWORD))

    def count(self, url):
        self.client.force_login(self.user)
        self.client.get(url)  # warm up (session, content types)
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.last_response = response
        return len(ctx)

    def test_whole_subject_view_is_bounded(self):
        subject = build_subject(main_profile(), topics=2, items_per_container=3)
        small = self.count(reverse("read_subject", args=[subject.pk]))
        self.assertLessEqual(small, self.CEILING)
        bigger = build_subject(main_profile(), topics=8, items_per_container=25, name="Bigger Subject")  # about 200 Items
        large = self.count(reverse("read_subject", args=[bigger.pk]))
        self.assertLessEqual(large, self.CEILING)
        self.assertLessEqual(large, small + 2, "query count grew with the amount of data")

    def test_flags_and_hyperlinks_pages_are_bounded(self):
        build_subject(main_profile(), topics=2, items_per_container=3)
        small = {name: self.count(reverse(name)) for name in ("flags", "flag_links")}
        self.assertContains(self.last_response, "https://example.com/Case/")
        build_subject(main_profile(), topics=8, items_per_container=25, name="Bigger Subject")
        for name in ("flags", "flag_links"):
            large = self.count(reverse(name))
            self.assertLessEqual(large, self.CEILING, name)
            self.assertLessEqual(large, small[name] + 2, "query count grew with the amount of data: " + name)
        self.count(reverse("flags"))
        self.assertContains(self.last_response, "Pending: check")

    def test_search_is_bounded(self):
        build_subject(main_profile(), topics=2, items_per_container=3)
        small = self.count(reverse("search") + "?q=item")
        self.assertContains(self.last_response, "item 0-0")
        build_subject(main_profile(), topics=8, items_per_container=25, name="Bigger Subject")
        large = self.count(reverse("search") + "?q=item")
        self.assertLessEqual(large, self.CEILING)
        self.assertLessEqual(large, small + 2, "query count grew with the amount of data")
