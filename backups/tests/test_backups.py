import gzip
import hashlib
import json
import uuid
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Profile, ProfileMembership, SuiteName
from backups import registry, services
from backups.management.commands import migrate_with_backup
from backups.models import BackupFile, BackupLog
from diary.models import (
    Case,
    Item,
    Note,
    NoteLink,
    Section,
    Subject,
    Subtopic,
    Topic,
    TrashBatch,
    UserSettings,
    VersionHistory,
)
from diary.tests.helpers import allow_old_shape_items, main_profile

User = get_user_model()
PASSWORD = "correct-horse-battery-9"
MAX = 10 * 1024 * 1024


def gunzip_json(raw):
    return json.loads(gzip.decompress(bytes(raw)).decode("utf-8"))


def set_age(backup, days):
    BackupFile.objects.filter(pk=backup.pk).update(created_at=timezone.now() - timedelta(days=days))


@override_settings(SECURE_SSL_REDIRECT=False)
class BackupBase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("boss", password=PASSWORD, is_superuser=True, is_staff=True)
        self.alice = User.objects.create_user("alice", password=PASSWORD)
        self.bob = User.objects.create_user("bob", password=PASSWORD)

    def usernames(self):
        return set(User.objects.values_list("username", flat=True))

    def login_admin(self):
        self.client.login(username="boss", password=PASSWORD)


class BackupRoleAccessTests(BackupBase):
    def test_editor_and_reader_refused(self):
        ProfileMembership.objects.create(user=self.alice, profile=main_profile(), role="editor")
        for name in ("alice", "bob"):
            self.client.login(username=name, password=PASSWORD)
            for url in ("backup_list", "restore_upload"):
                self.assertEqual(self.client.get(reverse(url)).status_code, 403, (name, url))
            self.assertEqual(self.client.post(reverse("backup_now")).status_code, 403)
            self.client.logout()


