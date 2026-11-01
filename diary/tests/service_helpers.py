"""Shared set-up for the service layer tests (Milestone 3a)."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Profile
from diary import services as svc
from diary.models import VersionHistory
from diary.reading import formats_for
from diary.services.core import record_type
from diary.services.sequences import ident, labels, members
from diary.tests.helpers import main_profile

User = get_user_model()
PASSWORD = "correct-horse-battery-9"


class ServiceTestCase(TestCase):
    def setUp(self):
        self.profile = main_profile()
        self.other_profile = Profile.objects.create(program="diary", name="Other")
        self.user = User.objects.create_user("editor", password=PASSWORD)
        self.user2 = User.objects.create_user("editor2", password=PASSWORD)

    # -- shortcuts -------------------------------------------------------------------------
    def make(self, record_type, parent=None, index=None, profile=None, user=None, **fields):
        return svc.create(profile or self.profile, user or self.user, record_type, parent=parent, index=index, **fields).record

    def get(self, obj):
        return type(obj)._base_manager.get(pk=obj.pk)

    def ref(self, obj):
        return (record_type(obj), obj.pk)

    def numbered(self, container):
        """[(generated number, name or text)] of the live Items and Sections directly in a heading."""
        key = ("run", record_type(container), container.pk)
        objs = members(self.profile.pk, key)
        generated = labels(key, objs, formats_for(None))
        return [(generated[ident(o)], o.name if record_type(o) == "section" else o.text_plain) for o in objs]

    def positions(self, objs):
        return [self.get(o).position for o in objs]

    def history(self, obj):
        return list(
            VersionHistory.objects.filter(record_type=record_type(obj), record_id=obj.pk).order_by("version", "id")
        )

    def history_kinds(self, obj):
        return [row.change_kind for row in self.history(obj)]

    def build_topic(self):
        """Subject > Topic with a run of 'one', 'two', Section 'S', 'three', 'four'."""
        self.subject = self.make("subject", name="Contract")
        self.topic = self.make("topic", ("subject", self.subject.pk), name="Formation")
        parent = ("topic", self.topic.pk)
        self.one = self.make("item", parent, text="one")
        self.two = self.make("item", parent, text="two")
        self.sec = self.make("section", parent, name="S")
        self.three = self.make("item", parent, text="three")
        self.four = self.make("item", parent, text="four")
        return self.topic

    def failing_history(self, after):
        """Patch the history writer so the call number ``after + 1`` (and later ones) raise RuntimeError."""
        from diary.services import core

        real = core.write_history
        calls = {"n": 0}

        def flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] > after:
                raise RuntimeError("boom")
            return real(*args, **kwargs)

        return mock.patch("diary.services.core.write_history", side_effect=flaky)
