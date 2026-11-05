"""Firm and Group service tests (T2.4, R-FIRM-1 to R-FIRM-5, brief 5.12).

Ports ``firmService.test.ts`` and ``firmService.property.test.ts``:

* create a firm also creates a same-named group in one transaction (R-FIRM-2);
* firm list order (``Lower(name)``) and the all/active/archived status filter on
  the STORED status (deviation from the original derived status, R-FIRM-5);
* add / update / remove a group (the UI "Group"; the codes stay PARTNER);
* at most 50 groups per firm -> ``TOO_MANY_PARTNERS``;
* case-insensitive duplicate firm / group names -> ``DUPLICATE_*`` (brief 15 Q2:
  "ABC" then "abc"), with the DB constraint as the backstop;
* invalid (blank / too long) names -> ``INVALID_*``;
* removing a group still used by a matter -> ``GROUP_IN_USE`` (409);
* matter roll-ups (no memos -> no status; Overdue/Unpaid/Paid precedence over
  live memos; all-written-off -> no status but ``has_written_off``);
* recent matters (order, limit, latest memo number).

The property test (``firmService.property.test.ts``) is a seeded
``random.Random`` loop (U8: Hypothesis not approved, ~200 cases) over name
round-trips, case-insensitive uniqueness, and the "a firm always has exactly one
same-named group" invariant.

These tests use the ORM, so ``TestCase`` is used; everything is scoped to a
``Profile(program="fees")``.
"""
import datetime
import random
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import Profile
from accounts.suite import KEY_FEES
from fees.errors import FeesError
from fees.models import FIRM_ACTIVE, FIRM_ARCHIVED, FeesSettings, Firm, Group, Matter, Memo
from fees.services.firms import (
    MAX_FIRM_NAME,
    MAX_GROUPS,
    add_group,
    create_firm,
    get_firm,
    list_firms,
    matter_rollups,
    recent_matters,
    remove_group,
    set_firm_status,
    update_firm,
    update_group,
)


def fees_profile(name="Ziyad-Fees"):
    return Profile.objects.create(program=KEY_FEES, name=name)


def make_matter(profile, firm, group, name):
    return Matter.objects.create(profile=profile, firm=firm, group=group, name=name)


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
# Create firm (+ same-named group)
# ---------------------------------------------------------------------------


class CreateFirmTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()

    def test_create_firm_also_creates_a_same_named_group(self):
        firm = create_firm(self.profile, "  Acme & Co  ")
        self.assertEqual(firm.name, "Acme & Co")
        self.assertEqual(firm.status, FIRM_ACTIVE)
        groups = list(firm.groups.all())
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].name, "Acme & Co")
        self.assertEqual(groups[0].profile_id, self.profile.pk)

    def test_blank_name_is_invalid(self):
        with self.assertRaises(FeesError) as ctx:
            create_firm(self.profile, "   ")
        self.assertEqual(ctx.exception.code, "INVALID_FIRM_NAME")
        self.assertEqual(ctx.exception.status, 422)

    def test_too_long_name_is_invalid(self):
        with self.assertRaises(FeesError) as ctx:
            create_firm(self.profile, "x" * (MAX_FIRM_NAME + 1))
        self.assertEqual(ctx.exception.code, "INVALID_FIRM_NAME")

    def test_duplicate_firm_name_case_insensitive(self):
        create_firm(self.profile, "ABC")
        with self.assertRaises(FeesError) as ctx:
            create_firm(self.profile, "abc")
        self.assertEqual(ctx.exception.code, "DUPLICATE_FIRM_NAME")
        self.assertEqual(ctx.exception.status, 409)

    def test_duplicate_is_scoped_to_profile(self):
        other = fees_profile("Other-Fees")
        create_firm(self.profile, "Acme")
        # The same name is free in a different profile.
        firm = create_firm(other, "Acme")
        self.assertEqual(firm.name, "Acme")


# ---------------------------------------------------------------------------
# List / status filter
# ---------------------------------------------------------------------------


class ListFirmsTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        self.b = create_firm(self.profile, "Bravo")
        self.a = create_firm(self.profile, "alpha")
        self.c = create_firm(self.profile, "Charlie")
        set_firm_status(self.profile, self.c.pk, FIRM_ARCHIVED)

    def test_ordered_by_lower_name(self):
        names = [f.name for f in list_firms(self.profile, "all")]
        self.assertEqual(names, ["alpha", "Bravo", "Charlie"])

    def test_active_filter_uses_stored_status(self):
        names = {f.name for f in list_firms(self.profile, "active")}
        self.assertEqual(names, {"alpha", "Bravo"})

    def test_archived_filter(self):
        names = [f.name for f in list_firms(self.profile, "archived")]
        self.assertEqual(names, ["Charlie"])

    def test_list_is_scoped_to_profile(self):
        other = fees_profile("Other-Fees")
        create_firm(other, "Zeta")
        names = [f.name for f in list_firms(self.profile, "all")]
        self.assertNotIn("Zeta", names)


class SetFirmStatusTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        self.firm = create_firm(self.profile, "Acme")

    def test_set_and_normalise_status(self):
        set_firm_status(self.profile, self.firm.pk, FIRM_ARCHIVED)
        self.firm.refresh_from_db()
        self.assertEqual(self.firm.status, FIRM_ARCHIVED)
        # Anything other than "archived" normalises to active.
        set_firm_status(self.profile, self.firm.pk, "whatever")
        self.firm.refresh_from_db()
        self.assertEqual(self.firm.status, FIRM_ACTIVE)

    def test_missing_firm_raises(self):
        with self.assertRaises(FeesError) as ctx:
            set_firm_status(self.profile, 999999, FIRM_ARCHIVED)
        self.assertEqual(ctx.exception.code, "FIRM_NOT_FOUND")
        self.assertEqual(ctx.exception.status, 404)

    def test_other_profile_firm_is_not_found(self):
        other = fees_profile("Other-Fees")
        with self.assertRaises(FeesError) as ctx:
            set_firm_status(other, self.firm.pk, FIRM_ARCHIVED)
        self.assertEqual(ctx.exception.code, "FIRM_NOT_FOUND")


class UpdateFirmTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        self.firm = create_firm(self.profile, "Acme")
        create_firm(self.profile, "Beta")

    def test_rename_and_notes(self):
        update_firm(self.profile, self.firm.pk, name="  Acme Legal  ", notes="a note")
        self.firm.refresh_from_db()
        self.assertEqual(self.firm.name, "Acme Legal")
        self.assertEqual(self.firm.notes, "a note")

    def test_rename_rejects_case_insensitive_duplicate(self):
        with self.assertRaises(FeesError) as ctx:
            update_firm(self.profile, self.firm.pk, name="beta")
        self.assertEqual(ctx.exception.code, "DUPLICATE_FIRM_NAME")

    def test_rename_to_its_own_name_is_allowed(self):
        update_firm(self.profile, self.firm.pk, name="acme")
        self.firm.refresh_from_db()
        self.assertEqual(self.firm.name, "acme")


# ---------------------------------------------------------------------------
# Groups (UI "Group"; codes keep PARTNER)
# ---------------------------------------------------------------------------


class GroupTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        self.firm = create_firm(self.profile, "Acme")

    def test_add_group(self):
        group = add_group(self.profile, self.firm.pk, "  Litigation  ")
        self.assertEqual(group.name, "Litigation")
        self.assertEqual(group.firm_id, self.firm.pk)

    def test_add_group_blank_is_invalid(self):
        with self.assertRaises(FeesError) as ctx:
            add_group(self.profile, self.firm.pk, "  ")
        self.assertEqual(ctx.exception.code, "INVALID_PARTNER_NAME")

    def test_add_group_duplicate_case_insensitive(self):
        add_group(self.profile, self.firm.pk, "Litigation")
        with self.assertRaises(FeesError) as ctx:
            add_group(self.profile, self.firm.pk, "litigation")
        self.assertEqual(ctx.exception.code, "DUPLICATE_PARTNER_NAME")

    def test_add_group_missing_firm(self):
        with self.assertRaises(FeesError) as ctx:
            add_group(self.profile, 999999, "Any")
        self.assertEqual(ctx.exception.code, "FIRM_NOT_FOUND")

    def test_too_many_groups(self):
        # The firm already has one same-named group from create_firm.
        while self.firm.groups.count() < MAX_GROUPS:
            add_group(self.profile, self.firm.pk, f"G{self.firm.groups.count()}")
        self.assertEqual(self.firm.groups.count(), MAX_GROUPS)
        with self.assertRaises(FeesError) as ctx:
            add_group(self.profile, self.firm.pk, "one too many")
        self.assertEqual(ctx.exception.code, "TOO_MANY_PARTNERS")
        self.assertEqual(ctx.exception.status, 422)

    def test_update_group_rename_and_duplicate(self):
        g1 = add_group(self.profile, self.firm.pk, "Litigation")
        add_group(self.profile, self.firm.pk, "Advisory")
        update_group(self.profile, g1.pk, "  Disputes  ")
        g1.refresh_from_db()
        self.assertEqual(g1.name, "Disputes")
        with self.assertRaises(FeesError) as ctx:
            update_group(self.profile, g1.pk, "advisory")
        self.assertEqual(ctx.exception.code, "DUPLICATE_PARTNER_NAME")

    def test_update_group_missing(self):
        with self.assertRaises(FeesError) as ctx:
            update_group(self.profile, 999999, "X")
        self.assertEqual(ctx.exception.code, "PARTNER_NOT_FOUND")

    def test_remove_group(self):
        group = add_group(self.profile, self.firm.pk, "Temp")
        remove_group(self.profile, self.firm.pk, group.pk)
        self.assertFalse(Group.objects.filter(pk=group.pk).exists())

    def test_remove_group_missing(self):
        with self.assertRaises(FeesError) as ctx:
            remove_group(self.profile, self.firm.pk, 999999)
        self.assertEqual(ctx.exception.code, "PARTNER_NOT_FOUND")

    def test_remove_group_in_use_raises_409(self):
        group = add_group(self.profile, self.firm.pk, "Used")
        make_matter(self.profile, self.firm, group, "Case 1")
        with self.assertRaises(FeesError) as ctx:
            remove_group(self.profile, self.firm.pk, group.pk)
        self.assertEqual(ctx.exception.code, "GROUP_IN_USE")
        self.assertEqual(ctx.exception.status, 409)
        # The group was NOT deleted (the guard runs before any delete).
        self.assertTrue(Group.objects.filter(pk=group.pk).exists())


# ---------------------------------------------------------------------------
# Q2: case-insensitive uniqueness (service error, with the DB constraint behind)
# ---------------------------------------------------------------------------


class CaseInsensitiveUniquenessTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()

    def test_firm_abc_then_abc_lower_raises_service_error(self):
        create_firm(self.profile, "ABC")
        with self.assertRaises(FeesError) as ctx:
            create_firm(self.profile, "abc")
        self.assertEqual(ctx.exception.code, "DUPLICATE_FIRM_NAME")

    def test_firm_db_constraint_is_the_backstop(self):
        create_firm(self.profile, "ABC")
        # Bypassing the service, the DB UniqueConstraint(Lower(name), profile) fires.
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Firm.objects.create(profile=self.profile, name="abc")

    def test_group_abc_then_abc_lower_raises_service_error(self):
        firm = create_firm(self.profile, "Firm")
        add_group(self.profile, firm.pk, "ABC")
        with self.assertRaises(FeesError) as ctx:
            add_group(self.profile, firm.pk, "abc")
        self.assertEqual(ctx.exception.code, "DUPLICATE_PARTNER_NAME")


# ---------------------------------------------------------------------------
# Matter roll-ups
# ---------------------------------------------------------------------------


class MatterRollupTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        self.firm = create_firm(self.profile, "Acme")
        self.group = self.firm.groups.first()
        FeesSettings.objects.create(profile=self.profile, overdue_days=30)

    def _matter(self, name):
        return make_matter(self.profile, self.firm, self.group, name)

    def test_matter_with_no_memos_has_no_status(self):
        matter = self._matter("Empty")
        rolls = matter_rollups(self.profile, self.firm.pk)
        self.assertNotIn(matter.pk, rolls)
        # And through get_firm the matter still shows a null status.
        detail = get_firm(self.profile, self.firm.pk)
        row = next(r for r in detail["matters"] if r["matter"].pk == matter.pk)
        self.assertIsNone(row["memo_status"])
        self.assertFalse(row["has_written_off"])

    def test_draft_memos_are_ignored(self):
        matter = self._matter("Drafty")
        make_memo(
            self.profile, matter, self.firm, self.group, is_draft=True,
            total_fees=Decimal("1000"), amount_paid=Decimal("0"),
        )
        rolls = matter_rollups(self.profile, self.firm.pk)
        self.assertNotIn(matter.pk, rolls)

    def test_paid_when_all_live_memos_paid(self):
        matter = self._matter("Paid")
        make_memo(
            self.profile, matter, self.firm, self.group,
            total_fees=Decimal("1000"), amount_paid=Decimal("1000"),
        )
        rolls = matter_rollups(self.profile, self.firm.pk)
        self.assertEqual(rolls[matter.pk]["memo_status"], "Paid")
        self.assertFalse(rolls[matter.pk]["has_written_off"])

    def test_unpaid_takes_precedence_over_paid(self):
        matter = self._matter("Unpaid")
        make_memo(
            self.profile, matter, self.firm, self.group,
            total_fees=Decimal("1000"), amount_paid=Decimal("1000"),
        )
        make_memo(
            self.profile, matter, self.firm, self.group,
            date=datetime.date.today(),
            total_fees=Decimal("1000"), amount_paid=Decimal("0"),
        )
        rolls = matter_rollups(self.profile, self.firm.pk)
        self.assertEqual(rolls[matter.pk]["memo_status"], "Unpaid")

    def test_overdue_takes_precedence(self):
        matter = self._matter("Overdue")
        old = datetime.date.today() - datetime.timedelta(days=100)
        make_memo(
            self.profile, matter, self.firm, self.group, date=old,
            total_fees=Decimal("1000"), amount_paid=Decimal("0"),
        )
        rolls = matter_rollups(self.profile, self.firm.pk)
        self.assertEqual(rolls[matter.pk]["memo_status"], "Overdue")

    def test_all_written_off_has_no_primary_status(self):
        matter = self._matter("WrittenOff")
        make_memo(
            self.profile, matter, self.firm, self.group, written_off=True,
            total_fees=Decimal("1000"), amount_paid=Decimal("0"),
        )
        rolls = matter_rollups(self.profile, self.firm.pk)
        self.assertIsNone(rolls[matter.pk]["memo_status"])
        self.assertTrue(rolls[matter.pk]["has_written_off"])

    def test_written_off_does_not_turn_unpaid_into_paid(self):
        matter = self._matter("Mixed")
        # One live unpaid memo and one written-off memo.
        make_memo(
            self.profile, matter, self.firm, self.group,
            date=datetime.date.today(),
            total_fees=Decimal("1000"), amount_paid=Decimal("0"),
        )
        make_memo(
            self.profile, matter, self.firm, self.group, written_off=True,
            total_fees=Decimal("500"), amount_paid=Decimal("0"),
        )
        rolls = matter_rollups(self.profile, self.firm.pk)
        self.assertEqual(rolls[matter.pk]["memo_status"], "Unpaid")
        self.assertTrue(rolls[matter.pk]["has_written_off"])

    def test_overdue_days_zero_means_never_overdue(self):
        matter = self._matter("OldButNotOverdue")
        old = datetime.date.today() - datetime.timedelta(days=1000)
        make_memo(
            self.profile, matter, self.firm, self.group, date=old,
            total_fees=Decimal("1000"), amount_paid=Decimal("0"),
        )
        rolls = matter_rollups(self.profile, self.firm.pk, overdue_days=0)
        self.assertEqual(rolls[matter.pk]["memo_status"], "Unpaid")


