from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase
from django.utils import timezone

from accounts.models import Profile, User
from diary.models import (
    Case,
    Item,
    Note,
    NoteLink,
    Section,
    Subject,
    Subtopic,
    Topic,
    UserSettings,
)
from diary.tests.helpers import main_profile


class Base(TestCase):
    def setUp(self):
        self.subject = Subject.objects.create(profile=main_profile(), name="Contract")
        self.topic = Topic.objects.create(profile=main_profile(), subject=self.subject, name="Formation")
        self.subtopic = Subtopic.objects.create(profile=main_profile(), topic=self.topic, name="Offer")

    def assertRefused(self, model, **fields):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                fields.setdefault("profile", main_profile())
                model.objects.create(**fields)


class SubjectTests(Base):
    def test_blank_name_refused(self):
        self.assertRefused(Subject, name="")

    def test_name_unique_ignoring_case_among_live_subjects(self):
        self.assertRefused(Subject, name="contract")
        self.assertRefused(Subject, name="CONTRACT")

    def test_deleted_subject_does_not_block_name(self):
        Subject.objects.filter(pk=self.subject.pk).update(deleted_at=timezone.now())
        again = Subject.objects.create(profile=main_profile(), name="Contract")
        self.assertIsNone(again.deleted_at)

    def test_two_deleted_subjects_may_share_a_name(self):
        Subject.objects.filter(pk=self.subject.pk).update(deleted_at=timezone.now())
        second = Subject.objects.create(profile=main_profile(), name="Contract")
        Subject.objects.filter(pk=second.pk).update(deleted_at=timezone.now())

    def test_defaults(self):
        self.assertTrue(self.subject.show_on_landing)
        self.assertEqual(self.subject.version, 1)
        self.assertIsNone(self.subject.deleted_at)
        self.assertIsNotNone(self.subject.created_at)


class NameTests(Base):
    def test_topic_and_subtopic_names_required(self):
        self.assertRefused(Topic, subject=self.subject, name="")
        self.assertRefused(Subtopic, topic=self.topic, name="")


class ParentRuleTests(Base):
    def test_subtopic_needs_exactly_one_parent(self):
        self.assertRefused(Subtopic, name="x")
        self.assertRefused(Subtopic, name="x", topic=self.topic, subject=self.subject)
        direct = Subtopic.objects.create(profile=main_profile(), name="Directors", subject=self.subject)
        self.assertEqual(direct.subject, self.subject)

    def test_section_needs_exactly_one_parent(self):
        self.assertRefused(Section, name="s")
        self.assertRefused(Section, name="s", subject=self.subject, topic=self.topic)
        for parent in ({"subject": self.subject}, {"topic": self.topic}, {"subtopic": self.subtopic}):
            Section.objects.create(profile=main_profile(), name="s", **parent)

    def test_item_needs_exactly_one_parent(self):
        self.assertRefused(Item, text="x")
        self.assertRefused(Item, text="x", subject=self.subject, subtopic=self.subtopic)
        for parent in ({"subject": self.subject}, {"topic": self.topic}, {"subtopic": self.subtopic}):
            Item.objects.create(profile=main_profile(), text="ok", **parent)

    def test_note_needs_exactly_one_parent(self):
        item = Item.objects.create(profile=main_profile(), subtopic=self.subtopic)
        section = Section.objects.create(profile=main_profile(), subtopic=self.subtopic)
        self.assertRefused(Note, text="x")
        self.assertRefused(Note, text="x", item=item, section=section)
        for parent in ({"subject": self.subject}, {"topic": self.topic}, {"subtopic": self.subtopic},
                       {"item": item}, {"section": section}):
            Note.objects.create(profile=main_profile(), text="ok", **parent)

    def test_note_link_needs_exactly_one_target(self):
        note = Note.objects.create(profile=main_profile(), subject=self.subject)
        item = Item.objects.create(profile=main_profile(), subtopic=self.subtopic)
        self.assertRefused(NoteLink, note=note)
        self.assertRefused(NoteLink, note=note, item=item, topic=self.topic)
        NoteLink.objects.create(profile=main_profile(), note=note, item=item)
        NoteLink.objects.create(profile=main_profile(), note=note, topic=self.topic)

    def test_note_link_target_cannot_be_deleted_while_linked(self):
        from django.db.models import ProtectedError

        note = Note.objects.create(profile=main_profile(), subject=self.subject)
        item = Item.objects.create(profile=main_profile(), subtopic=self.subtopic)
        NoteLink.objects.create(profile=main_profile(), note=note, item=item)
        with self.assertRaises(ProtectedError):
            item.delete()


