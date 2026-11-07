"""Page query budget: a page may not run more queries when there is three times the data (N+1 guard).

Every main page of the suite is fetched with a small data set and again with a larger one. For each page the larger
count may exceed the smaller by at most SLACK, and every count must stay under a generous ceiling. Exact counts are
not asserted, so ordinary changes to a page do not break this test; only a query per row (an N+1) does.

The Fee Register list, dashboard and statistics pages are guarded in fees/tests/test_view_queries.py; this file
covers the rest of the Fee Register pages plus the shared pages (Home, Settings, Admin screens) and the diary pages.
"""
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.models import ROLE_EDITOR, Profile, ProfileMembership
from accounts.suite import KEY_DIARY
from diary.models import Subtopic, Topic
from diary.tests.helpers import join_main, main_profile
from diary.tests.test_query_counts import build_subject
from fees.models import Firm, Matter, Memo
from fees.tests.test_view_queries import LARGE, SMALL, fill

User = get_user_model()
PASSWORD = "x-long-pass-123"
SLACK = 2
CEILING = 80
#: Pages that DO run queries per row today (found by this guard, listed as proposals in docs/EFFICIENCY_REVIEW.md).
#: They are exempt from the flatness check but must stay under a larger ceiling. When one is fixed, the ratchet test
#: below fails until its name is removed from this dict, so the list can only shrink.
KNOWN_GROWTH = {}
KNOWN_CEILING = 150


class BudgetMixin:
    def measure(self, url):
        """(status, number of queries) for one GET of ``url``, after a warm-up request."""
        self.client.get(url)  # warm up the session, content types and per-user lookups
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(url)
            if getattr(response, "streaming", False):
                b"".join(response.streaming_content)
        self.assertLess(response.status_code, 500, url)
        return response.status_code, len(captured)

    def measure_all(self, urls):
        return {label: self.measure(url) for label, url in urls.items()}

    def assert_flat(self, small, large, must_be_ok=()):
        """``small`` and ``large`` map a page label to (status, queries)."""
        for label, (_status, count) in small.items():
            big = large[label][1]
            if label in KNOWN_GROWTH:
                self.assertLess(big, KNOWN_CEILING, f"{label}: {big} queries")
                continue
            self.assertLessEqual(big, count + SLACK, f"{label}: {count} queries for N rows, {big} for 3N rows")
            self.assertLess(big, CEILING, f"{label}: {big} queries")
        for label in must_be_ok:
            self.assertEqual(large[label][0], 200, label)


@override_settings(SECURE_SSL_REDIRECT=False)
class SuitePageBudgetTests(BudgetMixin, TestCase):
    """Home, Settings, My settings, the Admin screens and the diary pages."""

    def setUp(self):
        self.admin = User.objects.create_user("qadmin", password=PASSWORD, is_superuser=True, is_staff=True)
        join_main(self.admin, "editor")
        self.client.force_login(self.admin)

    def test_admin_and_shared_pages_do_not_grow_with_users_and_profiles(self):
        urls = {
            "home": reverse("home"),
            "help": reverse("help"),
            "my_settings": reverse("my_settings"),
            "settings": reverse("settings"),
            "user_list": reverse("user_list"),
            "profile_list": reverse("profile_list"),
            "backup_list": reverse("backup_list"),
            "backup_list_email": reverse("backup_list") + "?tab=email",
            "profile_new": reverse("profile_create"),
            "user_new": reverse("user_create"),
        }

        def add(first, count):
            for n in range(first, first + count):
                user = User.objects.create_user(f"qu{n}", password=PASSWORD, email=f"qu{n}@example.com")
                profile = Profile.objects.create(program=KEY_DIARY, name=f"QP{n}")
                ProfileMembership.objects.create(user=user, profile=profile, role=ROLE_EDITOR)

        add(0, 4)
        small = self.measure_all(urls)
        add(4, 8)
        large = self.measure_all(urls)
        self.assert_flat(small, large, must_be_ok=("home", "my_settings", "settings", "user_list", "profile_list", "backup_list"))
        for label in KNOWN_GROWTH:
            if label in large:
                self.assertGreater(
                    large[label][1], small[label][1] + SLACK,
                    f"{label} no longer grows with the data: remove it from KNOWN_GROWTH ({KNOWN_GROWTH[label]})",
                )

    def test_diary_pages_do_not_grow_with_the_size_of_the_diary(self):
        profile = main_profile()
        small_subject = build_subject(profile, topics=2, items_per_container=3, name="Small subject")

        def subject_urls(subject):
            topic = Topic.objects.filter(subject=subject).order_by("pk").first()
            subtopic = Subtopic.objects.filter(topic=topic).order_by("pk").first()
            return {
                "subject_contents": reverse("subject_contents", args=[subject.pk]),
                "read_subject": reverse("read_subject", args=[subject.pk]),
                "read_topic": reverse("read_topic", args=[topic.pk]),
                "read_subtopic": reverse("read_subtopic", args=[subtopic.pk]),
            }

        shared = {
            "diary_home": reverse("diary_home"),
            "other_subjects": reverse("other_subjects"),
            "flags": reverse("flags"),
            "search": reverse("search") + "?q=item",
            "trash": reverse("trash"),
            "diary_history": reverse("diary_history"),
            "export": reverse("export"),
            "profile_settings": reverse("profile_settings"),
            "import_word": reverse("import_word"),
        }
        small_pages = self.measure_all(subject_urls(small_subject))
        shared_before = self.measure_all(shared)

        big_subject = build_subject(profile, topics=6, items_per_container=3, name="Big subject")
        big_pages = self.measure_all(subject_urls(big_subject))
        shared_after = self.measure_all(shared)

        self.assert_flat(small_pages, big_pages, must_be_ok=("subject_contents", "read_subject"))
        self.assert_flat(shared_before, shared_after, must_be_ok=("diary_home",))


