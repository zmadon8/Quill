from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
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


class Base(TestCase):
    def setUp(self):
        self.subject = Subject.objects.create(name="Contract")
        self.topic = Topic.objects.create(subject=self.subject, name="Formation")
        self.subtopic = Subtopic.objects.create(topic=self.topic, name="Offer")

    def assertRefused(self, model, **fields):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                model.objects.create(**fields)


class SubjectTests(Base):
    def test_blank_name_refused(self):
        self.assertRefused(Subject, name="")

    def test_name_unique_ignoring_case_among_live_subjects(self):
        self.assertRefused(Subject, name="contract")
        self.assertRefused(Subject, name="CONTRACT")

    def test_deleted_subject_does_not_block_name(self):
        Subject.objects.filter(pk=self.subject.pk).update(deleted_at=timezone.now())
        again = Subject.objects.create(name="Contract")
        self.assertIsNone(again.deleted_at)

    def test_two_deleted_subjects_may_share_a_name(self):
        Subject.objects.filter(pk=self.subject.pk).update(deleted_at=timezone.now())
        second = Subject.objects.create(name="Contract")
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
        direct = Subtopic.objects.create(name="Directors", subject=self.subject)
        self.assertEqual(direct.subject, self.subject)

    def test_section_needs_exactly_one_parent(self):
        self.assertRefused(Section, name="s")
        self.assertRefused(Section, name="s", subject=self.subject, topic=self.topic)
        for parent in ({"subject": self.subject}, {"topic": self.topic}, {"subtopic": self.subtopic}):
            Section.objects.create(name="s", **parent)

    def test_item_needs_exactly_one_parent(self):
        self.assertRefused(Item, text="x")
        self.assertRefused(Item, text="x", subject=self.subject, subtopic=self.subtopic)
        nested = Item.objects.create(subtopic=self.subtopic, kind="nested")
        self.assertRefused(Item, text="x", parent_item=nested, subtopic=self.subtopic)
        for parent in ({"subject": self.subject}, {"topic": self.topic}, {"subtopic": self.subtopic}):
            Item.objects.create(text="ok", **parent)

    def test_note_needs_exactly_one_parent(self):
        item = Item.objects.create(subtopic=self.subtopic)
        section = Section.objects.create(subtopic=self.subtopic)
        self.assertRefused(Note, text="x")
        self.assertRefused(Note, text="x", item=item, section=section)
        for parent in ({"subject": self.subject}, {"topic": self.topic}, {"subtopic": self.subtopic},
                       {"item": item}, {"section": section}):
            Note.objects.create(text="ok", **parent)

    def test_note_link_needs_exactly_one_target(self):
        note = Note.objects.create(subject=self.subject)
        item = Item.objects.create(subtopic=self.subtopic)
        self.assertRefused(NoteLink, note=note)
        self.assertRefused(NoteLink, note=note, item=item, topic=self.topic)
        NoteLink.objects.create(note=note, item=item)
        NoteLink.objects.create(note=note, topic=self.topic)

    def test_note_link_target_cannot_be_deleted_while_linked(self):
        from django.db.models import ProtectedError

        note = Note.objects.create(subject=self.subject)
        item = Item.objects.create(subtopic=self.subtopic)
        NoteLink.objects.create(note=note, item=item)
        with self.assertRaises(ProtectedError):
            item.delete()


class ItemRuleTests(Base):
    def test_one_level_of_nesting(self):
        nested = Item.objects.create(subtopic=self.subtopic, kind="nested")
        Item.objects.create(parent_item=nested, kind="plain", text="child")
        self.assertRefused(Item, parent_item=nested, kind="nested")
        self.assertRefused(Item, parent_item=nested, kind="multi")

    def test_multi_item_has_no_own_citation(self):
        self.assertRefused(Item, subtopic=self.subtopic, kind="multi", citation="A v B")
        Item.objects.create(subtopic=self.subtopic, kind="multi")

    def test_plain_item_keeps_citation(self):
        item = Item.objects.create(subtopic=self.subtopic, citation="A v B (2001) 1 SCC 1")
        item.refresh_from_db()
        self.assertEqual(item.citation, "A v B (2001) 1 SCC 1")

    def test_flag_and_review_defaults(self):
        item = Item.objects.create(subtopic=self.subtopic)
        self.assertEqual(item.flag, "none")
        self.assertFalse(item.needs_review)
        self.assertEqual(item.original_line, "")

    def test_clean_rejects_multiline_citation(self):
        item = Item(subtopic=self.subtopic, citation="line one\nline two")
        with self.assertRaises(ValidationError):
            item.clean()

    def test_clean_child_must_sit_under_nested_item(self):
        plain = Item.objects.create(subtopic=self.subtopic)
        child = Item(parent_item=plain)
        with self.assertRaises(ValidationError):
            child.clean()


class RichTextTests(Base):
    def test_save_sanitises_and_keeps_plain_copy(self):
        item = Item.objects.create(
            subtopic=self.subtopic,
            text='<p style="color:red">Hello <strong>world</strong><script>x()</script></p>',
        )
        item.refresh_from_db()
        self.assertEqual(item.text, "<p>Hello <b>world</b></p>")
        self.assertEqual(item.text_plain, "Hello world")

    def test_update_fields_save_includes_plain_copy(self):
        item = Item.objects.create(subtopic=self.subtopic, text="old")
        item.text = "<b>new</b>"
        item.save(update_fields=["text"])
        item.refresh_from_db()
        self.assertEqual(item.text_plain, "new")

    def test_case_comment_and_note_text(self):
        multi = Item.objects.create(subtopic=self.subtopic, kind="multi")
        case = Case.objects.create(item=multi, citation="A v B", comment="<em>why</em>")
        self.assertEqual(case.comment, "<i>why</i>")
        self.assertEqual(case.comment_plain, "why")
        note = Note.objects.create(subject=self.subject, text="<u>see</u> <a href='x'>this</a>")
        self.assertEqual(note.text, "<u>see</u> this")
        self.assertEqual(note.text_plain, "see this")

    def test_case_only_under_multi_item(self):
        plain = Item.objects.create(subtopic=self.subtopic)
        with self.assertRaises(ValidationError):
            Case(item=plain, citation="A v B").clean()


class UserSettingsTests(Base):
    def test_defaults(self):
        user = User.objects.create_user("zed", password="x-long-pass-123")
        settings_row = UserSettings.objects.create(user=user)
        self.assertEqual(settings_row.export_custom_name, "Judgment Diary")
        self.assertEqual(settings_row.export_date_format, "YYYY-MM-DD")
        self.assertEqual(settings_row.section_format, "paren_lower_alpha")
        self.assertEqual(settings_row.item_format, "paren_decimal")
        self.assertEqual(settings_row.nested_item_format, "paren_decimal")
        self.assertEqual(settings_row.time_zone, "Asia/Kolkata")
        self.assertEqual(user.diary_settings, settings_row)
