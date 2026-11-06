"""Memo numbering tests for the Fee Register (T2.3, R-NUM-1 to R-NUM-5, brief 5.6).

Ports ``memoNumberService.test.ts`` (auto numbers increment per FY, a new FY
restarts at ``/1``, preview is read-only and does not create a row, deleted
numbers are never reused) and the custom-number rules ported from
``assignCustomMemoNumber`` (R-NUM-3; owner decision 5 replaced the Q8 refusal of auto-shaped numbers). The ``memoNumber`` property
test becomes a seeded ``random.Random`` loop (U8: Hypothesis not approved), 200
cases, asserting the FY prefix always matches ``derive_financial_year`` and that
numbers within an FY are strictly increasing and never reused.

Concurrency (R-NUM-1) is covered two ways. Everywhere: a sequential-invariant
test that N calls on one ``(profile, FY)`` yield ``1..N`` with no gaps or dupes.
On PostgreSQL only (``connection.vendor``): a threaded ``TransactionTestCase``
with separate connections that asserts two concurrent ``next_number`` calls on the
same ``(profile, FY)`` never return the same sequence (mirrors the PostgreSQL-only
pattern in ``backups/tests/test_heavy.py``).

These tests need the database (the ORM), so ``TestCase`` /
``TransactionTestCase`` are used.
"""
import datetime
import random
import threading
import unittest

from django.db import connection, connections
from django.test import TestCase, TransactionTestCase

from accounts.models import Profile
from accounts.suite import KEY_FEES
from fees.errors import FeesError
from fees.models import Memo, NumberSequence
from fees.services.financial_year import derive_financial_year
from fees.services.memo_numbers import (
    claim_auto_number,
    find_memo_id_by_number,
    is_custom_number,
    next_number,
    parse_auto_number,
    preview_next_number,
    raise_counter,
    resolve_number,
    validate_custom_number,
)

POSTGRES_ONLY = unittest.skipUnless(
    connection.vendor == "postgresql",
    "True concurrency needs the PostgreSQL row lock; skipped on other databases.",
)


def fees_profile(name="Ziyad-Fees"):
    return Profile.objects.create(program=KEY_FEES, name=name)


def _firm_group_matter(profile):
    from fees.models import Firm, Group, Matter

    firm = Firm.objects.create(profile=profile, name="Acme")
    group = Group.objects.create(profile=profile, firm=firm, name="Main")
    matter = Matter.objects.create(profile=profile, firm=firm, group=group, name="Case 1")
    return firm, group, matter


def make_memo(profile, memo_number=None, seq=0, is_draft=False, **extra):
    firm, group, matter = _firm_group_matter(profile)
    data = dict(
        profile=profile,
        matter=matter,
        firm=firm,
        group=group,
        financial_year="2026-27",
        date=datetime.date(2026, 7, 1),
        addressee_line1="To whom it may concern",
        memo_number=memo_number,
        seq=seq,
        is_draft=is_draft,
    )
    data.update(extra)
    return Memo.objects.create(**data)


