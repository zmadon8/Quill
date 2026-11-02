"""Trash, permanent delete, History, Undo and the conflict screen (Milestone 3d)."""
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.urls import reverse

from diary import services as svc
from diary.models import Item, Note, NoteLink, Topic, VersionHistory
from diary.tests.helpers import join_main
from diary.tests.service_helpers import PASSWORD
from diary.tests.test_views_item_editor import ItemEditorTestCase
from diary.undo_session import SESSION_KEY

User = get_user_model()


@override_settings(SECURE_SSL_REDIRECT=False)
class TrashTestCase(ItemEditorTestCase):
    def setUp(self):
        super().setUp()
        self.admin = join_main(User.objects.create_user("boss", password=PASSWORD, is_superuser=True), "editor")
        self.admin_client = Client()
        self.admin_client.force_login(self.admin)
        self.trash_url = reverse("trash")

    def trash_post(self, name, data, client=None):
        data = dict(data)
        data.setdefault("next", self.trash_url)
        return (client or self.client).post(reverse(name), data)

    def delete_topic(self):
        svc.delete(self.profile, self.user, "topic", self.topic.pk)

    def resend(self, response, **extra):
        """What the buttons on a conflict page send: the carried fields again (plus ``extra``) to the same address."""
        data = {}
        for name, value in response.context["fields"]:
            data.setdefault(name, []).append(value)
        data.update(extra)
        return self.client.post(response.context["action"], data)


class TrashAccessTests(TrashTestCase):
    def test_readers_get_403_on_every_trash_address(self):
        self.assertEqual(self.reader_client.get(self.trash_url).status_code, 403)
        for name in ("trash_restore", "trash_permanent", "edit_undo", "history_restore"):
            resp = self.reader_client.post(reverse(name), {"kind": "item", "id": self.one.pk})
            self.assertEqual(resp.status_code, 403, name)

    def test_readers_get_403_on_history(self):
        self.assertEqual(self.reader_client.get(reverse("history", args=["item", self.one.pk])).status_code, 403)
        url = reverse("history_version", args=["item", self.one.pk, 1])
        self.assertEqual(self.reader_client.get(url).status_code, 403)

    def test_only_editors_get_a_trash_link(self):
        link = f'href="{self.trash_url}"'
        self.assertContains(self.client.get(reverse("diary_home")), link)
        self.assertNotContains(self.reader_client.get(reverse("diary_home")), link)

    def test_the_trash_screen_is_get_only_and_restore_is_post_only(self):
        self.assertEqual(self.client.post(self.trash_url).status_code, 405)
        self.assertEqual(self.client.get(reverse("trash_restore")).status_code, 405)
        self.assertEqual(self.client.get(reverse("trash_permanent")).status_code, 405)

    def test_restore_needs_the_csrf_token(self):
        svc.delete(self.profile, self.user, "item", self.one.pk)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        resp = strict.post(reverse("trash_restore"), {"kind": "item", "id": self.one.pk})
        self.assertEqual(resp.status_code, 403)
        self.assertIsNotNone(self.get(self.one).deleted_at)

    def test_another_profiles_records_are_404_and_not_listed(self):
        subject = self.make("subject", profile=self.other_profile, name="Elsewhere")
        topic = self.make("topic", ("subject", subject.pk), profile=self.other_profile, name="T")
        item = self.make("item", ("topic", topic.pk), profile=self.other_profile, text="x")
        svc.delete(self.other_profile, self.user, "item", item.pk)
        self.assertEqual(self.client.get(self.trash_url).context["entries"], [])
        self.assertEqual(self.trash_post("trash_restore", {"kind": "item", "id": item.pk}).status_code, 404)
        self.assertEqual(self.trash_post("trash_permanent", {"kind": "item", "id": item.pk}, self.admin_client).status_code, 404)
        self.assertIsNotNone(self.get(item).deleted_at)
        self.assertEqual(self.client.get(reverse("history", args=["item", item.pk])).status_code, 404)

    def test_unknown_record_types_are_404(self):
        self.assertEqual(self.trash_post("trash_restore", {"kind": "notelink", "id": 1}).status_code, 404)
        self.assertEqual(self.client.get(reverse("history", args=["bogus", 1])).status_code, 404)