# ---------------------------------------------------------------------------
# Recent matters
# ---------------------------------------------------------------------------


class RecentMattersTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        self.firm = create_firm(self.profile, "Acme")
        self.group = self.firm.groups.first()

    def test_order_by_latest_date_and_limit(self):
        for i in range(12):
            matter = make_matter(self.profile, self.firm, self.group, f"Matter {i}")
            make_memo(
                self.profile, matter, self.firm, self.group,
                date=datetime.date(2026, 7, 1) + datetime.timedelta(days=i),
                memo_number=f"2026-27/{i + 1}", seq=i + 1,
            )
        recent = recent_matters(self.profile, limit=10)
        self.assertEqual(len(recent), 10)
        dates = [r["last_memo_date"] for r in recent]
        self.assertEqual(dates, sorted(dates, reverse=True))
        # The most recent (i == 11) is first.
        self.assertEqual(recent[0]["matter_name"], "Matter 11")
        self.assertEqual(recent[0]["firm_name"], "Acme")

    def test_latest_memo_number_and_count(self):
        matter = make_matter(self.profile, self.firm, self.group, "Busy")
        make_memo(
            self.profile, matter, self.firm, self.group,
            date=datetime.date(2026, 7, 1), memo_number="2026-27/1", seq=1,
        )
        make_memo(
            self.profile, matter, self.firm, self.group,
            date=datetime.date(2026, 8, 1), memo_number="2026-27/2", seq=2,
        )
        recent = recent_matters(self.profile)
        row = next(r for r in recent if r["matter_id"] == matter.pk)
        self.assertEqual(row["memo_count"], 2)
        self.assertEqual(row["last_memo_number"], "2026-27/2")
        self.assertFalse(row["is_archived"])

    def test_drafts_excluded(self):
        matter = make_matter(self.profile, self.firm, self.group, "OnlyDraft")
        make_memo(self.profile, matter, self.firm, self.group, is_draft=True)
        recent = recent_matters(self.profile)
        self.assertEqual(recent, [])


# ---------------------------------------------------------------------------
# Property tests (seeded loops; U8: no Hypothesis)
# ---------------------------------------------------------------------------


class FirmPropertyTests(TestCase):
    """Seeded port of ``firmService.property.test.ts`` (~200 cases)."""

    SEED = 24041
    RUNS = 200

    def test_firm_names_round_trip_trimmed_and_create_one_group(self):
        profile = fees_profile()
        rng = random.Random(self.SEED)
        used = set()
        created = 0
        for _ in range(self.RUNS):
            core = "".join(
                rng.choice("abcdefghijklmnopqrstuvwxyz ABC")
                for _ in range(rng.randint(1, 12))
            ).strip()
            if not core:
                continue
            pad = " " * rng.randint(0, 3)
            raw = f"{pad}{core}{pad}"
            if core.lower() in used:
                # A case-insensitive duplicate must raise the service error.
                with self.assertRaises(FeesError) as ctx:
                    create_firm(profile, raw)
                self.assertEqual(ctx.exception.code, "DUPLICATE_FIRM_NAME")
                continue
            firm = create_firm(profile, raw)
            used.add(core.lower())
            created += 1
            # Name is stored trimmed.
            self.assertEqual(firm.name, core)
            # A created firm always has exactly one same-named group.
            groups = list(firm.groups.all())
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0].name, firm.name)
        # The invariant held across the whole profile.
        self.assertEqual(Firm.objects.filter(profile=profile).count(), created)
        for firm in Firm.objects.filter(profile=profile):
            self.assertEqual(firm.groups.count(), 1)
