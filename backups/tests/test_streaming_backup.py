"""Tests for the streaming suite backup serialiser (T1.4, RAM R1, R2, R3, R4).

Three behaviour checks and one memory gate:

* the reference builder (``_build_document``) and the streaming writer
  (``write_document`` via ``create_backup``) produce the same parsed document;
* a backup through the historical applied state (the pre-migration path) still
  builds a valid file;
* ``create_backup`` keeps its peak Python allocations under 15 MB on a large
  synthetic diary dataset.

The numeric memory gate is measured by ``tracemalloc``. The test is tagged
``memory`` so it can be skipped locally (``--exclude-tag=memory``) but runs in CI.
"""
import gzip
import io
import json
import tracemalloc
from contextlib import contextmanager

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings, tag

from accounts.models import Profile, ProfileMembership
from backups import registry, services
from diary.models import Case, Item, Subject, Subtopic, Topic
from diary.tests.helpers import main_profile

User = get_user_model()
PASSWORD = "correct-horse-battery-9"
MAX = 30 * 1024 * 1024


def gunzip_json(raw):
    return json.loads(gzip.decompress(bytes(raw)).decode("utf-8"))


@contextmanager
def assert_peak_under(testcase, mb):
    """Assert the peak Python allocations inside the block stay under ``mb`` megabytes.

    ``tracemalloc`` counts Python allocations, where nearly all the growth is; it under-counts C
    extensions a little, so thresholds in the RAM budget carry a margin (section 8). On failure the
    peak and the ten largest allocation sites are shown.
    """
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        yield
        _current, peak = tracemalloc.get_traced_memory()
        snapshot = tracemalloc.take_snapshot()
    finally:
        tracemalloc.stop()
    limit = mb * 1024 * 1024
    if peak > limit:
        top = snapshot.statistics("lineno")[:10]
        report = "\n".join(str(line) for line in top)
        testcase.fail(
            f"peak {peak / 1024 / 1024:.1f} MB exceeded the {mb} MB cap.\nTop allocations:\n{report}"
        )


@override_settings(SECURE_SSL_REDIRECT=False)
class StreamingBuilderEqualityTests(TestCase):
    """The streaming writer must produce the same document as the in-memory reference builder."""

    def setUp(self):
        self.admin = User.objects.create_user("boss", password=PASSWORD, is_superuser=True, is_staff=True)
        self.alice = User.objects.create_user("alice", password=PASSWORD)
        main = main_profile()
        junior = Profile.objects.create(program="diary", name="Junior")
        ProfileMembership.objects.create(user=self.admin, profile=main, role="editor")
        ProfileMembership.objects.create(user=self.alice, profile=junior, role="reader")
        for profile in (main, junior):
            for n in range(3):
                subject = Subject.objects.create(profile=profile, name=f"{profile.name} subject {n}")
                topic = Topic.objects.create(profile=profile, subject=subject, name=f"Topic {n}", position=1)
                subtopic = Subtopic.objects.create(profile=profile, topic=topic, name=f"Sub {n}", position=1)
                item = Item.objects.create(profile=profile, subtopic=subtopic, text=f"<p>Rule {n}</p>", position=1)
                Case.objects.create(profile=profile, item=item, citation=f"A{n} v B{n}", position=1)

    def _stream_bytes(self, now):
        buffer = io.BytesIO()
        counts = services.write_document(buffer, now)
        return buffer.getvalue(), counts

    def test_streamed_bytes_parse_to_the_reference_document(self):
        now = services.timezone.now()
        reference, ref_counts = services._build_document(now)
        raw, stream_counts = self._stream_bytes(now)
        streamed = gunzip_json(raw)
        self.assertEqual(streamed, reference)
        self.assertEqual(stream_counts, ref_counts)

    def test_streamed_document_keeps_layout_and_order(self):
        now = services.timezone.now()
        raw, _counts = self._stream_bytes(now)
        document = gunzip_json(raw)
        self.assertEqual(document["format"], services.FORMAT_MARKER)
        self.assertEqual(document["format_version"], 1)
        self.assertEqual(document["created_at"], now.isoformat())
        self.assertEqual(list(document["models"]), registry.BACKUP_MODELS)
        self.assertEqual(document["counts"]["diary.Subject"], 6)
        self.assertEqual(document["counts"]["diary.Case"], 6)

    def test_create_backup_stores_the_streamed_bytes(self):
        backup = services.create_backup("manual", self.admin)
        # Storage is byte-identical to a valid gzip of the reference document.
        document = gunzip_json(backup.data)
        reference, _counts = services._build_document(services.timezone.now())
        self.assertEqual(document["models"], reference["models"])
        self.assertEqual(backup.record_counts, document["counts"])
        import hashlib

        self.assertEqual(backup.sha256, hashlib.sha256(bytes(backup.data)).hexdigest())
        self.assertEqual(backup.size_bytes, len(bytes(backup.data)))

    def test_datetimes_keep_microseconds_in_the_streamed_file(self):
        backup = services.create_backup("manual", self.admin)
        document = gunzip_json(backup.data)
        stamp = document["models"]["diary.Subject"][0]["fields"]["created_at"]
        self.assertRegex(stamp, r"\.\d{6}(Z|\+|-|$)")

    def test_round_trip_through_streamed_backup(self):
        backup = services.create_backup("manual", self.admin)
        document = services.parse_backup(backup.data, MAX)
        Subject.objects.all().delete()
        self.assertEqual(Subject.objects.count(), 0)
        services.restore_backup(document, self.admin)
        self.assertEqual(Subject.objects.count(), 6)
        self.assertEqual(Case.objects.count(), 6)