class TrashListTests(TrashTestCase):
    def test_a_deleted_topic_is_one_entry_with_its_path_and_size(self):
        self.delete_topic()
        entries = self.client.get(self.trash_url).context["entries"]
        self.assertEqual(len(entries), 1)
        self.assertEqual((entries[0]["type"], entries[0]["label"], entries[0]["path"]), ("topic", "Formation", "Contract"))
        self.assertEqual(entries[0]["count"], 6)
        self.assertContains(self.client.get(self.trash_url), "Restore")

    def test_an_item_deleted_earlier_is_listed_on_its_own_with_the_full_path(self):
        svc.delete(self.profile, self.user, "item", self.one.pk)
        self.delete_topic()
        entries = self.client.get(self.trash_url).context["entries"]
        self.assertEqual(sorted((e["type"], e["path"]) for e in entries),
                         [("item", "Contract > Formation"), ("topic", "Contract")])

    def test_an_empty_trash_says_so(self):
        self.assertContains(self.client.get(self.trash_url), "The Trash is empty")

    def test_records_left_behind_by_a_chain_restore_stay_visible(self):
        self.delete_topic()
        self.trash_post("trash_restore", {**self.rec(self.one), "restore_parents": "1"})
        entries = self.client.get(self.trash_url).context["entries"]
        self.assertEqual(sorted(e["label"] for e in entries), ["S", "four", "three", "two"])


class RestoreTests(TrashTestCase):
    def test_restoring_a_topic_brings_the_whole_subtree_back_in_place(self):
        self.delete_topic()
        resp = self.trash_post("trash_restore", self.rec(self.topic))
        self.assertRedirects(resp, self.trash_url, fetch_redirect_response=False)
        self.assertIsNone(self.get(self.topic).deleted_at)
        self.assertEqual(self.order(), ["one", "two", "S", "three", "four"])
        self.assertEqual(Item.objects.filter(topic=self.topic).count(), 4)
        self.assertEqual(self.client.get(self.trash_url).context["entries"], [])

    def test_a_parent_in_trash_asks_before_restoring_the_chain(self):
        self.delete_topic()
        resp = self.trash_post("trash_restore", self.rec(self.one))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "diary/trash_parents.html")
        self.assertEqual(resp.context["chain"], [{"kind_name": "Topic", "label": "Formation"}])
        self.assertContains(resp, "Restore them too")
        self.assertIsNotNone(self.get(self.one).deleted_at)
        self.assertIsNotNone(self.get(self.topic).deleted_at)

    def test_agreeing_restores_the_parent_chain_and_only_that_item(self):
        self.delete_topic()
        resp = self.trash_post("trash_restore", {**self.rec(self.one), "restore_parents": "1"})
        self.assertEqual(resp.status_code, 302)
        self.assertIsNone(self.get(self.topic).deleted_at)
        self.assertIsNone(self.get(self.one).deleted_at)
        self.assertIsNotNone(self.get(self.two).deleted_at)

    def test_a_topic_name_clash_asks_for_a_new_name(self):
        self.delete_topic()
        self.make("topic", ("subject", self.subject.pk), name="Formation")
        resp = self.trash_post("trash_restore", self.rec(self.topic))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "diary/trash_rename.html")
        self.assertEqual(resp.context["clash"].suggestion, "Formation (restored)")
        self.assertContains(resp, "Formation (restored)")
        self.assertIsNotNone(self.get(self.topic).deleted_at)
        field = resp.context["field"]
        self.assertEqual(field, f"rename_topic_{self.topic.pk}")
        data = dict(resp.context["fields"])
        data[field] = "Formation of contracts"
        self.assertEqual(self.client.post(reverse("trash_restore"), data).status_code, 302)
        restored = self.get(self.topic)
        self.assertEqual((restored.name, restored.deleted_at), ("Formation of contracts", None))
        self.assertEqual(self.order(), ["one", "two", "S", "three", "four"])

    def test_a_subject_name_clash_asks_for_a_new_name(self):
        svc.delete(self.profile, self.user, "subject", self.subject.pk)
        self.make("subject", name="contract")
        resp = self.trash_post("trash_restore", self.rec(self.subject))
        self.assertTemplateUsed(resp, "diary/trash_rename.html")
        self.assertEqual(resp.context["clash"].record_type, "subject")
        data = dict(resp.context["fields"])
        data[resp.context["field"]] = "Contract law"
        self.client.post(reverse("trash_restore"), data)
        self.assertEqual(self.get(self.subject).name, "Contract law")
        self.assertIsNone(self.get(self.one).deleted_at)

    def test_a_chosen_name_that_is_also_taken_is_refused_and_nothing_is_restored(self):
        self.delete_topic()
        self.make("topic", ("subject", self.subject.pk), name="Formation")
        resp = self.trash_post("trash_restore", {**self.rec(self.topic), f"rename_topic_{self.topic.pk}": "Formation"})
        self.assertEqual(resp.status_code, 302)
        self.assertIsNotNone(self.get(self.topic).deleted_at)

    def test_restoring_something_not_in_the_trash_changes_nothing(self):
        before = self.get(self.one).version
        resp = self.trash_post("trash_restore", self.rec(self.one))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.get(self.one).version, before)

    def test_a_stale_restore_shows_the_conflict_screen(self):
        svc.delete(self.profile, self.user, "item", self.one.pk)
        stale = self.rec(self.one)
        stale["version"] -= 1
        resp = self.trash_post("trash_restore", stale)
        self.assertEqual(resp.status_code, 409)
        self.assertContains(resp, "Keep mine", status_code=409)
        self.assertIsNotNone(self.get(self.one).deleted_at)
        self.assertEqual(self.resend(resp).status_code, 302)
        self.assertIsNone(self.get(self.one).deleted_at)

