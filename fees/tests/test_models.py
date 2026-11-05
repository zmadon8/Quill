"""Schema, constraint and cross-program tests for the Fee Register (T1.8).

These cover design section 2 and porting brief section 4: every table and its key columns exist, the
case-insensitive unique rules and the check constraints are enforced by the database, registering the
fees program leaves the diary untouched, and the fees and diary packages do not import each other
(R-SC-3).
"""
import datetime
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts import programs
from accounts.models import ROLE_EDITOR, ROLE_READER, Profile, ProfileMembership
from accounts.profiles import live_memberships
from accounts.suite import KEY_DIARY, KEY_FEES
from fees.models import (
    Allocation,
    BankAccount,
    FeesSettings,
    Firm,
    Group,
    Matter,
    Memo,
    NumberSequence,
    Payment,
    PeriodAdjustment,
    SavedView,
    StatsCache,
    WordTemplate,
)


def fees_profile(name="Ziyad-Fees"):
    return Profile.objects.create(program=KEY_FEES, name=name)


def a_firm(profile, name="Acme"):
    return Firm.objects.create(profile=profile, name=name)


def a_group(profile, firm, name="Main"):
    return Group.objects.create(profile=profile, firm=firm, name=name)


def a_matter(profile, firm, group, name="Case 1"):
    return Matter.objects.create(profile=profile, firm=firm, group=group, name=name)


def a_memo(profile, matter, **extra):
    data = dict(
        profile=profile,
        matter=matter,
        firm=matter.firm,
        group=matter.group,
        financial_year="2026-27",
        date=datetime.date(2026, 7, 1),
        addressee_line1="To whom it may concern",
    )
    data.update(extra)
    return Memo.objects.create(**data)


class SchemaTests(TestCase):
    """Field names, types and the money/date/boolean rules against brief section 4 (R-DATA-1, R-DATA-2)."""

    EXPECTED_TABLES = [
        Firm,
        Group,
        Matter,
        Memo,
        NumberSequence,
        BankAccount,
        Payment,
        Allocation,
        PeriodAdjustment,
        SavedView,
        FeesSettings,
        WordTemplate,
        StatsCache,
    ]

    def test_every_brief_table_exists(self):
        for model in self.EXPECTED_TABLES:
            self.assertTrue(model._meta.db_table, model.__name__)

    def test_money_fields_are_decimal_14_2(self):
        money_fields = {
            Memo: [
                "fees_per_appearance",
                "fees_per_conference",
                "fees_misc_drafting",
                "total_fees",
                "amount_paid",
                "amount_received",
                "amount_tds",
            ],
            Payment: ["amount", "tds_amount"],
            Allocation: ["amount", "tds_amount"],
        }
        for model, names in money_fields.items():
            for name in names:
                field = model._meta.get_field(name)
                self.assertEqual(field.max_digits, 14, f"{model.__name__}.{name}")
                self.assertEqual(field.decimal_places, 2, f"{model.__name__}.{name}")

    def test_dates_and_booleans(self):
        self.assertEqual(Memo._meta.get_field("date").get_internal_type(), "DateField")
        self.assertEqual(Payment._meta.get_field("date_of_payment").get_internal_type(), "DateField")
        for name in ("is_draft", "written_off"):
            self.assertEqual(Memo._meta.get_field(name).get_internal_type(), "BooleanField")

    def test_dropped_vestigial_columns_are_absent(self):
        matter_fields = {f.name for f in Matter._meta.get_fields()}
        self.assertNotIn("is_custom", matter_fields)
        memo_fields = {f.name for f in Memo._meta.get_fields()}
        self.assertNotIn("tds_rate", memo_fields)
        payment_fields = {f.name for f in Payment._meta.get_fields()}
        self.assertNotIn("memo_amount", payment_fields)
        self.assertNotIn("memo_id", payment_fields)
        self.assertNotIn("memo", payment_fields)

    def test_memo_denormalises_firm_and_group(self):
        # R-DATA-5: the memo carries firm and group copied from the matter.
        for name in ("firm", "group", "matter"):
            self.assertTrue(Memo._meta.get_field(name).is_relation, name)

    def test_settings_defaults(self):
        profile = fees_profile()
        settings = FeesSettings.objects.create(profile=profile)
        self.assertEqual(settings.default_tds_rate, Decimal("10"))
        self.assertTrue(settings.statistics_enabled)
        self.assertTrue(settings.dashboard_kpis_enabled)
        self.assertEqual(settings.export_owner_name, "Ziyad Madon")
        self.assertEqual(settings.memo_filename_pattern, "")
        self.assertEqual(settings.data_version, 0)
        self.assertEqual(settings.money_unit, "full")