class NextNumberTests(TestCase):
    """Auto numbers: ``memoNumberService.test.ts`` generateMemoNumber cases (R-NUM-1)."""

    def setUp(self):
        self.profile = fees_profile()

    def test_first_memo_of_a_new_fy_gets_sequence_1(self):
        self.assertEqual(next_number(self.profile, "2026-07-15"), "2026-27/1")

    def test_second_memo_of_the_same_fy_gets_sequence_2(self):
        next_number(self.profile, "2026-07-15")
        self.assertEqual(next_number(self.profile, "2026-08-01"), "2026-27/2")

    def test_counter_restarts_at_1_for_a_new_financial_year(self):
        next_number(self.profile, "2026-07-15")
        next_number(self.profile, "2026-09-01")
        self.assertEqual(next_number(self.profile, "2027-04-01"), "2027-28/1")

    def test_sequences_are_independent_across_financial_years(self):
        self.assertEqual(next_number(self.profile, "2026-07-15"), "2026-27/1")
        self.assertEqual(next_number(self.profile, "2027-05-01"), "2027-28/1")
        self.assertEqual(next_number(self.profile, "2026-11-01"), "2026-27/2")
        self.assertEqual(next_number(self.profile, "2027-06-01"), "2027-28/2")

    def test_all_generated_numbers_are_unique(self):
        dates = [
            "2026-04-01",
            "2026-07-15",
            "2026-12-31",
            "2027-01-01",
            "2027-03-31",
            "2027-04-01",
            "2027-09-01",
        ]
        numbers = [next_number(self.profile, d) for d in dates]
        self.assertEqual(len(set(numbers)), len(numbers))

    def test_sequence_is_never_decremented_and_numbers_are_not_reused(self):
        self.assertEqual(next_number(self.profile, "2026-07-01"), "2026-27/1")
        self.assertEqual(next_number(self.profile, "2026-08-01"), "2026-27/2")
        self.assertEqual(next_number(self.profile, "2026-09-01"), "2026-27/3")
        row = NumberSequence.objects.get(profile=self.profile, financial_year="2026-27")
        self.assertEqual(row.last_seq, 3)
        # Even if a memo were deleted, the counter continues: the next is /4.
        self.assertEqual(next_number(self.profile, "2026-10-01"), "2026-27/4")

    def test_january_date_maps_to_prior_year_fy(self):
        self.assertEqual(next_number(self.profile, "2027-01-15"), "2026-27/1")

    def test_accepts_a_date_object_and_a_ready_fy_label(self):
        self.assertEqual(next_number(self.profile, datetime.date(2026, 7, 15)), "2026-27/1")
        # A ready "YYYY-YY" label is passed through verbatim (no re-derivation).
        self.assertEqual(next_number(self.profile, "2026-27"), "2026-27/2")

    def test_numbers_are_scoped_per_profile(self):
        other = fees_profile("Other-Fees")
        self.assertEqual(next_number(self.profile, "2026-07-15"), "2026-27/1")
        self.assertEqual(next_number(other, "2026-07-15"), "2026-27/1")
        self.assertEqual(next_number(self.profile, "2026-07-15"), "2026-27/2")


class PreviewNextNumberTests(TestCase):
    """Preview is read-only and never creates or advances a row (R-NUM-4)."""

    def setUp(self):
        self.profile = fees_profile()

    def test_preview_with_no_row_is_slash_1_and_creates_nothing(self):
        self.assertEqual(preview_next_number(self.profile, "2026-07-15"), "2026-27/1")
        self.assertFalse(
            NumberSequence.objects.filter(
                profile=self.profile, financial_year="2026-27"
            ).exists()
        )

    def test_preview_reflects_last_seq_plus_one_without_incrementing(self):
        next_number(self.profile, "2026-07-15")
        next_number(self.profile, "2026-08-01")
        self.assertEqual(preview_next_number(self.profile, "2026-09-01"), "2026-27/3")
        # Preview did not advance the counter.
        self.assertEqual(preview_next_number(self.profile, "2026-09-01"), "2026-27/3")
        row = NumberSequence.objects.get(profile=self.profile, financial_year="2026-27")
        self.assertEqual(row.last_seq, 2)

    def test_preview_accepts_a_ready_fy_label(self):
        self.assertEqual(preview_next_number(self.profile, "2026-27"), "2026-27/1")