class PermanentDeleteTests(TrashTestCase):
    def perm(self, obj, client=None, **extra):
        return self.trash_post("trash_permanent", {"kind": self.ref(obj)[0], "id": obj.pk, **extra}, client or self.admin_client)

    def test_an_editor_who_is_not_an_admin_gets_403_and_nothing_is_deleted(self):
        svc.delete(self.profile, self.user, "item", self.one.pk)
        self.assertEqual(self.perm(self.one, self.client).status_code, 403)
        self.assertEqual(self.perm(self.one, self.client, confirmed="1").status_code, 403)
        self.assertTrue(Item._base_manager.filter(pk=self.one.pk).exists())

    def test_an_admin_who_is_only_a_reader_of_the_profile_gets_403(self):
        reader_admin = join_main(User.objects.create_user("rootr", password=PASSWORD, is_superuser=True), "reader")
        client = Client()
        client.force_login(reader_admin)
        svc.delete(self.profile, self.user, "item", self.one.pk)
        self.assertEqual(self.perm(self.one, client, confirmed="1").status_code, 403)
        self.assertTrue(Item._base_manager.filter(pk=self.one.pk).exists())

    def test_the_admin_sees_the_button_and_editors_do_not(self):
        svc.delete(self.profile, self.user, "item", self.one.pk)
        self.assertContains(self.admin_client.get(self.trash_url), "Delete permanently")
        self.assertNotContains(self.client.get(self.trash_url), "Delete permanently")

    def test_the_first_press_names_what_is_lost_and_deletes_nothing(self):
        self.delete_topic()
        resp = self.perm(self.topic)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "diary/trash_permanent.html")
        self.assertEqual(resp.context["total"], 6)
        self.assertIn(("Item", 4), resp.context["counts"])
        self.assertContains(resp, "Formation")
        self.assertContains(resp, "Yes, delete these 6 records permanently")
        self.assertTrue(Topic._base_manager.filter(pk=self.topic.pk).exists())

    def test_the_second_confirmation_deletes_the_whole_batch_for_good_but_keeps_history(self):
        self.delete_topic()
        resp = self.perm(self.topic, confirmed="1")
        self.assertRedirects(resp, self.trash_url, fetch_redirect_response=False)
        self.assertFalse(Topic._base_manager.filter(pk=self.topic.pk).exists())
        self.assertFalse(Item._base_manager.filter(topic_id=self.topic.pk).exists())
        self.assertTrue(VersionHistory.objects.filter(record_type="topic", record_id=self.topic.pk).exists())
        self.assertEqual(self.client.get(self.trash_url).context["entries"], [])

    def test_a_record_that_is_not_in_the_trash_is_refused(self):
        resp = self.perm(self.one, confirmed="1")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Item._base_manager.filter(pk=self.one.pk, deleted_at__isnull=True).exists())

    def test_incoming_note_links_refuse_and_are_listed(self):
        other = self.make("note", ("topic", self.topic.pk), text="points here")
        svc.add_link(self.profile, self.user, other.pk, ("item", self.one.pk))
        svc.delete(self.profile, self.user, "item", self.one.pk)
        for extra in ({}, {"confirmed": "1"}):
            resp = self.perm(self.one, **extra)
            self.assertContains(resp, "points here", status_code=resp.status_code)
            self.assertContains(resp, "Refused", status_code=resp.status_code)
            self.assertNotContains(resp, "Yes, delete", status_code=resp.status_code)
        self.assertEqual(self.perm(self.one, confirmed="1").status_code, 409)
        self.assertTrue(Item._base_manager.filter(pk=self.one.pk).exists())
        self.assertTrue(NoteLink._base_manager.filter(note=other).exists())
        self.assertTrue(Note._base_manager.filter(pk=other.pk).exists())

    def test_permanent_delete_is_a_post_with_csrf(self):
        svc.delete(self.profile, self.user, "item", self.one.pk)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.admin)
        resp = strict.post(reverse("trash_permanent"), {"kind": "item", "id": self.one.pk, "confirmed": "1"})
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Item._base_manager.filter(pk=self.one.pk).exists())


