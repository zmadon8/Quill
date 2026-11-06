"""Matter service tests (T2.4, R-FIRM-1, R-FIRM-3, R-FIRM-5, brief 5.12).

Ports ``matterService.test.ts`` and ``matterService.property.test.ts``:

* create a matter (case-insensitive duplicate within the firm ->
  ``DUPLICATE_MATTER_NAME``; the group must belong to the firm ->
  ``PARTNER_NOT_FOUND``; blank/too-long name -> ``INVALID_MATTER_NAME``);
* rename (duplicate check within the firm);
* the MOVE cascade (R-FIRM-3): after moving a matter to another firm/group,
  EVERY memo of that matter has the new ``firm_id`` / ``group_id`` (the key
  test);
* a name collision in the TARGET firm is rejected;
* archive / unarchive;
* list order (``Lower(group name)`` then ``Lower(matter name)``), optional firm
  scope and status filter;
* Q2: "ABC" then "abc" within a firm raises ``DUPLICATE_MATTER_NAME`` (DB
  constraint as backstop).

The property test (``matterService.property.test.ts``) is a seeded
``random.Random`` loop (U8: ~200 cases): names round-trip trimmed, uniqueness
holds case-insensitively, and a move always leaves every memo pointing at the
matter's new firm/group.

ORM tests, so ``TestCase``; everything scoped to a ``Profile(program="fees")``.
"""
import datetime
import random

from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import Profile
from accounts.suite import KEY_FEES
from fees.errors import FeesError
from fees.models import Matter, Memo
from fees.services.firms import add_group, create_firm
from fees.services.matters import (
    MAX_MATTER_NAME,
    archive_matter,
    create_matter,
    get_matter,
    list_matters,
    unarchive_matter,
    update_matter,
)


def fees_profile(name="Ziyad-Fees"):
    return Profile.objects.create(program=KEY_FEES, name=name)


def make_memo(profile, matter, firm, group, **extra):
    data = dict(
        profile=profile,
        matter=matter,
        firm=firm,
        group=group,
        financial_year="2026-27",
        date=datetime.date(2026, 7, 1),
        addressee_line1="To whom it may concern",
        is_draft=False,
    )
    data.update(extra)
    return Memo.objects.create(**data)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


class CreateMatterTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        self.firm = create_firm(self.profile, "Acme")
        self.group = self.firm.groups.first()

    def test_create_trims_name_and_is_active(self):
        matter = create_matter(self.profile, self.firm.pk, self.group.pk, "  Case One  ")
        self.assertEqual(matter.name, "Case One")
        self.assertFalse(matter.is_archived)
        self.assertEqual(matter.firm_id, self.firm.pk)
        self.assertEqual(matter.group_id, self.group.pk)

    def test_create_stores_memo_defaults(self):
        matter = create_matter(
            self.profile, self.firm.pk, self.group.pk, "WithDefaults",
            court_name="High Court", addressee_use_firm_name=True,
            short_name="  WD  ",
        )
        self.assertEqual(matter.court_name, "High Court")
        self.assertTrue(matter.addressee_use_firm_name)
        self.assertEqual(matter.short_name, "WD")

    def test_blank_name_invalid(self):
        with self.assertRaises(FeesError) as ctx:
            create_matter(self.profile, self.firm.pk, self.group.pk, "   ")
        self.assertEqual(ctx.exception.code, "INVALID_MATTER_NAME")

    def test_too_long_name_invalid(self):
        with self.assertRaises(FeesError) as ctx:
            create_matter(
                self.profile, self.firm.pk, self.group.pk, "x" * (MAX_MATTER_NAME + 1)
            )
        self.assertEqual(ctx.exception.code, "INVALID_MATTER_NAME")

    def test_missing_firm(self):
        with self.assertRaises(FeesError) as ctx:
            create_matter(self.profile, 999999, self.group.pk, "X")
        self.assertEqual(ctx.exception.code, "FIRM_NOT_FOUND")

    def test_group_must_belong_to_firm(self):
        other_firm = create_firm(self.profile, "Other")
        other_group = other_firm.groups.first()
        with self.assertRaises(FeesError) as ctx:
            create_matter(self.profile, self.firm.pk, other_group.pk, "X")
        self.assertEqual(ctx.exception.code, "PARTNER_NOT_FOUND")

    def test_duplicate_name_within_firm_case_insensitive(self):
        create_matter(self.profile, self.firm.pk, self.group.pk, "ABC")
        with self.assertRaises(FeesError) as ctx:
            create_matter(self.profile, self.firm.pk, self.group.pk, "abc")
        self.assertEqual(ctx.exception.code, "DUPLICATE_MATTER_NAME")

    def test_same_name_allowed_in_a_different_firm(self):
        create_matter(self.profile, self.firm.pk, self.group.pk, "Shared")
        other_firm = create_firm(self.profile, "Other")
        other_group = other_firm.groups.first()
        matter = create_matter(self.profile, other_firm.pk, other_group.pk, "Shared")
        self.assertEqual(matter.name, "Shared")