class CaseInsensitiveUniquenessTests(TestCase):
    """R-DATA-3: names are unique per scope ignoring case, enforced by the database."""

    def setUp(self):
        self.profile = fees_profile()
        self.other = fees_profile("Second-Fees")

    def assert_duplicate(self, create):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                create()

    def test_firm_name_unique_per_profile_ignoring_case(self):
        a_firm(self.profile, "Acme")
        self.assert_duplicate(lambda: a_firm(self.profile, "acme"))
        # A different profile may reuse the name.
        a_firm(self.other, "ACME")

    def test_bank_account_name_unique_per_profile_ignoring_case(self):
        BankAccount.objects.create(profile=self.profile, name="HDFC")
        self.assert_duplicate(lambda: BankAccount.objects.create(profile=self.profile, name="hdfc"))
        BankAccount.objects.create(profile=self.other, name="hdfc")

    def test_group_name_unique_per_firm_ignoring_case(self):
        firm = a_firm(self.profile)
        a_group(self.profile, firm, "Litigation")
        self.assert_duplicate(lambda: a_group(self.profile, firm, "litigation"))
        # A different firm (even in the same profile) may reuse the name.
        other_firm = a_firm(self.profile, "Beta")
        a_group(self.profile, other_firm, "LITIGATION")

    def test_matter_name_unique_per_firm_ignoring_case(self):
        firm = a_firm(self.profile)
        group = a_group(self.profile, firm)
        a_matter(self.profile, firm, group, "Case Alpha")
        self.assert_duplicate(lambda: a_matter(self.profile, firm, group, "case alpha"))

    def test_saved_view_name_unique_per_profile_ignoring_case(self):
        SavedView.objects.create(profile=self.profile, name="By firm")
        self.assert_duplicate(lambda: SavedView.objects.create(profile=self.profile, name="by firm"))

    def test_memo_number_unique_per_profile_but_nulls_allowed(self):
        firm = a_firm(self.profile)
        group = a_group(self.profile, firm)
        matter = a_matter(self.profile, firm, group)
        a_memo(self.profile, matter, memo_number="2026-27/1", seq=1)
        self.assert_duplicate(lambda: a_memo(self.profile, matter, memo_number="2026-27/1", seq=2))
        # Two drafts (null number) are fine.
        a_memo(self.profile, matter, memo_number=None, is_draft=True)
        a_memo(self.profile, matter, memo_number=None, is_draft=True)
        # The same number is fine in another profile.
        f2 = a_firm(self.other)
        g2 = a_group(self.other, f2)
        m2 = a_matter(self.other, f2, g2)
        a_memo(self.other, m2, memo_number="2026-27/1", seq=1)

    def test_number_sequence_unique_per_profile_and_fy(self):
        NumberSequence.objects.create(profile=self.profile, financial_year="2026-27", last_seq=5)
        self.assert_duplicate(
            lambda: NumberSequence.objects.create(profile=self.profile, financial_year="2026-27")
        )
        NumberSequence.objects.create(profile=self.profile, financial_year="2027-28")

    def test_period_adjustment_unique_per_profile_fy_month(self):
        PeriodAdjustment.objects.create(profile=self.profile, financial_year="2026-27", month=4)
        self.assert_duplicate(
            lambda: PeriodAdjustment.objects.create(profile=self.profile, financial_year="2026-27", month=4)
        )
        PeriodAdjustment.objects.create(profile=self.profile, financial_year="2026-27", month=5)


class CheckConstraintTests(TestCase):
    """The database rejects negative stored totals and an out-of-range adjustment month."""

    def setUp(self):
        self.profile = fees_profile()
        self.firm = a_firm(self.profile)
        self.group = a_group(self.profile, self.firm)
        self.matter = a_matter(self.profile, self.firm, self.group)

    def assert_rejected(self, create):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                create()

    def test_negative_stored_totals_are_rejected(self):
        for field in ("total_fees", "amount_paid", "amount_received", "amount_tds"):
            with self.subTest(field=field):
                self.assert_rejected(lambda f=field: a_memo(self.profile, self.matter, **{f: Decimal("-1")}))

    def test_month_must_be_1_to_12(self):
        self.assert_rejected(
            lambda: PeriodAdjustment.objects.create(profile=self.profile, financial_year="2026-27", month=0)
        )
        self.assert_rejected(
            lambda: PeriodAdjustment.objects.create(profile=self.profile, financial_year="2026-27", month=13)
        )
        # The edges are allowed.
        PeriodAdjustment.objects.create(profile=self.profile, financial_year="2026-27", month=1)
        PeriodAdjustment.objects.create(profile=self.profile, financial_year="2026-27", month=12)