class HistoryTests(TrashTestCase):
    def setUp(self):
        super().setUp()
        svc.edit(self.profile, self.user, "item", self.one.pk, {"text": "<p>second</p>"})
        svc.edit(self.profile, self.user, "item", self.one.pk, {"text": "<p>third</p>"})
        self.url = reverse("history", args=["item", self.one.pk])

    def test_the_list_shows_every_version_newest_first(self):
        resp = self.client.get(self.url)
        self.assertEqual([e["version"] for e in resp.context["entries"]], [3, 2, 1])
        self.assertEqual([e["current"] for e in resp.context["entries"]], [True, False, False])
        self.assertEqual(resp.context["entries"][-1]["kind"], "Create")
        self.assertContains(resp, "Time (IST)")

    def test_history_exists_for_every_record_type(self):
        multi, first, _ = self.cited()
        for obj in (self.subject, self.topic, self.sec, self.one, multi, first):
            resp = self.client.get(reverse("history", args=[self.ref(obj)[0], obj.pk]))
            self.assertEqual(resp.status_code, 200, self.ref(obj))

    def test_a_version_shows_the_full_snapshot(self):
        resp = self.client.get(reverse("history_version", args=["item", self.one.pk, 2]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "second")
        self.assertContains(resp, "Restore this version")
        names = [f["name"] for f in resp.context["fields"]]
        self.assertIn("text", names)
        self.assertIn("citation", names)

    def test_an_old_version_with_a_citation_warns_that_case_a_is_replaced(self):
        row = VersionHistory.objects.get(record_type="item", record_id=self.one.pk, version=2)
        row.snapshot = {**row.snapshot, "citation": "Old v New"}
        row.save()
        resp = self.client.get(reverse("history_version", args=["item", self.one.pk, 2]))
        self.assertTrue(resp.context["replaces_case_a"])
        self.assertContains(resp, "replaces what Case (a) holds now")
        self.assertContains(resp, "Old v New")

    def test_a_version_without_an_old_citation_has_no_case_a_warning(self):
        resp = self.client.get(reverse("history_version", args=["item", self.one.pk, 2]))
        self.assertFalse(resp.context["replaces_case_a"])
        self.assertNotContains(resp, "replaces what Case (a) holds now")

    def test_the_current_version_has_no_restore_button(self):
        resp = self.client.get(reverse("history_version", args=["item", self.one.pk, 3]))
        self.assertNotContains(resp, "Restore this version")

    def test_a_missing_version_is_404(self):
        self.assertEqual(self.client.get(reverse("history_version", args=["item", self.one.pk, 99])).status_code, 404)

    def test_restoring_an_older_version_creates_a_new_version(self):
        original = VersionHistory.objects.get(record_type="item", record_id=self.one.pk, version=1).snapshot["text"]
        resp = self.trash_post("history_restore", {"kind": "item", "id": self.one.pk, "version": 3, "restore_version": 1})
        self.assertEqual(resp.status_code, 302)
        item = self.get(self.one)
        self.assertEqual((item.text, item.version), (original, 4))
        rows = list(VersionHistory.objects.filter(record_type="item", record_id=self.one.pk).order_by("version"))
        self.assertEqual([r.version for r in rows], [1, 2, 3, 4])
        self.assertEqual(rows[-1].change_kind, "restore")
        self.assertIn("third", rows[2].snapshot["text"])

    def test_a_stale_restore_is_a_conflict(self):
        resp = self.trash_post("history_restore", {"kind": "item", "id": self.one.pk, "version": 1, "restore_version": 1})
        self.assertEqual(resp.status_code, 409)
        self.assertIn("third", self.get(self.one).text)

    def test_a_record_in_the_trash_cannot_have_a_version_restored(self):
        svc.delete(self.profile, self.user, "item", self.one.pk)
        version = self.get(self.one).version
        resp = self.trash_post("history_restore", {"kind": "item", "id": self.one.pk, "version": version, "restore_version": 1})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("third", self.get(self.one).text)
        page = self.client.get(self.url)
        self.assertTrue(page.context["in_trash"])
        self.assertFalse(page.context["can_restore"])

    def test_restore_of_another_profiles_record_is_404(self):
        subject = self.make("subject", profile=self.other_profile, name="Elsewhere")
        resp = self.trash_post("history_restore", {"kind": "subject", "id": subject.pk, "version": 1, "restore_version": 1})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(self.client.get(reverse("history", args=["subject", subject.pk])).status_code, 404)

    def test_the_editing_card_links_to_the_history(self):
        resp = self.client.get(reverse("edit_inline_card"), {"kind": "item", "id": self.one.pk})
        self.assertIn(f'href="{self.url}?next=', resp.json()["html"])


class UndoViewTests(TrashTestCase):
    def groups(self):
        return [e["group"] for e in self.client.session.get(SESSION_KEY, [])]

    def undo(self, group, **extra):
        return self.client.post(reverse("edit_undo"), {"group": group, "next": self.next, **extra})

    def test_a_delete_through_the_screen_can_be_undone_with_the_button(self):
        self.post("edit_delete", {**self.rec(self.one), "confirmed": "1"})
        self.assertEqual(len(self.groups()), 1)
        page = self.client.get(self.next)
        self.assertContains(page, "data-undo-form")
        self.assertContains(page, "Undo: Deleted 1 Item")
        resp = self.undo(self.groups()[-1])
        self.assertEqual(resp.status_code, 302)
        self.assertIsNone(self.get(self.one).deleted_at)
        self.assertEqual(self.order(), ["one", "two", "S", "three", "four"])

    def test_the_undo_button_is_only_in_edit_mode(self):
        url = reverse("read_subject", args=[self.subject.pk])
        self.assertNotContains(self.client.get(url), "data-undo-form")
        self.assertContains(self.client.get(url + "?edit=1"), "Nothing to undo in this session")

    def test_deleting_a_topic_is_one_undo_step(self):
        self.post("edit_delete", {**self.rec(self.topic), "confirmed": "1"})
        self.assertEqual(len(self.groups()), 1)
        self.undo(self.groups()[-1])
        self.assertIsNone(self.get(self.topic).deleted_at)
        self.assertEqual(self.order(), ["one", "two", "S", "three", "four"])

    def test_undoing_a_move_puts_the_numbers_back(self):
        self.post("edit_move", {**self.rec(self.four), "direction": "up"})
        self.assertEqual(self.order(), ["one", "two", "S", "four", "three"])
        self.undo(self.groups()[-1])
        self.assertEqual(self.order(), ["one", "two", "S", "three", "four"])

    def test_an_action_that_was_not_made_in_this_session_cannot_be_undone(self):
        result = svc.edit(self.profile, self.user, "item", self.one.pk, {"text": "<p>elsewhere</p>"})
        resp = self.undo(str(result.group))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("elsewhere", self.get(self.one).text)
        self.assertTrue(self.msgs(resp))
        self.assertTrue(self.msgs(self.undo("not-a-group")))

    def test_undo_belongs_to_the_session_that_made_the_change(self):
        self.post("edit_delete", {**self.rec(self.one), "confirmed": "1"})
        other = Client()
        other.force_login(self.user)
        group = self.groups()[-1]
        resp = other.post(reverse("edit_undo"), {"group": group, "next": self.next})
        self.assertEqual(resp.status_code, 302)
        self.assertIsNotNone(self.get(self.one).deleted_at)

    def test_one_item_editor_save_is_one_undo_step(self):
        multi, first, second = self.cited()
        before = VersionHistory.objects.order_by("-id").first().id
        rows = self.case_rows([(first, "A v B2", "<b>note</b>"), (None, "E v F", "")])
        resp = self.client.post(self.editor_url(multi), {
            "version": self.get(multi).version, "text": "<p>new text</p>", "flag": "none", "next": self.next, **rows})
        self.assertEqual(resp.status_code, 302, self.msgs(resp))
        groups = set(VersionHistory.objects.filter(id__gt=before).values_list("group", flat=True))
        self.assertEqual(len(groups), 1)
        self.assertEqual(self.groups(), [str(groups.pop())])
        self.assertEqual(sorted(c for c, _ in self.live_cases(multi)), ["A v B2", "E v F"])
        self.undo(self.groups()[-1])
        self.assertEqual(self.get(multi).text, "m")
        self.assertEqual(sorted(c for c, _ in self.live_cases(multi)), ["A v B", "C v D"])
        self.assertIsNone(self.get(second).deleted_at)

    def test_a_record_changed_since_asks_before_undoing(self):
        self.save(self.one, text="<p>mine</p>")
        original = VersionHistory.objects.get(record_type="item", record_id=self.one.pk, version=1).snapshot["text"]
        svc.edit(self.profile, self.user, "item", self.one.pk, {"text": "<p>later</p>"})
        resp = self.undo(self.groups()[-1])
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "diary/undo_confirm.html")
        self.assertContains(resp, "Undo anyway")
        self.assertEqual([c["id"] for c in resp.context["changed"]], [self.one.pk])
        self.assertIn("later", self.get(self.one).text)
        resp = self.undo(self.groups()[-1], force="1")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.get(self.one).text, original)

    def test_someone_elses_later_change_is_never_undone(self):
        self.save(self.one, text="<p>mine</p>")
        svc.edit(self.profile, self.user2, "item", self.one.pk, {"text": "<p>theirs</p>"})
        resp = self.undo(self.groups()[-1], force="1")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("theirs", self.get(self.one).text)
        self.assertTrue(self.msgs(resp))

    def test_undoing_is_itself_an_action_that_can_be_undone(self):
        self.post("edit_delete", {**self.rec(self.one), "confirmed": "1"})
        self.undo(self.groups()[-1])
        self.assertIsNone(self.get(self.one).deleted_at)
        self.undo(self.groups()[-1])
        self.assertIsNotNone(self.get(self.one).deleted_at)

    def test_undo_is_post_only(self):
        self.assertEqual(self.client.get(reverse("edit_undo")).status_code, 405)


