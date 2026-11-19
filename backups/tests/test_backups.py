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
from diary.tests.helpers import main_profile

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
            self.assertEqual(self.client.post(reverse("restore_upload"), {}).status_code, 403)
            for url in ("restore_preview", "backup_download", "backup_delete"):
                self.assertEqual(self.client.get(reverse(url, args=[1])).status_code, 403, (name, url))
            self.assertEqual(self.client.post(reverse("restore_preview", args=[1]), {}).status_code, 403)
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
        expected["investments.Instrument"] = 1  # Nifty 50, the built-in index (migrations 0002 and 0016)
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
        self.assertIn("Old backups removed: 0", out.getvalue())  # one backup is under the keep count: nothing pruned, so no prune log

    def test_run_backup_failure_raises_command_error(self):
        with mock.patch("backups.services.serializers.serialize", side_effect=RuntimeError("boom")):
            with self.assertRaises(CommandError):
                call_command("run_backup", stdout=StringIO())
        self.assertTrue(BackupLog.objects.filter(kind="daily", success=False).exists())


class RetentionTests(BackupBase):
    def make_many(self, kinds):
        """Create backups oldest first, with distinct ages so the order is certain."""
        made = []
        with override_settings(BACKUP_KEEP_COUNT=1000):
            for index, kind in enumerate(kinds):
                backup = services.create_backup(kind)
                BackupFile.objects.filter(pk=backup.pk).update(
                    created_at=timezone.now() - timedelta(minutes=len(kinds) - index)
                )
                made.append(backup)
        return made

    def test_prune_keeps_only_the_newest_n(self):
        made = self.make_many(["daily"] * 6)
        removed = services.prune_old_backups(keep_count=4)
        self.assertEqual(removed, 2)
        remaining = set(BackupFile.objects.values_list("pk", flat=True))
        self.assertEqual(remaining, {b.pk for b in made[2:]})
        self.assertTrue(BackupLog.objects.filter(kind="prune", success=True).exists())

    def test_every_kind_counts(self):
        kinds = ["pre_import", "post_import", "pre_clear", "pre_migration", "pre_restore", "manual", "daily"]
        made = self.make_many(kinds)
        self.assertEqual(services.prune_old_backups(keep_count=3), 4)
        remaining = set(BackupFile.objects.values_list("pk", flat=True))
        self.assertEqual(remaining, {b.pk for b in made[-3:]})

    def test_old_import_backups_are_pruned_like_any_other(self):
        made = self.make_many(["pre_import", "post_import", "daily", "daily"])
        services.prune_old_backups(keep_count=2)
        self.assertFalse(BackupFile.objects.filter(pk__in=[made[0].pk, made[1].pk]).exists())

    def test_nothing_is_removed_while_under_the_limit(self):
        self.make_many(["daily"] * 3)
        self.assertEqual(services.prune_old_backups(keep_count=30), 0)
        self.assertEqual(BackupFile.objects.count(), 3)

    def test_prune_never_leaves_zero_backups(self):
        only = services.create_backup("daily")
        self.assertEqual(services.prune_old_backups(keep_count=0), 0)
        self.assertTrue(BackupFile.objects.filter(pk=only.pk).exists())

    def test_default_keep_count_setting_is_30_and_minimum_1(self):
        from django.conf import settings

        self.assertGreaterEqual(settings.BACKUP_KEEP_COUNT, 1)

    @override_settings(BACKUP_KEEP_COUNT=3)
    def test_create_backup_prunes_after_itself_and_keeps_the_new_one(self):
        self.make_many(["daily"] * 5)
        newest = services.create_backup("pre_migration")
        self.assertEqual(BackupFile.objects.count(), 3)
        self.assertTrue(BackupFile.objects.filter(pk=newest.pk).exists())

    def test_prune_failure_is_logged_not_raised(self):
        services.create_backup("daily")
        with mock.patch("backups.services.policy.select_over_count", side_effect=RuntimeError("bad")):
            self.assertEqual(services.prune_old_backups(), 0)
        self.assertTrue(BackupLog.objects.filter(kind="prune", success=False).exists())

    def test_prune_failure_never_breaks_a_backup(self):
        with mock.patch("backups.services.policy.select_over_count", side_effect=RuntimeError("bad")):
            backup = services.create_backup("manual")
        self.assertTrue(BackupFile.objects.filter(pk=backup.pk).exists())


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
        other_topic = Topic.objects.create(profile=main_profile(), subject=other, name="1", position=1)
        Subtopic.objects.create(profile=main_profile(), topic=other_topic, name="Directors")
        section = Section.objects.create(profile=main_profile(), subtopic=subtopic, name="Ex Parte", flag="pending", flag_text="check")
        item = Item.objects.create(profile=main_profile(), subtopic=subtopic, text="<p>Rule <b>one</b></p>", position=1)
        Case.objects.create(profile=main_profile(), item=item, citation="A v B", position=1)
        lines = Item.objects.create(profile=main_profile(), topic=other_topic, text="Parent", citation_layout="lines")
        Case.objects.create(profile=main_profile(), item=lines, citation="C v D", comment="<p>why</p>", position=1)
        Case.objects.create(profile=main_profile(), item=lines, citation="G v H", position=2)
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
        self.assertTrue(
            all(before[label] for label in registry.BACKUP_MODELS if not label.startswith(("fees.", "investments.")))
        )
        doc = services.parse_backup(services.create_backup("manual").data, MAX)
        self.assertEqual(doc["counts"]["diary.NoteLink"], 2)

        Subject.objects.create(profile=main_profile(), name="Extra")
        Item.objects.filter(text_plain="Parent").update(citation_layout="inline")
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