@override_settings(SECURE_SSL_REDIRECT=False)
class PreMigrationStreamingTests(TestCase):
    """create_backup(use_applied_state=True) reads through the historical models and still builds a valid file."""

    def setUp(self):
        self.admin = User.objects.create_user("boss", password=PASSWORD, is_superuser=True, is_staff=True)
        Subject.objects.create(profile=main_profile(), name="Historical")

    def test_applied_state_backup_is_valid(self):
        backup = services.create_backup("pre_migrate", self.admin, use_applied_state=True)
        document = services.parse_backup(backup.data, MAX)
        self.assertEqual(document["format_version"], 1)
        self.assertEqual(document["models"]["diary.Subject"][0]["fields"]["name"], "Historical")
        # Every model that exists in the applied state is present (the test database is fully migrated,
        # so optional models such as diary.TrashBatch and accounts.Profile have tables and are included).
        # The historical-state rule only drops an optional model when its table does not exist yet; that
        # branch is exercised by migration-state tests elsewhere. Here we assert the file is well formed.
        for label in registry.BACKUP_MODELS:
            self.assertIn(label, document["models"])
            self.assertIsInstance(document["models"][label], list)


@tag("memory")
@override_settings(SECURE_SSL_REDIRECT=False)
class StreamingBackupMemoryTests(TestCase):
    """Peak Python allocations during create_backup stay under 15 MB on a large synthetic diary.

    Tagged ``memory``: excluded locally with ``--exclude-tag=memory`` and run in CI. The threshold
    carries the RAM budget margin (section 8); the authoritative number is measured by CI on Postgres.
    """

    def setUp(self):
        self.admin = User.objects.create_user("boss", password=PASSWORD, is_superuser=True, is_staff=True)
        self.profile = main_profile()
        subject = Subject.objects.create(profile=self.profile, name="Bulk subject")
        topic = Topic.objects.create(profile=self.profile, subject=subject, name="Bulk topic", position=1)
        subtopic = Subtopic.objects.create(profile=self.profile, topic=topic, name="Bulk sub", position=1)
        # A large synthetic diary: many Items with a Case each, built with bulk_create.
        items = [
            Item(profile=self.profile, subtopic=subtopic, text=f"<p>Rule number {n} with some text</p>", position=n)
            for n in range(6000)
        ]
        Item.objects.bulk_create(items, batch_size=500)
        saved = list(Item.objects.filter(subtopic=subtopic).order_by("pk"))
        cases = [
            Case(profile=self.profile, item=item, citation=f"Case {n} v Another {n}", position=1)
            for n, item in enumerate(saved)
        ]
        Case.objects.bulk_create(cases, batch_size=500)

    def test_create_backup_peak_under_15mb(self):
        with assert_peak_under(self, 15):
            backup = services.create_backup("manual", self.admin)
        # The file is still correct at this size.
        self.assertEqual(backup.record_counts["diary.Item"], 6000)
        self.assertEqual(backup.record_counts["diary.Case"], 6000)