class ConflictScreenTests(TrashTestCase):
    def test_a_stale_rename_shows_both_versions_and_three_choices(self):
        stale = self.rec(self.topic)
        svc.edit(self.profile, self.user2, "topic", self.topic.pk, {"name": "Changed elsewhere"})
        resp = self.post("edit_rename", {**stale, "name": "Mine"})
        self.assertEqual(resp.status_code, 409)
        self.assertContains(resp, "This Topic has changed", status_code=409)
        self.assertEqual(resp.context["rows"], [("Name", "Mine", "Changed elsewhere", True)])
        for text in ("Keep mine", "Keep theirs", "Edit and merge", "Changed elsewhere"):
            self.assertContains(resp, text, status_code=409)
        self.assertEqual(self.get(self.topic).name, "Changed elsewhere")

    def test_keep_mine_sends_the_same_change_again_at_the_current_version(self):
        stale = self.rec(self.topic)
        svc.edit(self.profile, self.user2, "topic", self.topic.pk, {"name": "Changed elsewhere"})
        resp = self.post("edit_rename", {**stale, "name": "Mine"})
        fields = dict(resp.context["fields"])
        self.assertEqual(int(fields["version"]), self.get(self.topic).version)
        self.assertEqual(resp.context["action"], reverse("edit_rename"))
        resp = self.resend(resp, name="Mine")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.get(self.topic).name, "Mine")
        history = [r.snapshot["name"] for r in self.history(self.topic)]
        self.assertIn("Changed elsewhere", history)

    def test_keep_theirs_changes_nothing_and_goes_back(self):
        stale = self.rec(self.topic)
        svc.edit(self.profile, self.user2, "topic", self.topic.pk, {"name": "Changed elsewhere"})
        resp = self.post("edit_rename", {**stale, "name": "Mine"})
        self.assertEqual(resp.context["next_url"], self.next)
        self.assertContains(resp, f'href="{self.next}"', status_code=409)
        self.assertEqual(self.get(self.topic).name, "Changed elsewhere")

    def test_edit_and_merge_lets_the_name_be_changed_before_saving(self):
        stale = self.rec(self.topic)
        svc.edit(self.profile, self.user2, "topic", self.topic.pk, {"name": "Changed elsewhere"})
        resp = self.post("edit_rename", {**stale, "name": "Mine"})
        self.assertEqual(resp.context["merge"]["type"], "fields")
        self.assertEqual(resp.context["merge"]["value"], "Mine")
        self.assertContains(resp, "Save merged", status_code=409)
        self.assertEqual(self.resend(resp, name="Mine and theirs").status_code, 302)
        self.assertEqual(self.get(self.topic).name, "Mine and theirs")

    def test_a_stale_delete_can_be_kept_or_dropped(self):
        stale = {**self.rec(self.one), "confirmed": "1"}
        svc.edit(self.profile, self.user2, "item", self.one.pk, {"text": "<p>uno</p>"})
        resp = self.post("edit_delete", stale)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.context["rows"][0][0:2], ("What you asked for", "Move to the Trash"))
        self.assertIsNone(self.get(self.one).deleted_at)
        self.assertEqual(resp.context["merge"], {})
        self.assertEqual(self.resend(resp).status_code, 302)
        self.assertIsNotNone(self.get(self.one).deleted_at)

    def test_a_stale_move_offers_the_picker_and_keep_mine_moves(self):
        stale = {**self.rec(self.four), "direction": "up"}
        svc.edit(self.profile, self.user2, "item", self.four.pk, {"text": "<p>vier</p>"})
        resp = self.post("edit_move", stale)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.context["merge"], {})
        self.assertEqual(self.resend(resp).status_code, 302)
        self.assertEqual(self.order(), ["one", "two", "S", "vier", "three"])

    def test_a_stale_move_to_a_place_offers_to_choose_the_place_again(self):
        sub = self.make("subtopic", ("topic", self.topic.pk), name="Sub")
        stale = {**self.rec(self.sec), "parent": f"subtopic:{sub.pk}", "confirmed": "1"}
        svc.edit(self.profile, self.user2, "section", self.sec.pk, {"name": "S2"})
        resp = self.post("edit_move", stale)
        self.assertEqual(resp.status_code, 409)
        merge = resp.context["merge"]
        self.assertEqual(merge["type"], "picker")
        self.assertEqual(int(dict(merge["fields"])["version"]), self.get(self.sec).version)
        self.assertContains(resp, "Choose the place again", status_code=409)
        picker = self.client.post(reverse("edit_move_to"), dict(merge["fields"]))
        self.assertEqual(picker.status_code, 200)

    def typed_editor_conflict(self):
        opened = self.get(self.one).version
        svc.edit(self.profile, self.user2, "item", self.one.pk, {"text": "<p>theirs</p>"})
        return self.client.post(self.editor_url(self.one), {
            "version": opened, "text": "<p>My typed words</p>", "flag": "none",
            "flag_text": "", "review_note": "", "next": self.next, **self.case_rows([(None, "My citation", "")])})

    def test_the_item_conflict_shows_every_typed_field_next_to_the_saved_value(self):
        resp = self.typed_editor_conflict()
        self.assertEqual(resp.status_code, 409)
        rows = {label: (mine, theirs) for label, mine, theirs, _ in resp.context["rows"]}
        self.assertEqual(rows["Text"], ("My typed words", "theirs"))
        self.assertEqual(rows["Citation 1"], ("My citation", ""))
        self.assertEqual(resp.context["merge"], {"type": "editor"})

    def test_edit_and_merge_reopens_the_editor_with_what_was_typed_and_saves_nothing(self):
        resp = self.typed_editor_conflict()
        current = self.get(self.one).version
        merged = self.resend(resp, merge="1")
        self.assertEqual(merged.status_code, 200)
        self.assertTemplateUsed(merged, "diary/item_editor.html")
        self.assertContains(merged, "My typed words")
        self.assertContains(merged, "My citation")
        self.assertContains(merged, "The saved version")
        self.assertContains(merged, f'name="version" value="{current}"')
        self.assertEqual(self.get(self.one).version, current)
        saved = self.client.post(self.editor_url(self.one), {
            "version": current, "text": "<p>merged words</p>", "flag": "none", "next": self.next,
            **self.case_rows([(None, "My citation", "")])})
        self.assertEqual(saved.status_code, 302)
        self.assertIn("merged words", self.get(self.one).text)

    def test_keep_mine_on_an_item_saves_what_was_typed_over_the_other_version(self):
        resp = self.typed_editor_conflict()
        self.assertEqual(self.resend(resp).status_code, 302)
        item = self.get(self.one)
        self.assertIn("My typed words", item.text)
        self.assertEqual(self.live_cases(item), [("My citation", "")])
        self.assertIn("theirs", [r.snapshot["text"] for r in self.history(self.one)][1])

    def test_keep_mine_with_a_changed_case_refreshes_every_version_and_saves_everything(self):
        multi, first, second = self.cited()
        rows = self.case_rows([(first, "A v B", ""), (second, "C v D2", "")])
        svc.edit(self.profile, self.user2, "case", first.pk, {"citation": "Changed"})
        resp = self.client.post(self.editor_url(multi), {
            "version": self.get(multi).version, "text": "<p>new text</p>", "flag": "none", "next": self.next, **rows})
        self.assertEqual(resp.status_code, 409)
        self.assertContains(resp, "new text", status_code=409)
        self.assertEqual(self.resend(resp).status_code, 302)
        self.assertEqual(self.live_cases(multi), [("A v B", ""), ("C v D2", "")])
        self.assertIn("new text", self.get(multi).text)

    def test_nothing_typed_is_lost_when_the_conflict_is_on_a_case(self):
        multi, first, second = self.cited()
        rows = self.case_rows([(first, "Typed one", "<i>typed comment</i>"), (second, "Typed two", "")])
        svc.edit(self.profile, self.user2, "case", second.pk, {"citation": "Elsewhere"})
        resp = self.client.post(self.editor_url(multi), {
            "version": self.get(multi).version, "text": "<p>typed text</p>", "flag": "none", "next": self.next, **rows})
        self.assertEqual(resp.status_code, 409)
        for text in ("Typed one", "typed comment", "Typed two", "typed text", "Elsewhere"):
            self.assertContains(resp, text, status_code=409)

    def test_the_review_note_can_be_merged(self):
        stale = self.rec(self.one)
        svc.edit(self.profile, self.user2, "item", self.one.pk, {"text": "<p>theirs</p>"})
        resp = self.post("edit_review", {**stale, "set": "1", "note": "check this"})
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.context["merge"]["type"], "fields")
        self.assertEqual(self.resend(resp, note="check this please").status_code, 302)
        item = self.get(self.one)
        self.assertEqual((item.needs_review, item.review_note), (True, "check this please"))

