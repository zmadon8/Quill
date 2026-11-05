"""Tests for the database-backed statistics cache (T3.6, R-NFR-3, R-NFR-10).

Covers the ``fees.services.stats_cache.get_or_compute`` read-through cache and
its interaction with ``memos.touch``:

* HIT: a second call with the same parameters returns the cached payload WITHOUT
  calling ``compute`` again (asserted with a call counter);
* MISS: the first call (and a call with different parameters) runs ``compute``;
* invalidation on every write type: a memo create, a payment, a firm create and
  a settings update each call ``touch`` and must clear the cache so the next
  ``get_or_compute`` recomputes;
* current-month / today date key: a ``today_sensitive=True`` row stores
  ``valid_on = today`` and is a MISS once "today" moves on (the module reads the
  date through the patchable ``_today`` helper);
* 200-entry prune: writing more than 200 distinct params for one profile at the
  same ``data_version`` keeps at most 200 rows, evicting the oldest;
* profile isolation: one profile's cached rows never satisfy another profile's
  ``get_or_compute``.

Scoping mirrors ``test_outstanding.py``: a ``Profile(program=KEY_FEES)`` with a
firm / group / matter, memos via ``memos.create_memo`` and payments via
``payments.add_payment_to_memo`` so the stored columns are maintained.
"""
import datetime

from django.test import TestCase

from accounts.models import Profile
from accounts.suite import KEY_FEES
from fees.models import Firm, Group, Matter, StatsCache
from fees.services import firms, memos, payments, settings, stats_cache


def fees_profile(name="Ziyad-Fees"):
    return Profile.objects.create(program=KEY_FEES, name=name)


def seed_firm(profile, firm_name="Firm", group_name="P"):
    firm = Firm.objects.create(profile=profile, name=firm_name)
    group = Group.objects.create(profile=profile, firm=firm, name=group_name)
    return firm, group


def seed_matter(profile, firm, group, matter_name="Matter"):
    return Matter.objects.create(
        profile=profile, firm=firm, group=group, name=matter_name
    )


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