class ProtectDeletionTests(TestCase):
    """design section 2: a memo's matter and an allocation's memo are PROTECT."""

    def setUp(self):
        self.profile = fees_profile()
        self.firm = a_firm(self.profile)
        self.group = a_group(self.profile, self.firm)
        self.matter = a_matter(self.profile, self.firm, self.group)

    def test_matter_with_a_memo_cannot_be_deleted(self):
        a_memo(self.profile, self.matter, memo_number="2026-27/1", seq=1)
        from django.db.models import ProtectedError

        with self.assertRaises(ProtectedError):
            with transaction.atomic():
                self.matter.delete()

    def test_memo_with_an_allocation_cannot_be_deleted(self):
        memo = a_memo(self.profile, self.matter, memo_number="2026-27/1", seq=1)
        payment = Payment.objects.create(
            profile=self.profile, amount=Decimal("100"), date_of_payment=datetime.date(2026, 7, 2)
        )
        Allocation.objects.create(profile=self.profile, payment=payment, memo=memo, amount=Decimal("100"))
        from django.db.models import ProtectedError

        with self.assertRaises(ProtectedError):
            with transaction.atomic():
                memo.delete()


class ProgramRegistrationTests(TestCase):
    """Registering KEY_FEES (design 10.2 step C) is live once the app is ready and does not change the diary."""

    def test_fees_is_a_registered_program(self):
        self.assertIn(KEY_FEES, programs.program_keys())
        program = programs.get_program(KEY_FEES)
        self.assertIsNotNone(program)
        self.assertEqual(program.key, KEY_FEES)
        self.assertEqual(program.landing_url_name, "fees_dashboard")

    def test_fees_profile_models_are_lazy_labels(self):
        program = programs.get_program(KEY_FEES)
        labels = program.profile_models()
        self.assertIn("fees.Memo", labels)
        self.assertIn("fees.FeesSettings", labels)
        # The diary is unaffected.
        self.assertEqual(programs.get_program(KEY_DIARY).key, KEY_DIARY)

    def test_registration_did_not_call_reverse(self):
        # The landing URL name is stored as a string; no fees URL is resolvable yet.
        from django.urls import NoReverseMatch, reverse

        with self.assertRaises(NoReverseMatch):
            reverse("fees_dashboard")


class CrossProgramTests(TestCase):
    """design 10.4 step C: the two programs stay isolated once fees is registered."""

    def setUp(self):
        from django.contrib.auth import get_user_model

        self.User = get_user_model()
        self.diary_profile = Profile.objects.create(program=KEY_DIARY, name="Chambers")
        self.fees_profile = Profile.objects.create(program=KEY_FEES, name="Chambers")
        self.user = self.User.objects.create_user(username="ziyad", password="correct-horse-9")
        ProfileMembership.objects.create(user=self.user, profile=self.diary_profile, role=ROLE_EDITOR)
        ProfileMembership.objects.create(user=self.user, profile=self.fees_profile, role=ROLE_READER)

    def test_profile_names_are_unique_per_program_not_across_them(self):
        # The same name is allowed in two different programs (done in setUp without error).
        self.assertEqual(
            Profile.objects.filter(name="Chambers", deleted_at__isnull=True).count(), 2
        )

    def test_a_fees_profile_never_shows_in_the_diary_profile_switcher(self):
        diary = live_memberships(self.user, KEY_DIARY)
        self.assertEqual([m.profile_id for m in diary], [self.diary_profile.pk])
        fees = live_memberships(self.user, KEY_FEES)
        self.assertEqual([m.profile_id for m in fees], [self.fees_profile.pk])

    def test_a_user_with_both_programs_is_offered_both(self):
        from accounts import landing

        self.assertEqual(sorted(landing.programs_for(self.user)), sorted([KEY_DIARY, KEY_FEES]))

    def test_clearing_a_fees_profile_leaves_diary_data_untouched(self):
        from accounts import clear
        from diary.models import Subject

        admin = self.User.objects.create_user(username="boss", password="x", is_superuser=True)
        Subject.objects.create(profile=self.diary_profile, name="Keep me")
        # Since T1.9 the fee models are in the backups registry, so clearing a fees profile deletes that
        # profile's fee rows. The diary profile's data and the fees profile row itself stay intact.
        Firm.objects.create(profile=self.fees_profile, name="Acme LLP")
        counts = clear.clear_profile(self.fees_profile, admin)
        self.assertEqual(counts.get("fees.Firm"), 1)
        self.assertEqual(Firm.objects.filter(profile=self.fees_profile).count(), 0)
        self.assertEqual(Subject.objects.filter(profile=self.diary_profile).count(), 1)
        self.assertTrue(Profile.objects.filter(pk=self.fees_profile.pk).exists())