class ItemRuleTests(Base):
    def test_items_cannot_sit_beneath_items_any_more(self):
        self.assertFalse(hasattr(Item, "parent_item"))
        self.assertNotIn("parent_item", [f.name for f in Item._meta.get_fields()])

    def test_plain_is_the_only_kind_choice(self):
        from diary.models import KIND_CHOICES

        self.assertEqual([value for value, _label in KIND_CHOICES], ["plain"])

    def test_citation_layout_defaults_to_inline_and_has_two_choices(self):
        from diary.models import CITATION_LAYOUT_CHOICES

        item = Item.objects.create(profile=main_profile(), subtopic=self.subtopic)
        self.assertEqual(item.citation_layout, "inline")
        self.assertEqual([value for value, _label in CITATION_LAYOUT_CHOICES], ["inline", "lines"])

    def test_plain_item_cannot_hold_a_citation(self):
        # 10d: Case is the one store of citations (migration 0011, item_plain_has_no_citation).
        with self.assertRaises(IntegrityError), transaction.atomic():
            Item.objects.create(profile=main_profile(), subtopic=self.subtopic, kind="plain", citation="A v B")

    def test_plain_item_with_whitespace_citation_is_refused_too(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Item.objects.create(profile=main_profile(), subtopic=self.subtopic, kind="plain", citation="  ")

    def test_a_case_may_have_a_comment_and_no_citation(self):
        item = Item.objects.create(profile=main_profile(), subtopic=self.subtopic)
        case = Case.objects.create(profile=main_profile(), item=item, citation="", comment="<p>only a comment</p>")
        case.clean()
        self.assertEqual(case.comment_plain, "only a comment")

    def test_flag_defaults_and_the_retired_review_switch(self):
        from django.db import IntegrityError, transaction

        item = Item.objects.create(profile=main_profile(), subtopic=self.subtopic)
        self.assertEqual(item.flag, "none")
        self.assertFalse(item.needs_review)
        # D88: the For review switch is retired; a check rule keeps it off.
        with self.assertRaises(IntegrityError), transaction.atomic():
            Item.objects.filter(pk=item.pk).update(needs_review=True)
        self.assertEqual(item.original_line, "")

    def test_clean_rejects_multiline_citation(self):
        item = Item(subtopic=self.subtopic, citation="line one\nline two")
        with self.assertRaises(ValidationError):
            item.clean()


class RichTextTests(Base):
    def test_save_sanitises_and_keeps_plain_copy(self):
        item = Item.objects.create(profile=main_profile(),
            subtopic=self.subtopic,
            text='<p style="color:red">Hello <strong>world</strong><script>x()</script></p>',
        )
        item.refresh_from_db()
        self.assertEqual(item.text, "<p>Hello <b>world</b></p>")
        self.assertEqual(item.text_plain, "Hello world")

    def test_update_fields_save_includes_plain_copy(self):
        item = Item.objects.create(profile=main_profile(), subtopic=self.subtopic, text="old")
        item.text = "<b>new</b>"
        item.save(update_fields=["text"])
        item.refresh_from_db()
        self.assertEqual(item.text_plain, "new")

    def test_case_comment_and_note_text(self):
        multi = Item.objects.create(profile=main_profile(), subtopic=self.subtopic)
        case = Case.objects.create(profile=main_profile(), item=multi, citation="A v B", comment="<em>why</em>")
        self.assertEqual(case.comment, "<i>why</i>")
        self.assertEqual(case.comment_plain, "why")
        note = Note.objects.create(profile=main_profile(), subject=self.subject, text="<u>see</u> <a href='x'>this</a>")
        self.assertEqual(note.text, "<u>see</u> this")
        self.assertEqual(note.text_plain, "see this")

    def test_case_allowed_under_any_item(self):
        plain = Item.objects.create(profile=main_profile(), subtopic=self.subtopic)
        Case(item=plain, citation="A v B").clean()


class UserSettingsTests(Base):
    def test_defaults(self):
        user = User.objects.create_user("zed", password="x-long-pass-123")
        settings_row = UserSettings.objects.create(user=user)
        self.assertEqual(settings_row.export_date_format, "YYYY-MM-DD")
        self.assertEqual(settings_row.section_format, "paren_lower_alpha")
        self.assertEqual(settings_row.item_format, "paren_decimal")
        self.assertFalse(hasattr(settings_row, "nested_item_format"))
        self.assertFalse(hasattr(settings_row, "time_zone"))
        self.assertEqual(user.diary_settings, settings_row)


class ProfileIsolationTests(Base):
    def setUp(self):
        super().setUp()
        self.other_profile = Profile.objects.create(program="diary", name="Junior")

    def test_every_model_has_a_profile(self):
        for obj in (self.subject, self.topic, self.subtopic):
            self.assertEqual(obj.profile, main_profile())

    def test_subject_name_unique_per_profile_but_allowed_across_profiles(self):
        self.assertRefused(Subject, name="contract")
        other = Subject.objects.create(profile=self.other_profile, name="Contract")
        self.assertEqual(other.profile, self.other_profile)

    def test_child_in_another_profile_than_parent_refused(self):
        with self.assertRaises(ValidationError):
            Topic.objects.create(profile=self.other_profile, subject=self.subject, name="Wrong")
        with self.assertRaises(ValidationError):
            Subtopic.objects.create(profile=self.other_profile, topic=self.topic, name="Wrong")
        with self.assertRaises(ValidationError):
            Item.objects.create(profile=self.other_profile, subtopic=self.subtopic, text="x")
        with self.assertRaises(ValidationError):
            Section.objects.create(profile=self.other_profile, subtopic=self.subtopic)

    def test_case_and_note_must_match_parent_profile(self):
        multi = Item.objects.create(profile=main_profile(), subtopic=self.subtopic)
        with self.assertRaises(ValidationError):
            Case.objects.create(profile=self.other_profile, item=multi, citation="A v B")
        with self.assertRaises(ValidationError):
            Note.objects.create(profile=self.other_profile, subject=self.subject)

    def test_notelink_never_crosses_profiles(self):
        note = Note.objects.create(profile=main_profile(), subject=self.subject)
        foreign_subject = Subject.objects.create(profile=self.other_profile, name="Elsewhere")
        foreign_note = Note.objects.create(profile=self.other_profile, subject=foreign_subject)
        with self.assertRaises(ValidationError):
            NoteLink.objects.create(profile=main_profile(), note=note, subject=foreign_subject)
        with self.assertRaises(ValidationError):
            NoteLink.objects.create(profile=main_profile(), note=foreign_note, topic=self.topic)
        with self.assertRaises(ValidationError):
            NoteLink.objects.create(profile=self.other_profile, note=note, subject=foreign_subject)
        NoteLink.objects.create(profile=main_profile(), note=note, topic=self.topic)

    def test_profile_with_records_cannot_be_deleted(self):
        with self.assertRaises(ProtectedError):
            main_profile().delete()