class Counter:
    """A zero-argument callable that counts its calls and returns a fixed payload."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.payload


# ---------------------------------------------------------------------------
# Hit / miss
# ---------------------------------------------------------------------------

class HitMissTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()

    def test_miss_then_hit_calls_compute_once(self):
        compute = Counter({"value": 42})
        params = {"year": "2026-27"}

        first = stats_cache.get_or_compute(self.profile, "dashboard", params, compute)
        self.assertEqual(first, {"value": 42})
        self.assertEqual(compute.calls, 1)

        # A second call with the SAME params is a hit: compute is not called again.
        second = stats_cache.get_or_compute(self.profile, "dashboard", params, compute)
        self.assertEqual(second, {"value": 42})
        self.assertEqual(compute.calls, 1)

    def test_different_params_is_a_separate_miss(self):
        compute = Counter({"value": 1})
        stats_cache.get_or_compute(self.profile, "dashboard", {"a": 1}, compute)
        stats_cache.get_or_compute(self.profile, "dashboard", {"a": 2}, compute)
        self.assertEqual(compute.calls, 2)
        self.assertEqual(
            StatsCache.objects.filter(profile=self.profile, kind="dashboard").count(),
            2,
        )

    def test_different_kind_is_a_separate_miss(self):
        compute = Counter({"value": 1})
        stats_cache.get_or_compute(self.profile, "dashboard", {"a": 1}, compute)
        stats_cache.get_or_compute(self.profile, "statistics", {"a": 1}, compute)
        self.assertEqual(compute.calls, 2)

    def test_hit_returns_stored_payload_not_a_fresh_compute(self):
        # The stored payload is returned verbatim even if compute would now differ.
        stats_cache.get_or_compute(
            self.profile, "dashboard", {"a": 1}, Counter({"stored": True})
        )
        changed = Counter({"stored": False})
        result = stats_cache.get_or_compute(self.profile, "dashboard", {"a": 1}, changed)
        self.assertEqual(result, {"stored": True})
        self.assertEqual(changed.calls, 0)


# ---------------------------------------------------------------------------
# Invalidation on each write type
# ---------------------------------------------------------------------------

class InvalidationTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()
        self.firm, self.group = seed_firm(self.profile)
        self.matter = seed_matter(self.profile, self.firm, self.group)

    def _warm(self):
        """Seeds one cached dashboard row and returns its counter."""
        compute = Counter({"value": 1})
        stats_cache.get_or_compute(self.profile, "dashboard", {"a": 1}, compute)
        self.assertEqual(compute.calls, 1)
        return compute

    def _assert_recomputes(self, compute):
        """A fresh get_or_compute after a write must call compute again."""
        stats_cache.get_or_compute(self.profile, "dashboard", {"a": 1}, compute)
        self.assertEqual(compute.calls, 2)

    def test_create_memo_invalidates_cache(self):
        compute = self._warm()
        memo_with_total(self.profile, self.matter, 1000)
        self.assertFalse(StatsCache.objects.filter(profile=self.profile).exists())
        self._assert_recomputes(compute)

    def test_add_payment_invalidates_cache(self):
        memo = memo_with_total(self.profile, self.matter, 1000)
        compute = self._warm()
        payments.add_payment_to_memo(
            self.profile, memo.pk, dict(amount=100, date_of_payment="2026-08-01")
        )
        self.assertFalse(StatsCache.objects.filter(profile=self.profile).exists())
        self._assert_recomputes(compute)

    def test_create_firm_invalidates_cache(self):
        compute = self._warm()
        firms.create_firm(self.profile, "Another Firm")
        self.assertFalse(StatsCache.objects.filter(profile=self.profile).exists())
        self._assert_recomputes(compute)

    def test_settings_update_invalidates_cache(self):
        compute = self._warm()
        settings.update_settings(self.profile, {"overdue_days": 45})
        self.assertFalse(StatsCache.objects.filter(profile=self.profile).exists())
        self._assert_recomputes(compute)


# ---------------------------------------------------------------------------
# Current-month / today date key
# ---------------------------------------------------------------------------

class TodaySensitiveTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()

    def test_today_sensitive_row_stores_valid_on_today(self):
        fixed = datetime.date(2026, 11, 5)
        self.addCleanup(setattr, stats_cache, "_today", stats_cache._today)
        stats_cache._today = lambda: fixed

        stats_cache.get_or_compute(
            self.profile, "statistics", {"a": 1}, Counter({"v": 1}),
            today_sensitive=True,
        )
        row = StatsCache.objects.get(profile=self.profile, kind="statistics")
        self.assertEqual(row.valid_on, fixed)

    def test_non_today_sensitive_row_stores_null_valid_on(self):
        stats_cache.get_or_compute(
            self.profile, "statistics", {"a": 1}, Counter({"v": 1})
        )
        row = StatsCache.objects.get(profile=self.profile, kind="statistics")
        self.assertIsNone(row.valid_on)

    def test_today_sensitive_row_is_a_miss_on_a_later_day(self):
        self.addCleanup(setattr, stats_cache, "_today", stats_cache._today)

        # Compute on day one, stamping valid_on = that day.
        stats_cache._today = lambda: datetime.date(2026, 11, 5)
        compute = Counter({"v": 1})
        stats_cache.get_or_compute(
            self.profile, "statistics", {"a": 1}, compute, today_sensitive=True
        )
        self.assertEqual(compute.calls, 1)

        # Same day: hit.
        stats_cache.get_or_compute(
            self.profile, "statistics", {"a": 1}, compute, today_sensitive=True
        )
        self.assertEqual(compute.calls, 1)

        # Next day: the stored valid_on no longer matches, so it is a miss.
        stats_cache._today = lambda: datetime.date(2026, 11, 6)
        stats_cache.get_or_compute(
            self.profile, "statistics", {"a": 1}, compute, today_sensitive=True
        )
        self.assertEqual(compute.calls, 2)

    def test_date_independent_row_survives_a_day_change(self):
        self.addCleanup(setattr, stats_cache, "_today", stats_cache._today)
        stats_cache._today = lambda: datetime.date(2026, 11, 5)
        compute = Counter({"v": 1})
        stats_cache.get_or_compute(self.profile, "dashboard", {"a": 1}, compute)

        # A later day does not expire a valid_on=None row (only data_version does).
        stats_cache._today = lambda: datetime.date(2027, 1, 1)
        stats_cache.get_or_compute(self.profile, "dashboard", {"a": 1}, compute)
        self.assertEqual(compute.calls, 1)


# ---------------------------------------------------------------------------
# 200-entry prune
# ---------------------------------------------------------------------------

class PruneTests(TestCase):
    def setUp(self):
        self.profile = fees_profile()

    def test_keeps_at_most_200_rows_per_profile(self):
        # Write 205 distinct params at the SAME data_version (no touch between
        # writes), so pruning by count, not by data_version, does the eviction.
        for index in range(205):
            stats_cache.get_or_compute(
                self.profile, "dashboard", {"i": index}, Counter({"i": index})
            )
        count = StatsCache.objects.filter(profile=self.profile).count()
        self.assertEqual(count, stats_cache.MAX_ROWS_PER_PROFILE)
        self.assertEqual(count, 200)

    def test_prune_evicts_the_oldest_by_created_at(self):
        for index in range(stats_cache.MAX_ROWS_PER_PROFILE + 5):
            stats_cache.get_or_compute(
                self.profile, "dashboard", {"i": index}, Counter({"i": index})
            )
        # The five earliest writes are gone; the most recent survive.
        remaining = set(
            StatsCache.objects.filter(profile=self.profile).values_list(
                "params_hash", flat=True
            )
        )
        oldest_hash = stats_cache._params_hash({"i": 0})
        newest_hash = stats_cache._params_hash(
            {"i": stats_cache.MAX_ROWS_PER_PROFILE + 4}
        )
        self.assertNotIn(oldest_hash, remaining)
        self.assertIn(newest_hash, remaining)


# ---------------------------------------------------------------------------
# Profile isolation
# ---------------------------------------------------------------------------

class IsolationTests(TestCase):
    def test_one_profile_cache_never_satisfies_another(self):
        alpha = fees_profile("Alpha")
        beta = fees_profile("Beta")

        alpha_compute = Counter({"who": "alpha"})
        stats_cache.get_or_compute(alpha, "dashboard", {"a": 1}, alpha_compute)
        self.assertEqual(alpha_compute.calls, 1)

        # Same kind and params, different profile: a miss, computed separately.
        beta_compute = Counter({"who": "beta"})
        result = stats_cache.get_or_compute(beta, "dashboard", {"a": 1}, beta_compute)
        self.assertEqual(beta_compute.calls, 1)
        self.assertEqual(result, {"who": "beta"})

        # Each profile keeps its own row; beta's write did not touch alpha's.
        self.assertEqual(StatsCache.objects.filter(profile=alpha).count(), 1)
        self.assertEqual(StatsCache.objects.filter(profile=beta).count(), 1)

        # Alpha still hits its own cached payload without recomputing.
        again = stats_cache.get_or_compute(alpha, "dashboard", {"a": 1}, alpha_compute)
        self.assertEqual(again, {"who": "alpha"})
        self.assertEqual(alpha_compute.calls, 1)