class CreateBackupTests(BackupBase):
    def test_create_backup_contents_and_log(self):
        backup = services.create_backup("manual", self.admin)
        doc = gunzip_json(backup.data)
        self.assertEqual(doc["format"], "judgment-diary-backup")
        self.assertEqual(doc["format_version"], 1)
        expected = {label: 0 for label in registry.BACKUP_MODELS}
        expected["accounts.User"] = 3
        expected["accounts.Profile"] = 1  # the default "Main" profile created by the data migration
        self.assertEqual(doc["counts"], expected)
        self.assertEqual(Profile.objects.get().name, "Main")
        names = {r["fields"]["username"] for r in doc["models"]["accounts.User"]}
        self.assertEqual(names, {"boss", "alice", "bob"})
        self.assertTrue(backup.filename.startswith("judgment-diary-backup-"))
        self.assertTrue(backup.filename.endswith("-manual.json.gz"))
        self.assertEqual(backup.sha256, hashlib.sha256(bytes(backup.data)).hexdigest())
        self.assertEqual(backup.size_bytes, len(bytes(backup.data)))
        log = BackupLog.objects.get()
        self.assertTrue(log.success)
        self.assertEqual(log.kind, "manual")
        self.assertEqual(log.backup, backup)

    def test_backup_excludes_its_own_tables(self):
        services.create_backup("daily")
        second = services.create_backup("daily")
        doc = gunzip_json(second.data)
        self.assertEqual(list(doc["models"]), registry.BACKUP_MODELS)
        self.assertNotIn("backups.BackupFile", doc["models"])

    def test_failure_writes_failed_log_and_reraises(self):
        with mock.patch("backups.services.serializers.serialize", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                services.create_backup("manual", self.admin)
        self.assertEqual(BackupFile.objects.count(), 0)
        log = BackupLog.objects.get()
        self.assertFalse(log.success)
        self.assertIn("boom", log.message)


class RunBackupCommandTests(BackupBase):
    def test_run_backup_prunes_old_failed_logins(self):
        from accounts.models import FailedLogin

        FailedLogin.objects.create(username_lower="stale", ip="1.1.1.1", at=timezone.now() - timedelta(days=2))
        FailedLogin.objects.create(username_lower="fresh", ip="1.1.1.1", at=timezone.now())
        call_command("run_backup", stdout=StringIO())
        self.assertEqual(list(FailedLogin.objects.values_list("username_lower", flat=True)), ["fresh"])

    def test_run_backup_creates_daily_backup(self):
        out = StringIO()
        call_command("run_backup", stdout=out)
        self.assertEqual(BackupFile.objects.filter(kind="daily").count(), 1)
        self.assertIn("Daily backup OK", out.getvalue())
        self.assertTrue(BackupLog.objects.filter(kind="prune", success=True).exists())

    def test_run_backup_failure_raises_command_error(self):
        with mock.patch("backups.services.serializers.serialize", side_effect=RuntimeError("boom")):
            with self.assertRaises(CommandError):
                call_command("run_backup", stdout=StringIO())
        self.assertTrue(BackupLog.objects.filter(kind="daily", success=False).exists())


class RetentionTests(BackupBase):
    def test_prune_keeps_recent_and_newest(self):
        ages = {10: None, 29: None, 31: None, 40: None, 100: None}
        for days in ages:
            ages[days] = services.create_backup("daily")
            set_age(ages[days], days)
        removed = services.prune_old_backups()
        self.assertEqual(removed, 2)
        remaining = set(BackupFile.objects.values_list("pk", flat=True))
        self.assertEqual(remaining, {ages[10].pk, ages[29].pk, ages[31].pk})
        self.assertTrue(BackupLog.objects.filter(kind="prune", success=True).exists())

    def test_prune_never_leaves_zero_backups(self):
        only = services.create_backup("daily")
        set_age(only, 500)
        self.assertEqual(services.prune_old_backups(), 0)
        self.assertEqual(BackupFile.objects.count(), 1)

    def test_prune_never_removes_import_backups(self):
        old_daily = services.create_backup("daily")
        before = services.create_backup("pre_import")
        after = services.create_backup("post_import")
        newest = services.create_backup("daily")
        for backup in (old_daily, before, after):
            set_age(backup, 400)
        self.assertEqual(services.prune_old_backups(), 1)
        remaining = set(BackupFile.objects.values_list("pk", flat=True))
        self.assertEqual(remaining, {before.pk, after.pk, newest.pk})

    def test_prune_failure_is_logged_not_raised(self):
        services.create_backup("daily")
        with mock.patch("backups.services.policy.select_expired", side_effect=RuntimeError("bad")):
            self.assertEqual(services.prune_old_backups(), 0)
        self.assertTrue(BackupLog.objects.filter(kind="prune", success=False).exists())


class ParseTests(BackupBase):
    def test_rejects_garbage(self):
        with self.assertRaises(services.BackupError):
            services.parse_backup(b"not a gzip file", MAX)

    def test_rejects_wrong_json(self):
        with self.assertRaises(services.BackupError):
            services.parse_backup(gzip.compress(b'{"hello": 1}'), MAX)

    def test_rejects_unknown_model(self):
        doc = gunzip_json(services.create_backup("daily").data)
        doc["models"]["auth.Group"] = []
        with self.assertRaises(services.BackupError):
            services.parse_backup(gzip.compress(json.dumps(doc).encode()), MAX)

    def test_rejects_too_large_when_decompressed(self):
        raw = services.create_backup("daily").data
        with self.assertRaises(services.BackupError):
            services.parse_backup(raw, 50)

    def test_accepts_plain_json(self):
        raw = gzip.decompress(bytes(services.create_backup("daily").data))
        self.assertEqual(services.parse_backup(raw, MAX)["format_version"], 1)

    def test_rejects_plain_json_that_is_not_a_backup(self):
        with self.assertRaises(services.BackupError):
            services.parse_backup(b'{"hello": 1}', MAX)

    def test_rejects_plain_json_too_large(self):
        raw = gzip.decompress(bytes(services.create_backup("daily").data))
        with self.assertRaises(services.BackupError):
            services.parse_backup(raw, 50)

    def test_rejects_random_bytes(self):
        with self.assertRaises(services.BackupError):
            services.parse_backup(b"\x00\x01\xfe\xff random", MAX)

    def test_accepts_valid_backup(self):
        raw = services.create_backup("daily").data
        self.assertEqual(services.parse_backup(raw, MAX)["format_version"], 1)


class RestoreServiceTests(BackupBase):
    def test_preview_counts(self):
        raw = services.create_backup("daily").data
        doc = services.parse_backup(raw, MAX)
        User.objects.create_user("carol", password=PASSWORD)
        User.objects.filter(pk=self.bob.pk).delete()
        row = {r["label"]: r for r in services.preview_restore(doc)}["accounts.User"]
        self.assertEqual(row["label"], "accounts.User")
        self.assertEqual(row["in_file"], 3)
        self.assertEqual(row["in_database_now"], 3)
        self.assertEqual(row["would_be_added"], 1)
        self.assertEqual(row["would_be_removed"], 1)
        self.assertEqual(row["unchanged_or_overwritten"], 2)
        self.assertEqual(row["added_names"], ["bob"])
        self.assertEqual(row["removed_names"], ["carol"])

    def test_round_trip(self):
        # Note: the sequence reset after a restore (connection.ops.sequence_reset_sql) is a no-op
        # on SQLite, so this test cannot verify it. Only PostgreSQL does (README rehearsal step 5).
        self.alice.is_active = False
        self.alice.save()
        original = {u.username: (u.password, u.is_superuser, u.is_active) for u in User.objects.all()}
        doc = services.parse_backup(services.create_backup("manual").data, MAX)

        User.objects.create_user("carol", password=PASSWORD)
        self.bob.set_password("a-different-password-77")
        self.bob.save()
        User.objects.filter(pk=self.alice.pk).delete()

        services.restore_backup(doc, self.admin)

        restored = {u.username: (u.password, u.is_superuser, u.is_active) for u in User.objects.all()}
        self.assertEqual(restored, original)
        self.assertNotIn("carol", self.usernames())
        self.assertEqual(BackupFile.objects.filter(kind="pre_restore").count(), 1)
        self.assertTrue(BackupLog.objects.filter(kind="restore", success=True).exists())
        # The safety backup holds the data as it was just before the restore.
        safety = gunzip_json(BackupFile.objects.get(kind="pre_restore").data)
        safety_names = {r["fields"]["username"] for r in safety["models"]["accounts.User"]}
        self.assertEqual(safety_names, {"boss", "bob", "carol"})

    def membership_roles(self):
        return dict(ProfileMembership.objects.values_list("user__username", "role"))

    def test_round_trip_keeps_roles(self):
        main = main_profile()
        ProfileMembership.objects.create(user=self.admin, profile=main, role="editor")
        ProfileMembership.objects.create(user=self.alice, profile=main, role="editor")
        ProfileMembership.objects.create(user=self.bob, profile=main, role="reader")
        doc = services.parse_backup(services.create_backup("manual").data, MAX)
        users = doc["models"]["accounts.User"]
        self.assertTrue(all("role" not in r["fields"] for r in users))
        expected = {"boss": "editor", "alice": "editor", "bob": "reader"}
        self.assertEqual(self.membership_roles(), expected)
        ProfileMembership.objects.all().update(role="reader")
        services.restore_backup(doc, self.admin)
        self.assertEqual(self.membership_roles(), expected)
        self.assertTrue(User.objects.get(username="boss").is_superuser)

    def old_user_backup(self, roles):
        """A backup as written before roles moved: ``role`` on users, no ``role`` on memberships."""
        doc = services.parse_backup(services.create_backup("manual").data, MAX)
        for record in doc["models"]["accounts.User"]:
            record["fields"]["role"] = roles[record["fields"]["username"]]
        for record in doc["models"].get("accounts.ProfileMembership", []):
            del record["fields"]["role"]
        return services.parse_backup(gzip.compress(json.dumps(doc).encode("utf-8")), MAX)

    def test_restore_old_backup_with_user_role_maps_to_membership_role(self):
        main = main_profile()
        for user in (self.admin, self.alice, self.bob):
            ProfileMembership.objects.create(user=user, profile=main)
        old = self.old_user_backup({"boss": "admin", "alice": "editor", "bob": "reader"})
        ProfileMembership.objects.all().update(role="reader")
        services.restore_backup(old, self.admin)
        self.assertEqual(self.membership_roles(), {"boss": "editor", "alice": "editor", "bob": "reader"})
        self.assertTrue(User.objects.get(username="boss").is_superuser)
        self.assertFalse(User.objects.get(username="alice").is_superuser)

    def test_restore_old_backup_with_admin_role_but_no_superuser_flag(self):
        old = self.old_user_backup({"boss": "admin", "alice": "reader", "bob": "reader"})
        for record in old["models"]["accounts.User"]:
            record["fields"]["is_superuser"] = False
            record["fields"]["role"] = {"boss": "admin"}.get(record["fields"]["username"], "reader")
        old = services.parse_backup(gzip.compress(json.dumps(old).encode("utf-8")), MAX)
        services.restore_backup(old, self.admin)
        self.assertTrue(User.objects.get(username="boss").is_superuser)

    def test_restore_old_backup_without_memberships_defaults_to_reader_and_maps_roles(self):
        doc = services.parse_backup(services.create_backup("manual").data, MAX)
        del doc["models"]["accounts.ProfileMembership"]
        del doc["models"]["accounts.Profile"]
        for record in doc["models"]["accounts.User"]:
            record["fields"]["role"] = "editor" if record["fields"]["username"] == "alice" else "reader"
        old = services.parse_backup(gzip.compress(json.dumps(doc).encode("utf-8")), MAX)
        services.restore_backup(old, self.admin)
        self.assertEqual(self.membership_roles(), {"boss": "editor", "alice": "editor", "bob": "reader"})

    def test_restore_old_backup_without_any_role_defaults_to_reader(self):
        main = main_profile()
        ProfileMembership.objects.create(user=self.alice, profile=main, role="editor")
        doc = services.parse_backup(services.create_backup("manual").data, MAX)
        for record in doc["models"]["accounts.ProfileMembership"]:
            del record["fields"]["role"]
        old = services.parse_backup(gzip.compress(json.dumps(doc).encode("utf-8")), MAX)
        services.restore_backup(old, self.admin)
        self.assertEqual(self.membership_roles(), {"alice": "reader"})

    def test_restore_old_backup_without_display_names_uses_defaults(self):
        SuiteName.objects.create(key="diary", display_name="Renamed")
        doc = services.parse_backup(services.create_backup("manual").data, MAX)
        del doc["models"]["accounts.SuiteName"]
        old = services.parse_backup(gzip.compress(json.dumps(doc).encode("utf-8")), MAX)
        services.restore_backup(old, self.admin)
        self.assertEqual(SuiteName.objects.count(), 0)
        from accounts import suite

        self.assertEqual(suite.get_names(), suite.DEFAULT_NAMES)

    def test_file_missing_other_models_is_still_refused(self):
        doc = services.parse_backup(services.create_backup("manual").data, MAX)
        del doc["models"]["diary.Subject"]
        with self.assertRaises(services.BackupError):
            services.parse_backup(gzip.compress(json.dumps(doc).encode("utf-8")), MAX)

    def test_restore_refused_without_active_admin(self):
        doc = services.parse_backup(services.create_backup("manual").data, MAX)
        for record in doc["models"]["accounts.User"]:
            record["fields"]["is_superuser"] = False
        User.objects.create_user("carol", password=PASSWORD)
        before = self.usernames()
        with self.assertRaises(services.BackupError):
            services.restore_backup(doc, self.admin)
        self.assertEqual(self.usernames(), before)
        self.assertFalse(BackupFile.objects.filter(kind="pre_restore").exists())

    def test_restore_failure_rolls_back(self):
        doc = services.parse_backup(services.create_backup("manual").data, MAX)
        User.objects.create_user("carol", password=PASSWORD)
        before = self.usernames()
        with mock.patch("backups.services.connection.ops.sequence_reset_sql", side_effect=RuntimeError("oops")):
            with self.assertRaises(services.BackupError):
                services.restore_backup(doc, self.admin)
        self.assertEqual(self.usernames(), before)
        self.assertTrue(BackupLog.objects.filter(kind="restore", success=False).exists())


class DiaryRoundTripTests(BackupBase):
    """Every diary model is in the registry and survives backup and restore."""

    def build(self):
        user = self.alice
        subject = Subject.objects.create(profile=main_profile(), name="Contract", created_by=user)
        topic = Topic.objects.create(profile=main_profile(), subject=subject, name="Formation", position=1)
        subtopic = Subtopic.objects.create(profile=main_profile(), topic=topic, name="Offer", position=1)
        other = Subject.objects.create(profile=main_profile(), name="Companies Act", position=2)
        Subtopic.objects.create(profile=main_profile(), subject=other, name="Directors")
        section = Section.objects.create(profile=main_profile(), subtopic=subtopic, name="Ex Parte", needs_review=True, review_note="check")
        item = Item.objects.create(profile=main_profile(), subtopic=subtopic, text="<p>Rule <b>one</b></p>", position=1)
        Case.objects.create(profile=main_profile(), item=item, citation="A v B", position=1)
        nested = Item.objects.create(profile=main_profile(), subject=other, kind="nested", text="Parent", citation="C v D")
        Item.objects.create(profile=main_profile(), parent_item=nested, text="Child")
        multi = Item.objects.create(profile=main_profile(), topic=topic, text="Multi")
        Case.objects.create(profile=main_profile(), item=multi, citation="E v F", comment="<i>c</i>", position=1)
        note = Note.objects.create(profile=main_profile(), item=item, text="See also")
        NoteLink.objects.create(profile=main_profile(), note=note, section=section)
        NoteLink.objects.create(profile=main_profile(), note=note, subject=other)
        junior = Profile.objects.create(program="diary", name="Junior")
        Subject.objects.create(profile=junior, name="Junior notes")
        ProfileMembership.objects.create(user=user, profile=main_profile())
        ProfileMembership.objects.create(user=self.admin, profile=junior)
        SuiteName.objects.create(key="diary", display_name="Case Law Diary (custom)")
        UserSettings.objects.create(user=user, section_format="section_n", opening_subject=subject)
        VersionHistory.objects.create(profile=main_profile(),
            record_type="item", record_id=item.pk, version=1, snapshot={"text": "x"}, change_kind="create",
            group=uuid.uuid4(),
        )
        batch = TrashBatch.objects.create(
            profile=main_profile(), root_type="item", root_id=item.pk, label="Gone", created_by=user
        )
        Item.objects.create(
            profile=main_profile(), subtopic=subtopic, text="Trashed", position=2,
            deleted_at=timezone.now(), delete_batch=batch.id,
        )

    def snapshot(self):
        out = {}
        for model in registry.get_models():
            rows = [
                {f.attname: getattr(obj, f.attname) for f in model._meta.concrete_fields}
                for obj in model._default_manager.order_by("pk")
            ]
            out[model._meta.label] = rows
        return out

    def test_registry_lists_every_diary_model(self):
        from django.apps import apps

        listed = set(registry.BACKUP_MODELS)
        for model in apps.get_app_config("diary").get_models():
            self.assertIn(model._meta.label, listed)

    def test_registry_parents_come_first(self):
        order = [m for m in registry.get_models()]
        for position, model in enumerate(order):
            for field in model._meta.concrete_fields:
                target = field.related_model
                if target is not None and target is not model:
                    self.assertIn(target, order[:position], (model, field.name))

    def test_round_trip_restores_everything(self):
        self.build()
        before = self.snapshot()
        self.assertTrue(all(before[label] for label in registry.BACKUP_MODELS))
        doc = services.parse_backup(services.create_backup("manual").data, MAX)
        self.assertEqual(doc["counts"]["diary.NoteLink"], 2)

        Subject.objects.create(profile=main_profile(), name="Extra")
        Item.objects.filter(text_plain="Parent").update(citation="changed")
        NoteLink.objects.all().delete()
        Subject.objects.filter(name="Contract").delete()
        self.assertNotEqual(self.snapshot(), before)

        services.restore_backup(doc, self.admin)
        self.assertEqual(self.snapshot(), before)

    def test_datetimes_keep_microseconds_in_the_file(self):
        self.build()
        doc = services.parse_backup(services.create_backup("manual").data, MAX)
        stamp = doc["models"]["diary.Subject"][0]["fields"]["created_at"]
        self.assertRegex(stamp, r"\.\d{6}(Z|\+|-|$)")

    def test_older_millisecond_file_still_restores(self):
        self.build()
        doc = services.parse_backup(services.create_backup("manual").data, MAX)
        for record in doc["models"]["diary.Subject"]:
            record["fields"]["created_at"] = "2024-01-02T03:04:05.123Z"
        self.assertEqual(doc["format_version"], 1)
        services.restore_backup(doc, self.admin)
        self.assertTrue(all(sub.created_at.microsecond == 123000 for sub in Subject.objects.all()))
        self.assertTrue(Subject.objects.exists())


class OldFileWithoutTrashBatchesTests(BackupBase):
    """A backup made before Milestone 3 has no Trash batches, no delete_batch and no history group."""

    build = DiaryRoundTripTests.build

    def old_file(self):
        doc = services.parse_backup(services.create_backup("manual").data, MAX)
        del doc["models"]["diary.TrashBatch"]
        del doc["counts"]["diary.TrashBatch"]
        for label, records in doc["models"].items():
            for record in records:
                record["fields"].pop("delete_batch", None)
                record["fields"].pop("group", None)
        return json.dumps(doc).encode("utf-8")

    def test_registry_lists_trash_batches_as_optional(self):
        self.assertIn("diary.TrashBatch", registry.BACKUP_MODELS)
        self.assertIn("diary.TrashBatch", registry.OPTIONAL_MODELS)
        self.assertIn("diary.TrashBatch", registry.PROFILE_MODELS)

    def test_new_file_carries_batches_and_groups(self):
        self.build()
        doc = services.parse_backup(services.create_backup("manual").data, MAX)
        self.assertEqual(doc["counts"]["diary.TrashBatch"], 1)
        trashed = [r for r in doc["models"]["diary.Item"] if r["fields"]["deleted_at"]]
        self.assertEqual(trashed[0]["fields"]["delete_batch"], str(TrashBatch.objects.get().pk))
        self.assertTrue(doc["models"]["diary.VersionHistory"][0]["fields"]["group"])

    def test_old_file_is_accepted_and_restores_with_empty_defaults(self):
        self.build()
        doc = services.parse_backup(self.old_file(), MAX)
        self.assertNotIn("diary.TrashBatch", doc["models"])
        services.restore_backup(doc, self.admin)
        self.assertEqual(TrashBatch.objects.count(), 0)
        self.assertTrue(Item.objects.exists())
        self.assertFalse(Item.objects.filter(delete_batch__isnull=False).exists())
        self.assertTrue(Item.objects.filter(deleted_at__isnull=False).exists())
        self.assertFalse(VersionHistory.objects.filter(group__isnull=False).exists())

    def test_restoring_an_old_file_replaces_existing_trash_batches(self):
        self.build()
        doc = services.parse_backup(self.old_file(), MAX)
        self.assertEqual(TrashBatch.objects.count(), 1)
        services.restore_backup(doc, self.admin)
        self.assertEqual(TrashBatch.objects.count(), 0)

    def test_preview_of_an_old_file_lists_the_batches_as_removed(self):
        self.build()
        doc = services.parse_backup(self.old_file(), MAX)
        row = {r["label"]: r for r in services.preview_restore(doc)}["diary.TrashBatch"]
        self.assertEqual((row["in_file"], row["in_database_now"], row["would_be_removed"]), (0, 1, 1))


class OldFileWithoutProfilesTests(BackupBase):
    """A backup made before profiles existed restores into a default "Main" profile."""

    build = DiaryRoundTripTests.build

    def old_file(self):
        doc = services.parse_backup(services.create_backup("manual").data, MAX)
        del doc["models"]["accounts.Profile"]
        del doc["models"]["accounts.ProfileMembership"]
        doc["models"]["diary.Subject"] = [
            record for record in doc["models"]["diary.Subject"] if record["fields"]["name"] != "Junior notes"
        ]
        for label in registry.PROFILE_MODELS:
            for record in doc["models"][label]:
                del record["fields"]["profile"]
        return json.dumps(doc).encode("utf-8")

    def test_old_file_gets_main_profile(self):
        self.build()
        doc = services.parse_backup(self.old_file(), MAX)
        self.assertEqual([r["fields"]["name"] for r in doc["models"]["accounts.Profile"]], ["Main"])
        users = len(doc["models"]["accounts.User"])
        self.assertEqual(len(doc["models"]["accounts.ProfileMembership"]), users)
        summary = services.profile_summary(doc)
        self.assertEqual([(row["name"], row["users"]) for row in summary], [("Main", users)])
        self.assertGreater(summary[0]["records"], 0)

    def test_old_file_restores_everything_into_main(self):
        self.build()
        doc = services.parse_backup(self.old_file(), MAX)
        services.restore_backup(doc, self.admin)
        self.assertEqual(list(Profile.objects.values_list("name", flat=True)), ["Main"])
        main = Profile.objects.get(name="Main")
        self.assertTrue(Subject.objects.exists())
        self.assertFalse(Subject.objects.exclude(profile=main).exists())
        self.assertFalse(Item.objects.exclude(profile=main).exists())
        self.assertFalse(VersionHistory.objects.exclude(profile=main).exists())
        self.assertEqual(ProfileMembership.objects.filter(profile=main).count(), User.objects.count())

    def test_file_with_profiles_is_not_changed(self):
        self.build()
        doc = services.parse_backup(services.create_backup("manual").data, MAX)
        self.assertFalse(services.upgrade_old_document(doc))
        self.assertEqual(
            sorted(r["fields"]["name"] for r in doc["models"]["accounts.Profile"]), ["Junior", "Main"]
        )


class ReadingAllDefaultBackupTests(BackupBase):
    def test_setting_round_trips(self):
        Profile.objects.filter(pk=main_profile().pk).update(reading_all_default=False)
        doc = services.parse_backup(services.create_backup("manual").data, MAX)
        self.assertIs(doc["models"]["accounts.Profile"][0]["fields"]["reading_all_default"], False)
        Profile.objects.filter(pk=main_profile().pk).update(reading_all_default=True)
        services.restore_backup(doc, self.admin)
        self.assertFalse(Profile.objects.get(name="Main").reading_all_default)

    def test_backup_made_before_the_setting_restores_as_on(self):
        Profile.objects.filter(pk=main_profile().pk).update(reading_all_default=False)
        doc = services.parse_backup(services.create_backup("manual").data, MAX)
        for record in doc["models"]["accounts.Profile"]:
            del record["fields"]["reading_all_default"]
        services.restore_backup(doc, self.admin)
        self.assertTrue(Profile.objects.get(name="Main").reading_all_default)
        self.assertEqual(Profile.objects.get(name="Main").reading_all_mode, "remember")

    def test_display_name_round_trips_and_an_old_backup_restores_it_blank(self):
        Profile.objects.filter(pk=main_profile().pk).update(display_name="Madon's Case Law")
        doc = services.parse_backup(services.create_backup("manual").data, MAX)
        self.assertEqual(doc["models"]["accounts.Profile"][0]["fields"]["display_name"], "Madon's Case Law")
        Profile.objects.filter(pk=main_profile().pk).update(display_name="changed")
        services.restore_backup(doc, self.admin)
        self.assertEqual(Profile.objects.get(name="Main").display_name, "Madon's Case Law")
        for record in doc["models"]["accounts.Profile"]:
            del record["fields"]["display_name"]
        services.restore_backup(doc, self.admin)
        self.assertEqual(Profile.objects.get(name="Main").display_name, "")

    def test_mode_round_trips(self):
        Profile.objects.filter(pk=main_profile().pk).update(reading_all_mode="always_off")
        doc = services.parse_backup(services.create_backup("manual").data, MAX)
        self.assertEqual(doc["models"]["accounts.Profile"][0]["fields"]["reading_all_mode"], "always_off")
        Profile.objects.filter(pk=main_profile().pk).update(reading_all_mode="always_on")
        services.restore_backup(doc, self.admin)
        self.assertEqual(Profile.objects.get(name="Main").reading_all_mode, "always_off")

    def test_backup_without_mode_restores_as_remember_with_its_boolean(self):
        Profile.objects.filter(pk=main_profile().pk).update(reading_all_mode="always_on", reading_all_default=False)
        doc = services.parse_backup(services.create_backup("manual").data, MAX)
        for record in doc["models"]["accounts.Profile"]:
            del record["fields"]["reading_all_mode"]
        services.restore_backup(doc, self.admin)
        profile = Profile.objects.get(name="Main")
        self.assertEqual(profile.reading_all_mode, "remember")
        self.assertFalse(profile.reading_all_default)


class LandingProgramBackupTests(BackupBase):
    def test_setting_round_trips(self):
        User.objects.filter(pk=self.alice.pk).update(landing_program="diary")
        doc = services.parse_backup(services.create_backup("manual").data, MAX)
        rows = {r["fields"]["username"]: r["fields"] for r in doc["models"]["accounts.User"]}
        self.assertEqual(rows["alice"]["landing_program"], "diary")
        User.objects.filter(pk=self.alice.pk).update(landing_program="")
        services.restore_backup(doc, self.admin)
        self.assertEqual(User.objects.get(username="alice").landing_program, "diary")

    def test_backup_made_before_the_setting_restores_as_home(self):
        User.objects.filter(pk=self.alice.pk).update(landing_program="diary")
        doc = services.parse_backup(services.create_backup("manual").data, MAX)
        for record in doc["models"]["accounts.User"]:
            del record["fields"]["landing_program"]
        services.restore_backup(doc, self.admin)
        self.assertEqual(User.objects.get(username="alice").landing_program, "")


class ViewTests(BackupBase):
    def test_non_admin_gets_403_everywhere(self):
        backup = services.create_backup("daily")
        self.client.login(username="alice", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("backup_list")).status_code, 403)
        self.assertEqual(self.client.post(reverse("backup_now")).status_code, 403)
        self.assertEqual(self.client.get(reverse("restore_upload")).status_code, 403)
        self.assertEqual(self.client.post(reverse("restore_upload")).status_code, 403)
        self.assertEqual(self.client.get(reverse("backup_download", args=[backup.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("restore_preview", args=[backup.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("restore_preview", args=[backup.pk]), {"confirm": "RESTORE"}).status_code, 403)
        self.assertEqual(BackupFile.objects.count(), 1)

    def test_anonymous_redirected_to_login(self):
        resp = self.client.get(reverse("backup_list"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp["Location"])

    def test_backup_tables_are_resizable(self):
        self.login_admin()
        self.client.post(reverse("backup_now"))
        page = self.client.get(reverse("backup_list"))
        self.assertContains(page, 'data-resizable-columns="backups-list"')
        self.assertContains(page, 'data-resizable-columns="backups-log"')
        self.assertContains(page, "js/resizable-columns.js")

    def test_list_and_backup_now(self):
        self.login_admin()
        resp = self.client.post(reverse("backup_now"))
        self.assertRedirects(resp, reverse("backup_list"))
        self.assertEqual(BackupFile.objects.filter(kind="manual", created_by=self.admin).count(), 1)
        page = self.client.get(reverse("backup_list"))
        self.assertContains(page, "Download")
        self.assertContains(page, "accounts.User: 3")

    def test_import_backups_are_labelled_and_can_be_deleted_by_an_admin(self):
        self.login_admin()
        before = services.create_backup("pre_import", self.admin)
        manual = services.create_backup("manual", self.admin)
        page = self.client.get(reverse("backup_list"))
        self.assertContains(page, "Before import")
        self.assertContains(page, reverse("backup_delete", args=[before.pk]))
        self.assertNotContains(page, reverse("backup_delete", args=[manual.pk]))
        self.assertContains(self.client.get(reverse("backup_delete", args=[before.pk])), before.filename)
        self.assertTrue(BackupFile.objects.filter(pk=before.pk).exists())  # asking does not delete
        self.client.post(reverse("backup_delete", args=[before.pk]))
        self.assertFalse(BackupFile.objects.filter(pk=before.pk).exists())
        # other kinds cannot be deleted this way
        self.assertEqual(self.client.post(reverse("backup_delete", args=[manual.pk])).status_code, 404)
        self.assertTrue(BackupFile.objects.filter(pk=manual.pk).exists())

    def test_delete_backup_is_admin_only(self):
        before = services.create_backup("pre_import", self.admin)
        self.client.login(username="alice", password=PASSWORD)
        self.assertEqual(self.client.post(reverse("backup_delete", args=[before.pk])).status_code, 403)
        self.assertTrue(BackupFile.objects.filter(pk=before.pk).exists())

    def test_backup_now_requires_post(self):
        self.login_admin()
        self.assertEqual(self.client.get(reverse("backup_now")).status_code, 405)

    def test_download_returns_exact_bytes(self):
        backup = services.create_backup("daily")
        self.login_admin()
        resp = self.client.get(reverse("backup_download", args=[backup.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/octet-stream")
        self.assertNotIn("Content-Encoding", resp)
        self.assertIn(".json.gz", resp["Content-Disposition"])
        self.assertIn("attachment", resp["Content-Disposition"])
        self.assertEqual(b"".join(resp.streaming_content), bytes(backup.data))

    def test_preview_page_shows_counts(self):
        backup = services.create_backup("daily")
        User.objects.create_user("carol", password=PASSWORD)
        self.login_admin()
        resp = self.client.get(reverse("restore_preview", args=[backup.pk]))
        self.assertContains(resp, "safety backup")
        self.assertContains(resp, "carol")

    def test_restore_requires_confirmation_word(self):
        backup = services.create_backup("daily")
        User.objects.create_user("carol", password=PASSWORD)
        before = self.usernames()
        self.login_admin()
        for body in ({}, {"confirm": "restore"}, {"confirm": "yes"}):
            resp = self.client.post(reverse("restore_preview", args=[backup.pk]), body)
            self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.usernames(), before)
        self.assertFalse(BackupFile.objects.filter(kind="pre_restore").exists())

    def test_restore_with_confirmation_word(self):
        backup = services.create_backup("daily")
        User.objects.create_user("carol", password=PASSWORD)
        self.login_admin()
        resp = self.client.post(reverse("restore_preview", args=[backup.pk]), {"confirm": "RESTORE"})
        self.assertRedirects(resp, reverse("backup_list"))
        self.assertEqual(self.usernames(), {"boss", "alice", "bob"})
        self.assertTrue(BackupFile.objects.filter(kind="pre_restore").exists())
        # The success log is written after the commit, with request.user (a lazy object).
        log = BackupLog.objects.get(kind="restore", success=True)
        self.assertEqual(log.created_by.username, "boss")

    def test_upload_valid_file_goes_to_preview(self):
        raw = bytes(services.create_backup("daily").data)
        self.login_admin()
        upload = SimpleUploadedFile("my backup.json.gz", raw, content_type="application/gzip")
        resp = self.client.post(reverse("restore_upload"), {"backup_file": upload})
        uploaded = BackupFile.objects.get(kind="uploaded")
        self.assertRedirects(resp, reverse("restore_preview", args=[uploaded.pk]))
        self.assertEqual(bytes(uploaded.data), raw)
        self.assertNotIn(" ", uploaded.filename)

    def test_upload_plain_json_goes_to_preview_and_restores(self):
        raw = gzip.decompress(bytes(services.create_backup("daily").data))
        User.objects.create_user("carol", password=PASSWORD)
        self.login_admin()
        upload = SimpleUploadedFile("judgment-diary-backup-x-manual.json", raw, content_type="application/json")
        resp = self.client.post(reverse("restore_upload"), {"backup_file": upload})
        uploaded = BackupFile.objects.get(kind="uploaded")
        self.assertRedirects(resp, reverse("restore_preview", args=[uploaded.pk]))
        self.assertEqual(bytes(uploaded.data), raw)
        self.assertEqual(uploaded.sha256, hashlib.sha256(raw).hexdigest())
        self.client.post(reverse("restore_preview", args=[uploaded.pk]), {"confirm": "RESTORE"})
        self.assertNotIn("carol", self.usernames())

    def test_upload_corrupted_file_rejected_without_changes(self):
        User.objects.create_user("carol", password=PASSWORD)
        before = self.usernames()
        self.login_admin()
        upload = SimpleUploadedFile("bad.json.gz", b"this is not a backup", content_type="application/gzip")
        resp = self.client.post(reverse("restore_upload"), {"backup_file": upload}, follow=True)
        self.assertContains(resp, "not a backup file")
        self.assertFalse(BackupFile.objects.filter(kind="uploaded").exists())
        self.assertEqual(self.usernames(), before)

    @override_settings(MAX_BACKUP_UPLOAD_MB=1)
    def test_upload_over_limit_rejected(self):
        self.login_admin()
        upload = SimpleUploadedFile("big.json.gz", b"x" * (1024 * 1024 + 1))
        self.client.post(reverse("restore_upload"), {"backup_file": upload})
        self.assertFalse(BackupFile.objects.filter(kind="uploaded").exists())


class CitationConstraintRestoreTests(BackupBase):
    """Migration 0011 forbids a citation on a non-nested Item. A backup file must still restore: whatever the
    file holds is mapped BEFORE insertion, and the constraint is in force here (nothing lifts it)."""

    def make_file(self):
        profile = main_profile()
        subject = Subject.objects.create(profile=profile, name="Contract")
        sub = Subtopic.objects.create(profile=profile, subject=subject, name="Offer")
        self.item = Item.objects.create(profile=profile, subtopic=sub, text="p", position=1)
        self.nested = Item.objects.create(profile=profile, subtopic=sub, text="n", kind="nested", citation="N v M", position=2)
        return gunzip_json(services.create_backup("manual").data)

    def test_a_file_with_a_stray_citation_is_mapped_then_restored(self):
        old = self.make_file()
        for record in old["models"]["diary.Item"]:
            if record["pk"] == self.item.pk:
                record["fields"]["citation"] = "Stray v File"
        doc = services.parse_backup(json.dumps(old).encode("utf-8"), MAX)
        self.assertEqual(doc["legacy_mapping"]["cases_created"], 1)
        services.restore_backup(doc, self.admin)
        self.assertEqual(self.item.cases.get().citation, "Stray v File")
        self.assertFalse(Item.objects.exclude(kind="nested").exclude(citation="").exists())
        self.assertEqual(Item.objects.get(pk=self.nested.pk).citation, "N v M")

    def test_a_file_in_the_current_shape_restores_unchanged(self):
        old = self.make_file()
        doc = services.parse_backup(json.dumps(old).encode("utf-8"), MAX)
        self.assertEqual(doc["legacy_mapping"]["items_changed"], 0)
        services.restore_backup(doc, self.admin)
        self.assertEqual(Item.objects.get(pk=self.nested.pk).citation, "N v M")


class BannerTests(BackupBase):
    def test_banner_after_failure(self):
        with mock.patch("backups.services.serializers.serialize", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                services.create_backup("daily")
        self.login_admin()
        self.assertContains(self.client.get(reverse("home")), "The last backup FAILED")

    def test_banner_when_stale(self):
        backup = services.create_backup("daily")
        BackupLog.objects.filter(backup=backup).update(started_at=timezone.now() - timedelta(hours=50))
        self.login_admin()
        self.assertContains(self.client.get(reverse("home")), "No successful backup in the last 36 hours.")

    def test_banner_when_no_backup_ever(self):
        self.login_admin()
        self.assertContains(self.client.get(reverse("home")), "No successful backup")

    def test_no_banner_after_fresh_success(self):
        services.create_backup("daily")
        self.login_admin()
        resp = self.client.get(reverse("home"))
        self.assertNotContains(resp, "FAILED")
        self.assertNotContains(resp, "No successful backup")

    def test_no_banner_for_non_admin(self):
        self.client.login(username="alice", password=PASSWORD)
        resp = self.client.get(reverse("home"))
        self.assertNotContains(resp, "No successful backup")


class MigrateWithBackupTests(BackupBase):
    CMD = "backups.management.commands.migrate_with_backup"

    def test_backup_taken_when_migrations_pending(self):
        with mock.patch(f"{self.CMD}.has_pending_migrations", return_value=True), mock.patch(
            f"{self.CMD}.call_command"
        ) as migrate:
            call_command("migrate_with_backup", stdout=StringIO())
        self.assertEqual(BackupFile.objects.filter(kind="pre_migration").count(), 1)
        migrate.assert_called_once_with("migrate", interactive=False)

    def test_no_backup_when_nothing_pending(self):
        with mock.patch(f"{self.CMD}.has_pending_migrations", return_value=False), mock.patch(
            f"{self.CMD}.call_command"
        ) as migrate:
            call_command("migrate_with_backup", stdout=StringIO())
        self.assertFalse(BackupFile.objects.exists())
        migrate.assert_called_once()

    def test_no_backup_when_no_users(self):
        User.objects.all().delete()
        with mock.patch(f"{self.CMD}.has_pending_migrations", return_value=True), mock.patch(
            f"{self.CMD}.call_command"
        ):
            call_command("migrate_with_backup", stdout=StringIO())
        self.assertFalse(BackupFile.objects.exists())

    def test_failed_backup_aborts_migrate(self):
        with mock.patch(f"{self.CMD}.has_pending_migrations", return_value=True), mock.patch(
            f"{self.CMD}.call_command"
        ) as migrate, mock.patch("backups.services.serializers.serialize", side_effect=RuntimeError("boom")):
            with self.assertRaises(CommandError):
                call_command("migrate_with_backup", stdout=StringIO())
        migrate.assert_not_called()

    def test_pre_migration_backup_uses_applied_state_models(self):
        with mock.patch(f"{self.CMD}.has_pending_migrations", return_value=True), mock.patch(
            f"{self.CMD}.call_command"
        ), mock.patch(f"{self.CMD}.services.create_backup", wraps=services.create_backup) as create:
            call_command("migrate_with_backup", stdout=StringIO())
        create.assert_called_once_with("pre_migration", use_applied_state=True)

    def test_applied_state_backup_tolerates_model_not_yet_migrated(self):
        # Simulates a pending migration that adds a backed-up model: the registry (new code)
        # lists a model the applied state does not have, and the backup must still succeed.
        # NOT a real schema change: only a real PostgreSQL deploy proves the end-to-end case.
        class FakeApps:
            def get_model(self, label):
                if label == "accounts.User":
                    return User
                raise LookupError(label)

        labels = ["accounts.User", "diary.Subject"]
        with mock.patch("backups.registry.BACKUP_MODELS", labels), mock.patch(
            "backups.services.applied_state_apps", return_value=FakeApps()
        ):
            backup = services.create_backup("pre_migration", use_applied_state=True)
        document = gunzip_json(backup.data)
        self.assertEqual(document["counts"], {"accounts.User": 3, "diary.Subject": 0})
        self.assertEqual(document["models"]["diary.Subject"], [])

    def test_applied_state_apps_has_user_model(self):
        historical = services.applied_state_apps().get_model("accounts.User")
        self.assertEqual(historical._default_manager.count(), 3)

    def test_real_pending_check_runs(self):
        # Test database is fully migrated, so nothing is pending.
        self.assertFalse(migrate_with_backup.has_pending_migrations())


@override_settings(SECURE_SSL_REDIRECT=False)
class FriendlyErrorTests(TestCase):
    def test_csrf_failure_is_friendly(self):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        resp = client.post(reverse("backup_now"))
        self.assertContains(resp, "security check", status_code=403)

    def test_banner_failure_does_not_break_pages(self):
        admin = User.objects.create_user("boss", password=PASSWORD, is_superuser=True, is_staff=True)
        self.client.force_login(admin)
        with mock.patch("backups.context_processors._backup_banner", side_effect=RuntimeError("x")):
            resp = self.client.get(reverse("backup_list"))
        self.assertEqual(resp.status_code, 200)


class OldFormatItemsTests(BackupBase):
    """10d: a backup made before Multi-Item was merged into Item is mapped exactly as migration 0010 maps the
    live database (diary/legacy_merge.py)."""

    def setUp(self):
        allow_old_shape_items(self)
        super().setUp()

    def build_old(self):
        """Old-format rows written straight to the tables: citations on Items, kind 'multi'."""
        profile = main_profile()
        subject = Subject.objects.create(profile=profile, name="Contract")
        sub = Subtopic.objects.create(profile=profile, subject=subject, name="Offer")
        make = lambda **kw: Item.objects.create(profile=profile, subtopic=sub, **kw)  # noqa: E731
        self.plain = make(text="p", citation="A v B", position=1)
        self.bare = make(text="b", position=2)
        self.multi = make(text="m", position=3)
        Item.objects.filter(pk=self.multi.pk).update(kind="multi")
        Case.objects.create(profile=profile, item=self.multi, citation="C1", comment="<i>c</i>", position=1)
        Case.objects.create(profile=profile, item=self.multi, citation="C2", position=2)
        self.nested = make(text="n", kind="nested", citation="N v M", position=4)
        make(text="t", citation="T v U", position=5, deleted_at=timezone.now())
        make(text="s", citation="  ", position=6)
        return gunzip_json(services.create_backup("manual").data)

    def shape(self):
        items = list(Item.objects.order_by("pk").values_list("pk", "kind", "citation", "version", "deleted_at"))
        cases = sorted(
            Case.objects.values_list("item_id", "position", "citation", "comment", "version", "deleted_at", "delete_batch")
        )
        history = sorted(
            VersionHistory.objects.filter(change_kind="migrate").values_list("record_type", "version", "change_kind")
        )
        return items, cases, history

    def test_restoring_an_old_file_maps_like_the_migration(self):
        from django.apps import apps

        from diary import legacy_merge as legacy

        old = self.build_old()
        legacy.migrate_items(apps)
        migrated = self.shape()

        doc = services.parse_backup(json.dumps(old).encode("utf-8"), MAX)
        self.assertEqual(doc["legacy_mapping"]["cases_created"], 3)
        services.restore_backup(doc, self.admin)
        self.assertEqual(self.shape(), migrated)

    def test_mapped_result(self):
        old = self.build_old()
        doc = services.parse_backup(json.dumps(old).encode("utf-8"), MAX)
        stats = doc["legacy_mapping"]
        self.assertEqual(
            (stats["items_changed"], stats["cases_created"], stats["multi_to_plain"], stats["whitespace_only"],
             stats["nested_with_citation_kept"]),
            (4, 3, 1, 1, 1),
        )
        self.assertEqual(doc["counts"]["diary.Case"], 5)
        services.restore_backup(doc, self.admin)
        self.assertFalse(Item.objects.exclude(kind="nested").exclude(citation="").exists())
        self.assertFalse(Item.objects.filter(kind="multi").exists())
        self.assertEqual(Item.objects.get(pk=self.nested.pk).citation, "N v M")
        self.assertEqual(self.plain.cases.get().citation, "A v B")
        self.assertEqual(Case.objects.get(citation="  ").item.text_plain, "s")
        trashed = Case.objects.get(citation="T v U")
        self.assertIsNotNone(trashed.deleted_at)
        self.assertEqual(VersionHistory.objects.filter(change_kind="migrate", record_type="case").count(), 3)
        # Primary keys of new rows do not collide, and the sequences continue after them.
        extra = Case.objects.create(profile=main_profile(), item=self.plain, citation="Later", position=5)
        self.assertGreater(extra.pk, max(Case.objects.exclude(pk=extra.pk).values_list("pk", flat=True)))

    def test_preview_says_the_file_is_old_and_counts_include_the_mapping(self):
        old = self.build_old()
        doc = services.parse_backup(json.dumps(old).encode("utf-8"), MAX)
        rows = {r["label"]: r for r in services.preview_restore(doc)}
        self.assertEqual(rows["diary.Case"]["in_file"], 5)
        self.assertIn("3 citation(s) moved into Case (a)", services.legacy.describe(doc["legacy_mapping"]))

    def test_restore_log_mentions_the_mapping(self):
        old = self.build_old()
        doc = services.parse_backup(json.dumps(old).encode("utf-8"), MAX)
        services.restore_backup(doc, self.admin)
        self.assertIn("moved into Case (a)", BackupLog.objects.filter(kind="restore").latest("pk").message)

    def test_a_new_format_file_is_not_changed(self):
        self.build_old()
        from django.apps import apps

        from diary import legacy_merge as legacy

        legacy.migrate_items(apps)
        doc = services.parse_backup(services.create_backup("manual").data, MAX)
        self.assertEqual(doc["legacy_mapping"]["items_changed"], 0)
        self.assertEqual(doc["counts"]["diary.Case"], 5)

    def test_trashed_cases_are_reported_and_not_touched(self):
        profile = main_profile()
        subject = Subject.objects.create(profile=profile, name="Contract")
        sub = Subtopic.objects.create(profile=profile, subject=subject, name="Offer")
        item = Item.objects.create(profile=profile, subtopic=sub, text="j", citation="A v B; C v D", position=1)
        gone = Case.objects.create(profile=profile, item=item, citation="A v B", position=1, deleted_at=timezone.now())
        old = gunzip_json(services.create_backup("manual").data)
        doc = services.parse_backup(json.dumps(old).encode("utf-8"), MAX)
        self.assertEqual(doc["legacy_mapping"]["trashed_cases_beside"], 1)
        self.assertIn("Cases in Trash", services.legacy.describe(doc["legacy_mapping"]))
        services.restore_backup(doc, self.admin)
        live = list(Case.objects.filter(item=item, deleted_at__isnull=True).values_list("citation", "position"))
        self.assertEqual(live, [("A v B; C v D", 1)])
        gone.refresh_from_db()
        self.assertEqual((gone.position, gone.deleted_at is None), (1, False))

    def test_unmappable_data_is_refused_with_a_message(self):
        old = self.build_old()
        for record in old["models"]["diary.Case"]:
            if record["fields"]["citation"] == "C1":
                record["fields"]["item"] = self.plain.pk
                record["fields"]["position"] = 0
        with self.assertRaises(services.BackupError):
            services.parse_backup(json.dumps(old).encode("utf-8"), MAX)
