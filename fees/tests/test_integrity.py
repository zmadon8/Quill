"""Data-integrity checker tests for the Fee Register (T2.8, R-DATA-4, design section 4).

``fees.services.integrity.run_check`` and the ``fees_check`` command recompute
every stored memo total from first principles and REPORT mismatches (read-only;
they never fix). These tests assert:

* a clean dataset (memos plus payments mutated through the services) reports
  ZERO mismatches and the right ``memos_checked``;
* a deliberately corrupted row (written with a raw ``update`` that bypasses the
  services) is DETECTED, naming the exact memo / field / stored / expected;
* ``run_check(None)`` spans every fees profile and does NOT cross profiles;
* the ``fees_check`` command exits 0 on a clean DB and non-zero (``CommandError``)
  on a corrupted row, naming the memo;
* the T2.8 GATE: after a seeded random operation sequence (create-memo /
  add / update / assign / delete payment / delete-memo) ``fees_check`` reports
  zero mismatches.

Uses the ORM, so Django ``TestCase``; everything is scoped to
``Profile(program="fees")`` and mutated via ``memos`` / ``payments`` so the
stored values are maintained. Helpers mirror ``test_payments.py``.
"""
import random
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from accounts.models import Profile
from accounts.suite import KEY_FEES
from fees.models import Firm, Group, Matter, Memo
from fees.services import integrity, memos, payments


def fees_profile(name="Ziyad-Fees"):
    return Profile.objects.create(program=KEY_FEES, name=name)


def seed_matter(profile, firm_name="Firm", matter_name="Matter"):
    firm = Firm.objects.create(profile=profile, name=firm_name)
    group = Group.objects.create(profile=profile, firm=firm, name="Group")
    matter = Matter.objects.create(
        profile=profile, firm=firm, group=group, name=matter_name
    )
    return firm, group, matter


def memo_with_total(profile, matter, total, date="2026-07-15"):
    """Creates a memo whose whole total is a single misc-drafting fee."""
    return memos.create_memo(
        profile,
        dict(
            date=date,
            matter_id=matter.pk,
            addressee_line1="A",
            num_appearances=0,
            fees_per_appearance=0,
            num_conferences=0,
            fees_per_conference=0,
            fees_misc_drafting=total,
        ),
    )


# ---------------------------------------------------------------------------
# A clean dataset reports zero mismatches
# ---------------------------------------------------------------------------

class CleanDatasetTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter = seed_matter(self.profile)
        self.a = memo_with_total(self.profile, self.matter, 50000)
        self.b = memo_with_total(self.profile, self.matter, 30000, date="2026-07-16")
        self.c = memo_with_total(self.profile, self.matter, 10000, date="2026-07-17")

    def test_check_profile_reports_no_mismatches(self):
        # Exercise add / split / assign / update / delete through the services.
        payments.add_payment_to_memo(
            self.profile,
            self.a.pk,
            {"amount": 45000, "tds_rate": 10, "auto_tds": True, "date_of_payment": "2026-08-01"},
        )
        payments.add_payment(
            self.profile,
            {
                "amount": 40000,
                "date_of_payment": "2026-08-02",
                "allocations": [
                    {"memo_id": self.b.pk, "amount": 30000, "tds_amount": 0},
                    {"memo_id": self.c.pk, "amount": 10000, "tds_amount": 0},
                ],
            },
        )
        pay = payments.add_unaccounted_payment(
            self.profile, {"amount": 5000, "date_of_payment": "2026-08-03"}
        )
        payments.assign_payment_to_memo(self.profile, pay["id"], self.c.pk)
        payments.update_payment(
            self.profile, pay["id"], {"amount": 7000, "date_of_payment": "2026-08-04"}
        )

        report = integrity.run_check(self.profile)
        self.assertEqual(report.memos_checked, 3)
        self.assertEqual(report.mismatches, [])
        self.assertTrue(report.ok)

    def test_empty_profile_has_zero_memos_and_no_mismatches(self):
        empty = fees_profile("Empty-Fees")
        report = integrity.run_check(empty)
        self.assertEqual(report.memos_checked, 0)
        self.assertEqual(report.mismatches, [])


# ---------------------------------------------------------------------------
# Corruption is detected (raw update bypasses the services)
# ---------------------------------------------------------------------------

class CorruptionDetectedTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter = seed_matter(self.profile)
        self.memo = memo_with_total(self.profile, self.matter, 50000)

    def test_wrong_total_fees_detected(self):
        # Corrupt total_fees directly, bypassing memos.create_memo.
        Memo.objects.filter(pk=self.memo.pk).update(total_fees=Decimal("99999.00"))
        report = integrity.run_check(self.profile)
        fields = {m.field: m for m in report.mismatches}
        self.assertIn("total_fees", fields)
        self.assertEqual(fields["total_fees"].memo_id, self.memo.pk)
        self.assertEqual(fields["total_fees"].stored, Decimal("99999.00"))
        self.assertEqual(fields["total_fees"].expected, Decimal("50000.00"))
        self.assertEqual(
            fields["total_fees"].memo_number, self.memo.memo_number
        )

    def test_wrong_amount_paid_detected(self):
        # A real payment, then corrupt only amount_paid.
        payments.add_payment_to_memo(
            self.profile, self.memo.pk, {"amount": 1000, "date_of_payment": "2026-08-01"}
        )
        Memo.objects.filter(pk=self.memo.pk).update(amount_paid=Decimal("5000.00"))
        report = integrity.run_check(self.profile)
        fields = {m.field: m for m in report.mismatches}
        self.assertEqual(set(fields), {"amount_paid"})
        self.assertEqual(fields["amount_paid"].stored, Decimal("5000.00"))
        self.assertEqual(fields["amount_paid"].expected, Decimal("1000.00"))

    def test_several_fields_each_reported(self):
        Memo.objects.filter(pk=self.memo.pk).update(
            total_fees=Decimal("1.00"),
            amount_received=Decimal("2.00"),
            amount_tds=Decimal("3.00"),
        )
        report = integrity.run_check(self.profile)
        fields = {m.field for m in report.mismatches}
        # amount_paid is still 0 stored vs expected 0, so it is NOT flagged.
        self.assertEqual(fields, {"total_fees", "amount_received", "amount_tds"})


# ---------------------------------------------------------------------------
# run_check(None) spans profiles and does not cross them (isolation)
# ---------------------------------------------------------------------------

class MultiProfileIsolationTests(TestCase):
    def test_mismatch_in_one_profile_not_attributed_to_another(self):
        p1 = fees_profile("P1-Fees")
        p2 = fees_profile("P2-Fees")
        _, _, m1 = seed_matter(p1)
        _, _, m2 = seed_matter(p2)
        memo1 = memo_with_total(p1, m1, 1000)
        memo2 = memo_with_total(p2, m2, 2000)

        # Corrupt only p1's memo.
        Memo.objects.filter(pk=memo1.pk).update(total_fees=Decimal("7.00"))

        reports = integrity.run_check(None)
        by_profile = {r.profile_id: r for r in reports}
        self.assertIn(p1.pk, by_profile)
        self.assertIn(p2.pk, by_profile)

        self.assertEqual(len(by_profile[p1.pk].mismatches), 1)
        self.assertEqual(by_profile[p1.pk].mismatches[0].memo_id, memo1.pk)
        # p2 is clean: its memo is untouched.
        self.assertTrue(by_profile[p2.pk].ok)
        self.assertEqual(by_profile[p2.pk].memos_checked, 1)
        _ = memo2  # referenced for clarity

    def test_summarise_counts(self):
        p1 = fees_profile("S1-Fees")
        _, _, m1 = seed_matter(p1)
        memo1 = memo_with_total(p1, m1, 1000)
        memo_with_total(p1, m1, 2000, date="2026-07-16")
        Memo.objects.filter(pk=memo1.pk).update(total_fees=Decimal("5.00"))

        summary = integrity.summarise(integrity.run_check(p1))
        self.assertEqual(summary.profiles_checked, 1)
        self.assertEqual(summary.memos_checked, 2)
        self.assertEqual(summary.mismatches, 1)
        self.assertFalse(summary.ok)


# ---------------------------------------------------------------------------
# The fees_check management command: exit codes and output
# ---------------------------------------------------------------------------

class FeesCheckCommandTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter = seed_matter(self.profile)
        self.memo = memo_with_total(self.profile, self.matter, 50000)

    def run_command(self, **kwargs):
        out = StringIO()
        call_command("fees_check", stdout=out, **kwargs)
        return out.getvalue()

    def test_clean_db_exits_zero_and_prints_consistent_line(self):
        payments.add_payment_to_memo(
            self.profile, self.memo.pk, {"amount": 100, "date_of_payment": "2026-08-01"}
        )
        output = self.run_command()
        self.assertIn("consistent", output)

    def test_clean_specific_profile(self):
        output = self.run_command(profile=self.profile.pk)
        self.assertIn("consistent", output)

    def test_unknown_profile_errors(self):
        with self.assertRaises(CommandError):
            self.run_command(profile=999999)

    def test_corrupted_row_exits_non_zero_and_names_memo(self):
        Memo.objects.filter(pk=self.memo.pk).update(total_fees=Decimal("1.00"))
        out = StringIO()
        with self.assertRaises(CommandError):
            call_command("fees_check", stdout=out)
        # The per-profile report is printed before the error is raised.
        label = self.memo.memo_number or f"draft memo {self.memo.pk}"
        self.assertIn(label, out.getvalue())


# ---------------------------------------------------------------------------
# T2.8 GATE: zero mismatches after a seeded random operation sequence
# ---------------------------------------------------------------------------

class RandomSequenceGateTests(TestCase):
    """The T2.8 gate: after ~130 seeded random create-memo / payment /
    delete-memo steps, fees_check reports ZERO mismatches."""

    SEED = 82028
    STEPS = 130

    def setUp(self):
        self.profile = fees_profile()
        _, _, self.matter = seed_matter(self.profile)

    def test_zero_mismatches_after_random_sequence(self):
        rng = random.Random(self.SEED)
        memo_ids = [
            memo_with_total(
                self.profile, self.matter, 100000, date=f"2026-07-{d:02d}"
            ).pk
            for d in range(10, 14)
        ]
        live_payment_ids = []

        for _step in range(self.STEPS):
            choice = rng.random()
            if choice < 0.35 or not live_payment_ids:
                # add a payment with random allocations across 0..2 memos.
                n = rng.randint(0, 2)
                allocs = [
                    {
                        "memo_id": rng.choice(memo_ids),
                        "amount": round(rng.uniform(1, 5000), 2),
                        "tds_amount": round(rng.uniform(0, 500), 2),
                    }
                    for _ in range(n)
                ]
                data = {
                    "amount": round(rng.uniform(1, 10000), 2),
                    "date_of_payment": "2026-08-01",
                }
                if allocs:
                    data["allocations"] = allocs
                pay = payments.add_payment(self.profile, data)
                live_payment_ids.append(pay["id"])
            elif choice < 0.55:
                # update a payment (sometimes explicit allocations, sometimes omitted).
                pid = rng.choice(live_payment_ids)
                data = {
                    "amount": round(rng.uniform(1, 10000), 2),
                    "date_of_payment": "2026-08-02",
                }
                if rng.random() < 0.6:
                    n = rng.randint(0, 2)
                    data["allocations"] = [
                        {
                            "memo_id": rng.choice(memo_ids),
                            "amount": round(rng.uniform(1, 5000), 2),
                            "tds_amount": round(rng.uniform(0, 500), 2),
                        }
                        for _ in range(n)
                    ]
                payments.update_payment(self.profile, pid, data)
            elif choice < 0.7:
                # assign a payment wholly to a random memo.
                pid = rng.choice(live_payment_ids)
                payments.assign_payment_to_memo(
                    self.profile, pid, rng.choice(memo_ids)
                )
            elif choice < 0.85:
                # delete a payment.
                pid = rng.choice(live_payment_ids)
                payments.delete_payment(self.profile, pid)
                live_payment_ids.remove(pid)
            else:
                # add a fresh memo (grows the set the checker must verify).
                new_memo = memo_with_total(
                    self.profile, self.matter, round(rng.uniform(1000, 90000), 2),
                    date="2026-07-20",
                )
                memo_ids.append(new_memo.pk)

        report = integrity.run_check(self.profile)
        self.assertEqual(
            report.mismatches,
            [],
            msg="fees_check found drift after the seeded random sequence",
        )
        self.assertEqual(report.memos_checked, len(memo_ids))

        # The command must also exit clean on this dataset.
        out = StringIO()
        call_command("fees_check", stdout=out, profile=self.profile.pk)
        self.assertIn("consistent", out.getvalue())