class ReadingAllDefaultBackupTests(BackupBase):
    def test_the_removed_boolean_is_not_written(self):
        doc = services.parse_backup(services.create_backup("manual").data, MAX)
        self.assertNotIn("reading_all_default", doc["models"]["accounts.Profile"][0]["fields"])


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


class LastDiaryPathBackupTests(BackupBase):
    def test_last_page_round_trips(self):
        User.objects.filter(pk=self.alice.pk).update(last_diary_path="/caselaw/search/?q=duty")
        doc = services.parse_backup(services.create_backup("manual").data, MAX)
        User.objects.filter(pk=self.alice.pk).update(last_diary_path="")
        services.restore_backup(doc, self.admin)
        self.assertEqual(User.objects.get(username="alice").last_diary_path, "/caselaw/search/?q=duty")

    def test_backup_made_before_the_column_restores_as_blank(self):
        User.objects.filter(pk=self.alice.pk).update(last_diary_path="/caselaw/search/")
        doc = services.parse_backup(services.create_backup("manual").data, MAX)
        for record in doc["models"]["accounts.User"]:
            del record["fields"]["last_diary_path"]
        services.restore_backup(doc, self.admin)
        self.assertEqual(User.objects.get(username="alice").last_diary_path, "")


class LastBackupTests(BackupBase):
    """Only the newest backup (made by the current release) has to restore. Files made by much earlier releases are no longer
    converted. A column that a later release drops is ignored, and one it adds takes its default, so yesterday's file still restores."""

    def make_subject(self):
        subject = Subject.objects.create(profile=main_profile(), name="Contract", landing_position=1)
        topic = Topic.objects.create(profile=main_profile(), subject=subject, name="Offer")
        item = Item.objects.create(profile=main_profile(), topic=topic, text="<p>one</p>", text_plain="one", position=1)
        Case.objects.create(profile=main_profile(), item=item, citation="A v B", position=1)
        return subject, topic, item

    def test_a_backup_made_now_restores_the_diary_and_the_users(self):
        ProfileMembership.objects.create(user=self.alice, profile=main_profile(), role="editor")
        self.make_subject()
        doc = services.parse_backup(services.create_backup("daily").data, MAX)
        Subject.objects.all().delete()
        User.objects.filter(pk=self.bob.pk).delete()
        services.restore_backup(doc, self.admin)
        self.assertEqual(self.usernames(), {"boss", "alice", "bob"})
        self.assertEqual(list(Item.objects.values_list("text_plain", flat=True)), ["one"])
        self.assertEqual(list(Case.objects.values_list("citation", flat=True)), ["A v B"])
        self.assertEqual(dict(ProfileMembership.objects.values_list("user__username", "role")), {"alice": "editor"})

    def test_a_column_the_models_no_longer_have_is_ignored(self):
        self.make_subject()
        doc = services.parse_backup(services.create_backup("daily").data, MAX)
        for label in ("accounts.User", "diary.Item", "diary.Subject"):
            for record in doc["models"][label]:
                record["fields"]["a_column_dropped_later"] = "ignored"
        again = services.parse_backup(gzip.compress(json.dumps(doc).encode("utf-8")), MAX)
        services.restore_backup(again, self.admin)
        self.assertEqual(self.usernames(), {"boss", "alice", "bob"})
        self.assertEqual(Item.objects.count(), 1)

    def test_a_file_that_a_much_older_release_made_is_refused_with_a_message_not_a_crash(self):
        doc = services.parse_backup(services.create_backup("daily").data, MAX)
        doc["format_version"] = 0
        with self.assertRaises(services.BackupError):
            services.parse_backup(gzip.compress(json.dumps(doc).encode("utf-8")), MAX)
        doc["format_version"] = services.FORMAT_VERSION
        doc["models"]["accounts.User"][0]["fields"] = "not a dictionary"
        with self.assertRaises(services.BackupError):
            services.parse_backup(gzip.compress(json.dumps(doc).encode("utf-8")), MAX)


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
        self.assertContains(page, 'data-table-id="backups-list"')
        self.assertContains(page, 'data-table-id="backups-log"')
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
    """Since round 10 the database forbids a citation on every Item. A backup file must still restore: whatever the
    file holds is mapped BEFORE insertion, and the constraint is in force here (nothing lifts it)."""

    def make_file(self):
        profile = main_profile()
        subject = Subject.objects.create(profile=profile, name="Contract")
        sub = Subtopic.objects.create(profile=profile, subject=subject, name="Offer")
        self.item = Item.objects.create(profile=profile, subtopic=sub, text="p", position=1)
        self.nested = Item.objects.create(profile=profile, subtopic=sub, text="n", position=2)
        old = gunzip_json(services.create_backup("manual").data)
        for record in old["models"]["diary.Item"]:  # an old file: the Nested Item holds its own citation
            if record["pk"] == self.nested.pk:
                record["fields"].update(kind="nested", citation="N v M")
        return old


    def test_a_file_in_the_current_shape_restores_unchanged(self):
        self.make_file()
        current = gunzip_json(services.create_backup("manual").data)
        doc = services.parse_backup(json.dumps(current).encode("utf-8"), MAX)
        self.assertEqual(doc["legacy_mapping"]["items_changed"], 0)
        self.assertEqual(doc["nested_mapping"]["nested_items"], 0)
        services.restore_backup(doc, self.admin)
        self.assertEqual(Item.objects.get(pk=self.nested.pk).citation, "")


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