# ---------------------------------------------------------------------------
# Q2 case-insensitive uniqueness with DB backstop
# ---------------------------------------------------------------------------


class CourtNameLengthTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        self.firm = create_firm(self.profile, "Acme")
        self.group = self.firm.groups.first()

    def test_overlong_court_name_rejected(self):
        from fees.services.memos import MAX_MEMO_TEXT

        with self.assertRaises(FeesError) as ctx:
            create_matter(
                self.profile, self.firm.pk, self.group.pk, "M",
                court_name="x" * (MAX_MEMO_TEXT + 1),
            )
        self.assertEqual(ctx.exception.code, "INVALID_MATTER")
        self.assertFalse(Matter.objects.filter(profile=self.profile).exists())

    def test_court_name_at_limit_accepted(self):
        from fees.services.memos import MAX_MEMO_TEXT

        matter = create_matter(
            self.profile, self.firm.pk, self.group.pk, "M",
            court_name="x" * MAX_MEMO_TEXT,
        )
        self.assertEqual(len(matter.court_name), MAX_MEMO_TEXT)


class MatterCaseInsensitiveUniquenessTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        self.firm = create_firm(self.profile, "Acme")
        self.group = self.firm.groups.first()

    def test_abc_then_abc_lower_raises_service_error(self):
        create_matter(self.profile, self.firm.pk, self.group.pk, "ABC")
        with self.assertRaises(FeesError) as ctx:
            create_matter(self.profile, self.firm.pk, self.group.pk, "abc")
        self.assertEqual(ctx.exception.code, "DUPLICATE_MATTER_NAME")

    def test_db_constraint_is_the_backstop(self):
        create_matter(self.profile, self.firm.pk, self.group.pk, "ABC")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Matter.objects.create(
                    profile=self.profile, firm=self.firm, group=self.group, name="abc"
                )


# ---------------------------------------------------------------------------
# Update: rename + the MOVE cascade (R-FIRM-3)
# ---------------------------------------------------------------------------


class UpdateMatterTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        self.firm_a = create_firm(self.profile, "Firm A")
        self.group_a = self.firm_a.groups.first()
        self.group_a2 = add_group(self.profile, self.firm_a.pk, "A Second")
        self.firm_b = create_firm(self.profile, "Firm B")
        self.group_b = self.firm_b.groups.first()

    def _matter_with_memos(self, name, n=3):
        matter = create_matter(self.profile, self.firm_a.pk, self.group_a.pk, name)
        for i in range(n):
            make_memo(
                self.profile, matter, self.firm_a, self.group_a,
                memo_number=f"2026-27/{i + 1}", seq=i + 1,
            )
        return matter

    def test_rename_within_firm(self):
        matter = create_matter(self.profile, self.firm_a.pk, self.group_a.pk, "Old")
        update_matter(self.profile, matter.pk, name="  New  ")
        matter.refresh_from_db()
        self.assertEqual(matter.name, "New")

    def test_rename_duplicate_rejected(self):
        create_matter(self.profile, self.firm_a.pk, self.group_a.pk, "Taken")
        matter = create_matter(self.profile, self.firm_a.pk, self.group_a.pk, "Free")
        with self.assertRaises(FeesError) as ctx:
            update_matter(self.profile, matter.pk, name="taken")
        self.assertEqual(ctx.exception.code, "DUPLICATE_MATTER_NAME")

    def test_update_applies_memo_defaults(self):
        matter = create_matter(self.profile, self.firm_a.pk, self.group_a.pk, "M")
        update_matter(self.profile, matter.pk, court_name="Supreme Court")
        matter.refresh_from_db()
        self.assertEqual(matter.court_name, "Supreme Court")

    def test_move_to_another_group_cascades_to_all_memos(self):
        matter = self._matter_with_memos("Movable", n=3)
        update_matter(self.profile, matter.pk, group_id=self.group_a2.pk)
        matter.refresh_from_db()
        self.assertEqual(matter.group_id, self.group_a2.pk)
        self.assertEqual(matter.firm_id, self.firm_a.pk)
        memos = Memo.objects.filter(matter=matter)
        self.assertEqual(memos.count(), 3)
        for memo in memos:
            self.assertEqual(memo.group_id, self.group_a2.pk)
            self.assertEqual(memo.firm_id, self.firm_a.pk)

    def test_move_to_another_firm_cascades_to_all_memos(self):
        matter = self._matter_with_memos("CrossFirm", n=4)
        update_matter(
            self.profile, matter.pk, firm_id=self.firm_b.pk, group_id=self.group_b.pk
        )
        matter.refresh_from_db()
        self.assertEqual(matter.firm_id, self.firm_b.pk)
        self.assertEqual(matter.group_id, self.group_b.pk)
        memos = Memo.objects.filter(matter=matter)
        self.assertEqual(memos.count(), 4)
        for memo in memos:
            self.assertEqual(memo.firm_id, self.firm_b.pk)
            self.assertEqual(memo.group_id, self.group_b.pk)

    def test_move_target_group_must_belong_to_target_firm(self):
        matter = self._matter_with_memos("Bad", n=1)
        with self.assertRaises(FeesError) as ctx:
            # firm_b with firm_a's group
            update_matter(
                self.profile, matter.pk, firm_id=self.firm_b.pk, group_id=self.group_a.pk
            )
        self.assertEqual(ctx.exception.code, "PARTNER_NOT_FOUND")
        # Nothing moved.
        matter.refresh_from_db()
        self.assertEqual(matter.firm_id, self.firm_a.pk)

    def test_move_rejects_name_collision_in_target_firm(self):
        # firm_b already has a matter named "Clash".
        create_matter(self.profile, self.firm_b.pk, self.group_b.pk, "Clash")
        matter = create_matter(self.profile, self.firm_a.pk, self.group_a.pk, "clash")
        with self.assertRaises(FeesError) as ctx:
            update_matter(
                self.profile, matter.pk, firm_id=self.firm_b.pk, group_id=self.group_b.pk
            )
        self.assertEqual(ctx.exception.code, "DUPLICATE_MATTER_NAME")
        # The matter did not move.
        matter.refresh_from_db()
        self.assertEqual(matter.firm_id, self.firm_a.pk)

    def test_missing_matter(self):
        with self.assertRaises(FeesError) as ctx:
            update_matter(self.profile, 999999, name="X")
        self.assertEqual(ctx.exception.code, "MATTER_NOT_FOUND")


# ---------------------------------------------------------------------------
# List / Get
# ---------------------------------------------------------------------------


class ListMattersTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        self.firm = create_firm(self.profile, "Acme")
        self.g_zed = self.firm.groups.first()  # "Acme"
        self.g_alpha = add_group(self.profile, self.firm.pk, "Alpha")
        # Under Alpha: "beta", "Apple"; under Acme: "delta".
        create_matter(self.profile, self.firm.pk, self.g_alpha.pk, "beta")
        create_matter(self.profile, self.firm.pk, self.g_alpha.pk, "Apple")
        create_matter(self.profile, self.firm.pk, self.g_zed.pk, "delta")

    def test_order_by_lower_group_then_lower_matter(self):
        matters = list(list_matters(self.profile, firm_id=self.firm.pk))
        names = [(m.group.name, m.name) for m in matters]
        # Group "Acme" < "Alpha"; within Alpha "Apple" < "beta".
        self.assertEqual(
            names,
            [("Acme", "delta"), ("Alpha", "Apple"), ("Alpha", "beta")],
        )

    def test_status_filter(self):
        m = create_matter(self.profile, self.firm.pk, self.g_zed.pk, "archived one")
        archive_matter(self.profile, m.pk)
        active = {x.name for x in list_matters(self.profile, status_filter="active")}
        archived = {x.name for x in list_matters(self.profile, status_filter="archived")}
        self.assertIn("delta", active)
        self.assertNotIn("archived one", active)
        self.assertEqual(archived, {"archived one"})

    def test_scoped_to_firm(self):
        other = create_firm(self.profile, "Other")
        create_matter(self.profile, other.pk, other.groups.first().pk, "elsewhere")
        names = {m.name for m in list_matters(self.profile, firm_id=self.firm.pk)}
        self.assertNotIn("elsewhere", names)


class GetArchiveTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        self.firm = create_firm(self.profile, "Acme")
        self.group = self.firm.groups.first()

    def test_get_matter(self):
        matter = create_matter(self.profile, self.firm.pk, self.group.pk, "Case")
        got = get_matter(self.profile, matter.pk)
        self.assertEqual(got.pk, matter.pk)
        self.assertEqual(got.firm.name, "Acme")

    def test_get_matter_missing(self):
        with self.assertRaises(FeesError) as ctx:
            get_matter(self.profile, 999999)
        self.assertEqual(ctx.exception.code, "MATTER_NOT_FOUND")

    def test_archive_and_unarchive(self):
        matter = create_matter(self.profile, self.firm.pk, self.group.pk, "Case")
        archive_matter(self.profile, matter.pk)
        matter.refresh_from_db()
        self.assertTrue(matter.is_archived)
        unarchive_matter(self.profile, matter.pk)
        matter.refresh_from_db()
        self.assertFalse(matter.is_archived)


# ---------------------------------------------------------------------------
# Property test (seeded loop; U8)
# ---------------------------------------------------------------------------


class MatterPropertyTests(TestCase):
    """Seeded port of ``matterService.property.test.ts`` (~200 cases)."""

    SEED = 31337
    RUNS = 200

    def test_names_round_trip_uniqueness_and_move_cascade(self):
        profile = fees_profile()
        firm_a = create_firm(profile, "Alpha Firm")
        firm_b = create_firm(profile, "Bravo Firm")
        group_a = firm_a.groups.first()
        group_b = firm_b.groups.first()
        rng = random.Random(self.SEED)
        used_in_a = set()
        for _ in range(self.RUNS):
            core = "".join(
                rng.choice("abcdefghijklmnop ABC")
                for _ in range(rng.randint(1, 10))
            ).strip()
            if not core:
                continue
            pad = " " * rng.randint(0, 3)
            raw = f"{pad}{core}{pad}"
            if core.lower() in used_in_a:
                with self.assertRaises(FeesError) as ctx:
                    create_matter(profile, firm_a.pk, group_a.pk, raw)
                self.assertEqual(ctx.exception.code, "DUPLICATE_MATTER_NAME")
                continue
            matter = create_matter(profile, firm_a.pk, group_a.pk, raw)
            used_in_a.add(core.lower())
            # Name stored trimmed.
            self.assertEqual(matter.name, core)
            # Give the matter a couple of memos then move it to firm B.
            n = rng.randint(0, 3)
            for i in range(n):
                make_memo(profile, matter, firm_a, group_a, seq=i + 1)
            # Moving may collide if firm B already has this name; guard it.
            if Matter.objects.filter(
                profile=profile, firm=firm_b, name__iexact=core
            ).exists():
                continue
            update_matter(profile, matter.pk, firm_id=firm_b.pk, group_id=group_b.pk)
            matter.refresh_from_db()
            self.assertEqual(matter.firm_id, firm_b.pk)
            self.assertEqual(matter.group_id, group_b.pk)
            # Every memo points at the new firm/group.
            for memo in Memo.objects.filter(matter=matter):
                self.assertEqual(memo.firm_id, firm_b.pk)
                self.assertEqual(memo.group_id, group_b.pk)
            used_in_a.discard(core.lower())