class ValidateCustomNumberTests(TestCase):
    """Custom numbers (R-NUM-3 + brief 15 Q8), ported from assignCustomMemoNumber."""

    def setUp(self):
        self.profile = fees_profile()

    def test_blank_is_rejected(self):
        with self.assertRaises(FeesError) as ctx:
            validate_custom_number(self.profile, "   ")
        self.assertEqual(ctx.exception.code, "INVALID_MEMO")
        self.assertEqual(ctx.exception.status, 422)

    def test_none_is_rejected(self):
        with self.assertRaises(FeesError) as ctx:
            validate_custom_number(self.profile, None)
        self.assertEqual(ctx.exception.code, "INVALID_MEMO")

    def test_over_100_chars_is_rejected(self):
        with self.assertRaises(FeesError) as ctx:
            validate_custom_number(self.profile, "x" * 101)
        self.assertEqual(ctx.exception.code, "INVALID_MEMO")
        self.assertIn("100", ctx.exception.message)

    def test_exactly_100_chars_is_allowed(self):
        value = "x" * 100
        self.assertEqual(validate_custom_number(self.profile, value), value)

    def test_value_shaped_like_an_auto_number_is_no_longer_refused_here(self):
        # Owner decision 5: callers route auto-shaped text to claim_auto_number first;
        # the forced-Custom import path may still store it as custom text.
        self.assertEqual(validate_custom_number(self.profile, "2022-23/5"), "2022-23/5")

    def test_auto_shaped_custom_text_is_still_unique(self):
        make_memo(self.profile, memo_number="2022-23/5")
        with self.assertRaises(FeesError):
            validate_custom_number(self.profile, "2022-23/5")

    def test_duplicate_on_another_memo_is_rejected(self):
        make_memo(self.profile, memo_number="CUSTOM-1")
        with self.assertRaises(FeesError) as ctx:
            validate_custom_number(self.profile, "CUSTOM-1")
        self.assertEqual(ctx.exception.code, "INVALID_MEMO")
        self.assertIn("already in use", ctx.exception.message)

    def test_valid_unique_value_is_returned_trimmed(self):
        self.assertEqual(validate_custom_number(self.profile, "  INV-42  "), "INV-42")

    def test_uniqueness_is_per_profile(self):
        other = fees_profile("Other-Fees")
        make_memo(other, memo_number="SHARED-1")
        # The same custom number is free in a different profile.
        self.assertEqual(validate_custom_number(self.profile, "SHARED-1"), "SHARED-1")

    def test_exclude_memo_id_lets_a_memo_keep_its_own_number(self):
        memo = make_memo(self.profile, memo_number="KEEP-1")
        # Without exclusion the memo clashes with itself.
        with self.assertRaises(FeesError):
            validate_custom_number(self.profile, "KEEP-1")
        # Excluding it lets the edit keep the number.
        self.assertEqual(
            validate_custom_number(self.profile, "KEEP-1", exclude_memo_id=memo.pk),
            "KEEP-1",
        )