@override_settings(SECURE_SSL_REDIRECT=False)
class FeesPageBudgetTests(BudgetMixin, TestCase):
    """The Fee Register pages that test_view_queries.py does not cover, for a profile of N and one of 3N rows."""

    @classmethod
    def setUpTestData(cls):
        cls.small, cls.small_user = fill("qb-small", SMALL)
        cls.large, cls.large_user = fill("qb-large", LARGE)
        for user in (cls.small_user, cls.large_user):
            User.objects.filter(pk=user.pk).update(is_superuser=True, is_staff=True)
            ProfileMembership.objects.filter(user=user).update(role=ROLE_EDITOR)

    def urls(self, profile):
        memo = Memo.objects.filter(profile=profile, is_draft=False).order_by("pk").first()
        firm = Firm.objects.filter(profile=profile).order_by("pk").first()
        matter = Matter.objects.filter(profile=profile).order_by("pk").first()
        return {
            "fees_landing": reverse("fees_landing"),
            "fees_settings": reverse("fees_settings"),
            "fees_backup": reverse("fees_backup"),
            "fees_import": reverse("fees_import"),
            "fees_memo_new": reverse("fees_memo_new"),
            "fees_payment_new": reverse("fees_payment_new"),
            "fees_matter_new": reverse("fees_matter_new"),
            "fees_firm_new": reverse("fees_firm_new"),
            "fees_statistics_year_end": reverse("fees_statistics_year_end"),
            "fees_memo_detail": reverse("fees_memo_detail", kwargs={"memo_id": memo.pk}),
            "fees_memo_edit": reverse("fees_memo_edit", kwargs={"memo_id": memo.pk}),
            "fees_firm_statement": reverse("fees_firm_statement", kwargs={"firm_id": firm.pk}),
            "fees_firm_ledger": reverse("fees_firm_ledger", kwargs={"firm_id": firm.pk}),
            "fees_matter_detail": reverse("fees_matter_detail", kwargs={"matter_id": matter.pk}),
            "fees_matter_statement": reverse("fees_matter_statement", kwargs={"matter_id": matter.pk}),
            "fees_matter_ledger": reverse("fees_matter_ledger", kwargs={"matter_id": matter.pk}),
        }

    def test_other_fee_register_pages_do_not_grow_with_data(self):
        self.client.force_login(self.small_user)
        small = self.measure_all(self.urls(self.small))
        self.client.force_login(self.large_user)
        large = self.measure_all(self.urls(self.large))
        self.assert_flat(small, large, must_be_ok=("fees_settings", "fees_memo_detail"))