class KeptAutoNumberTests(TestCase):
    """Owner decision 5, Option A: an auto-shaped number is accepted as a real auto number."""

    def setUp(self):
        self.profile = fees_profile()

    def counter(self, fy="2026-27"):
        row = NumberSequence.objects.filter(profile=self.profile, financial_year=fy).first()
        return row.last_seq if row else None

    def test_parse_auto_number(self):
        self.assertEqual(parse_auto_number(" 2026-27/12 "), ("2026-27", 12))
        for text in ("INV-1", "2026-27", "2026-27/", "2026-27/x", "26-27/1", "2026-27/1/2", None, ""):
            self.assertIsNone(parse_auto_number(text), text)

    def test_kept_number_is_stored_as_auto_and_sets_the_counter(self):
        self.assertEqual(claim_auto_number(self.profile, "2026-27/7", "2026-27"), ("2026-27/7", "2026-27", 7))
        self.assertEqual(self.counter(), 7)

    def test_next_number_is_the_highest_plus_one_and_gaps_stay(self):
        claim_auto_number(self.profile, "2026-27/7", "2026-27")
        self.assertEqual(next_number(self.profile, "2026-07-15"), "2026-27/8")
        # 1 to 6 are never handed out.
        self.assertEqual(next_number(self.profile, "2026-07-16"), "2026-27/9")

    def test_a_lower_number_does_not_lower_the_counter(self):
        claim_auto_number(self.profile, "2026-27/9", "2026-27")
        claim_auto_number(self.profile, "2026-27/3", "2026-27")
        self.assertEqual(self.counter(), 9)
        self.assertEqual(next_number(self.profile, "2026-07-15"), "2026-27/10")

    def test_counter_is_raised_from_an_existing_row_only_when_higher(self):
        next_number(self.profile, "2026-07-15")
        next_number(self.profile, "2026-07-15")
        raise_counter(self.profile, "2026-27", 1)
        self.assertEqual(self.counter(), 2)
        raise_counter(self.profile, "2026-27", 40)
        self.assertEqual(self.counter(), 40)

    def test_financial_year_mismatch_is_refused(self):
        with self.assertRaises(FeesError) as ctx:
            claim_auto_number(self.profile, "2025-26/4", "2026-27")
        self.assertEqual(ctx.exception.code, "INVALID_MEMO")
        self.assertIn("2025-26", ctx.exception.message)
        self.assertIsNone(self.counter("2025-26"))

    def test_a_number_already_used_is_refused(self):
        make_memo(self.profile, memo_number="2026-27/4", seq=4)
        with self.assertRaises(FeesError) as ctx:
            claim_auto_number(self.profile, "2026-27/4", "2026-27")
        self.assertIn("already in use", ctx.exception.message)

    def test_a_memo_may_claim_its_own_number_when_excluded(self):
        memo = make_memo(self.profile, memo_number="2026-27/4", seq=4)
        self.assertEqual(
            claim_auto_number(self.profile, "2026-27/4", "2026-27", exclude_memo_id=memo.pk)[2], 4
        )

    def test_non_canonical_sequences_are_refused(self):
        for text in ("2026-27/0", "2026-27/007", "2026-27/1000000000"):
            with self.assertRaises(FeesError, msg=text):
                claim_auto_number(self.profile, text, "2026-27")

    def test_resolve_number_routes_auto_shape_and_custom_text(self):
        self.assertEqual(resolve_number(self.profile, "2026-27/5", "2026-27"), ("2026-27/5", "2026-27", 5))
        self.assertEqual(resolve_number(self.profile, " INV-5 ", "2026-27"), ("INV-5", "2026-27", 0))
        self.assertEqual(self.counter(), 5)  # the custom text did not move it

    def test_next_number_steps_past_a_custom_text_of_the_same_shape(self):
        make_memo(self.profile, memo_number="2026-27/1", seq=0)
        self.assertEqual(next_number(self.profile, "2026-07-15"), "2026-27/2")
        self.assertEqual(self.counter(), 2)


class IsCustomNumberTests(TestCase):
    """The brief-5.6 predicate: finalised, numbered, seq == 0."""

    def test_true_only_when_finalised_numbered_and_seq_zero(self):
        self.assertTrue(
            is_custom_number({"is_draft": False, "memo_number": "X-1", "seq": 0})
        )

    def test_false_for_a_draft(self):
        self.assertFalse(
            is_custom_number({"is_draft": True, "memo_number": "X-1", "seq": 0})
        )

    def test_false_without_a_number(self):
        self.assertFalse(
            is_custom_number({"is_draft": False, "memo_number": None, "seq": 0})
        )

    def test_false_for_an_auto_number_with_nonzero_seq(self):
        self.assertFalse(
            is_custom_number({"is_draft": False, "memo_number": "2026-27/3", "seq": 3})
        )

    def test_accepts_a_model_instance(self):
        profile = fees_profile()
        memo = make_memo(profile, memo_number="CUST-9", seq=0, is_draft=False)
        self.assertTrue(is_custom_number(memo))


class FindMemoIdByNumberTests(TestCase):
    """Case-insensitive exact match on trimmed input, non-drafts only (R-NUM-5)."""

    def setUp(self):
        self.profile = fees_profile()

    def test_case_insensitive_trimmed_match(self):
        memo = make_memo(self.profile, memo_number="2026-27/7", seq=7)
        self.assertEqual(find_memo_id_by_number(self.profile, "  2026-27/7  "), memo.pk)

    def test_blank_returns_none(self):
        self.assertIsNone(find_memo_id_by_number(self.profile, "   "))
        self.assertIsNone(find_memo_id_by_number(self.profile, None))

    def test_drafts_are_excluded(self):
        make_memo(self.profile, memo_number="DRAFT-1", is_draft=True)
        self.assertIsNone(find_memo_id_by_number(self.profile, "DRAFT-1"))

    def test_scoped_to_the_profile(self):
        other = fees_profile("Other-Fees")
        make_memo(other, memo_number="2026-27/1", seq=1)
        self.assertIsNone(find_memo_id_by_number(self.profile, "2026-27/1"))


class SequentialInvariantTests(TestCase):
    """R-NUM-1 everywhere: N sequential calls yield 1..N with no gaps or dupes."""

    def test_n_calls_yield_1_to_n_in_order(self):
        profile = fees_profile()
        n = 50
        seqs = []
        for _ in range(n):
            number = next_number(profile, "2026-07-15")
            fy, seq = number.split("/")
            self.assertEqual(fy, "2026-27")
            seqs.append(int(seq))
        self.assertEqual(seqs, list(range(1, n + 1)))
        self.assertEqual(len(set(seqs)), n)


class NumberPropertyTests(TestCase):
    """Seeded loop port of ``memoNumber.property.test.ts`` (U8: no Hypothesis, 200 cases)."""

    SEED = 20263
    RUNS = 200

    def test_prefix_always_matches_derive_fy_and_seq_increases_per_fy(self):
        profile = fees_profile()
        rng = random.Random(self.SEED)
        counters = {}
        seen = set()
        for _ in range(self.RUNS):
            d = datetime.date(
                rng.randint(2020, 2035), rng.randint(1, 12), rng.randint(1, 28)
            )
            expected_fy = derive_financial_year(d)
            number = next_number(profile, d)
            fy, seq_text = number.rsplit("/", 1)
            seq = int(seq_text)
            # The FY prefix always matches derive_financial_year.
            self.assertEqual(fy, expected_fy)
            # Numbers within an FY are strictly increasing and start at 1.
            expected_seq = counters.get(fy, 0) + 1
            self.assertEqual(seq, expected_seq)
            counters[fy] = seq
            # Never reused across the whole run.
            self.assertNotIn(number, seen)
            seen.add(number)


@POSTGRES_ONLY
class ConcurrencyTests(TransactionTestCase):
    """R-NUM-1 real concurrency: two threads never get the same sequence (PostgreSQL only).

    A ``TransactionTestCase`` is used so the rows are really committed across the
    separate thread connections, mirroring ``backups/tests/test_heavy.py``.
    """

    def test_two_concurrent_allocations_never_collide(self):
        profile = fees_profile()
        fy_date = "2026-07-15"
        workers = 8
        results = []
        errors = []
        start = threading.Barrier(workers)

        def worker():
            try:
                start.wait()
                number = next_number(profile, fy_date)
            except Exception as exc:  # noqa: BLE001 - surfaced to the assertions
                errors.append(exc)
                return
            finally:
                connections.close_all()
            results.append(number)

        threads = [threading.Thread(target=worker) for _ in range(workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"worker(s) raised: {errors}")
        self.assertEqual(len(results), workers)
        # Every allocated number is distinct: no two threads got the same seq.
        self.assertEqual(len(set(results)), workers)
        seqs = sorted(int(r.split("/")[1]) for r in results)
        self.assertEqual(seqs, list(range(1, workers + 1)))
        row = NumberSequence.objects.get(profile=profile, financial_year="2026-27")
        self.assertEqual(row.last_seq, workers)


@POSTGRES_ONLY
class KeptNumberConcurrencyTests(TransactionTestCase):
    """Concurrent raise_counter calls end at the maximum and next_number never collides (PostgreSQL only)."""

    def test_concurrent_raises_and_allocations_stay_consistent(self):
        profile = fees_profile()
        raise_counter(profile, "2026-27", 1)
        values = [5, 50, 20, 35, 8, 41]
        allocated = []
        errors = []
        start = threading.Barrier(len(values) + 2)

        def raiser(value):
            try:
                start.wait()
                raise_counter(profile, "2026-27", value)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                connections.close_all()

        def allocator():
            try:
                start.wait()
                allocated.append(next_number(profile, "2026-27"))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=raiser, args=(v,)) for v in values]
        threads += [threading.Thread(target=allocator) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(set(allocated)), 2)
        row = NumberSequence.objects.get(profile=profile, financial_year="2026-27")
        self.assertGreaterEqual(row.last_seq, 50)
