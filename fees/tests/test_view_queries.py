"""Query-count tests for the list, dashboard and statistics views (T7.4).

Two profiles are filled with the same shape of data, one with N rows and one with 3N. A view that runs a
query per row would use far more queries for the large profile, so for each view the test checks that the
large profile does not use more queries than the small one (plus a tiny slack), and that the count stays
under a generous upper bound. Exact counts are deliberately not asserted.

The row counts stay under the 50 row page size so the large page really holds three times the rows. The
number of financial years is fixed (2) so a per-year query does not look like a per-row one.
"""
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.models import ROLE_READER, Profile, ProfileMembership
from accounts.suite import KEY_FEES
from fees.models import FeesSettings, Firm, Matter, Memo
from fees.services import memos
from fees.tests.datasets import build_planning_dataset

User = get_user_model()
PASSWORD = "x-Test-Pw-1"

SMALL = 15
LARGE = 3 * SMALL
SLACK = 2
UPPER_BOUND = 120  # generous: a page is a few dozen queries at most, a per-row loop would pass this at 3N rows
FY = "2015-16"


def fill(name, rows):
    """A Fee Register profile with a reader, ``rows`` memos, payments and allocations, and a third as many drafts."""
    profile = Profile.objects.create(program=KEY_FEES, name=name)
    build_planning_dataset(
        profile,
        memos=rows,
        payments=rows,
        allocations=rows,
        firms=rows // 5,
        years=2,
        first_fy_start=2015,
        seed=7,
    )
    matter = Matter.objects.filter(profile=profile).order_by("pk").first()
    for n in range(rows // 3):
        memos.save_draft(profile, {"matter_id": matter.pk, "addressee_line1": f"Draft addressee {n}"})
    # Settings last, with update_or_create (a service mutator has already created the row).
    FeesSettings.objects.update_or_create(profile=profile, defaults={})
    user = User.objects.create_user(username=f"reader-{name}", password=PASSWORD)
    ProfileMembership.objects.create(user=user, profile=profile, role=ROLE_READER)
    return profile, user


@override_settings(SECURE_SSL_REDIRECT=False)
class QueryCountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.small, cls.small_user = fill("q-small", SMALL)
        cls.large, cls.large_user = fill("q-large", LARGE)

    def count(self, user, url):
        """The number of queries one GET of ``url`` runs for ``user``; the response must be a 200."""
        self.client.force_login(user)
        self.client.get(reverse("fees_firms"))  # warm up the session and per-user lookups
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(url)
            if getattr(response, "streaming", False):
                b"".join(response.streaming_content)
        self.assertEqual(response.status_code, 200, url)
        return len(captured)

    def assert_flat(self, make_url):
        """``make_url(profile)`` is the URL for a profile; the 3N profile may not cost more queries than N."""
        small = self.count(self.small_user, make_url(self.small))
        large = self.count(self.large_user, make_url(self.large))
        label = make_url(self.small)
        self.assertLessEqual(large, small + SLACK, f"{label}: {small} queries for N rows, {large} for 3N rows")
        self.assertLess(large, UPPER_BOUND, f"{label}: {large} queries")

    def static(self, name, query=""):
        return lambda _profile: reverse(name) + query

    def test_the_two_profiles_differ_in_size(self):
        self.assertEqual(Memo.objects.filter(profile=self.small, is_draft=False).count(), SMALL)
        self.assertEqual(Memo.objects.filter(profile=self.large, is_draft=False).count(), LARGE)
        self.assertEqual(Memo.objects.filter(profile=self.large, is_draft=True).count(), LARGE // 3)
        self.assertEqual(Firm.objects.filter(profile=self.large).count(), LARGE // 5)

    def test_memo_list(self):
        self.assert_flat(self.static("fees_memos", "?fy="))

    def test_memo_list_filtered(self):
        self.assert_flat(self.static("fees_memos", "?fy=&unpaid=1"))

    def test_drafts(self):
        self.assert_flat(self.static("fees_memo_drafts", "?fy="))

    def test_firms(self):
        self.assert_flat(self.static("fees_firms"))

    def test_firm_detail(self):
        def url(profile):
            firm = Firm.objects.filter(profile=profile).order_by("pk").first()
            return reverse("fees_firm_detail", kwargs={"firm_id": firm.pk})

        self.assert_flat(url)

    def test_feebook(self):
        self.assert_flat(self.static("fees_feebook", "?fy="))

    def test_outstanding_summary(self):
        self.assert_flat(self.static("fees_outstanding"))

    def test_outstanding_detail(self):
        self.assert_flat(self.static("fees_outstanding_detail"))

    def test_search(self):
        self.assert_flat(self.static("fees_search", "?q=Firm"))

    def test_search_page(self):
        self.assert_flat(self.static("fees_search_page", "?q=Matter"))

    def test_dashboard(self):
        self.assert_flat(self.static("fees_dashboard"))

    def test_dashboard_kpis(self):
        self.assert_flat(self.static("fees_dashboard_kpis"))

    def test_statistics_page(self):
        self.assert_flat(self.static("fees_statistics", f"?granularity=month&fy={FY}"))

    def test_statistics_data(self):
        self.assert_flat(self.static("fees_statistics_data", f"?granularity=month&fy={FY}"))

    def test_statistics_data_by_financial_year(self):
        self.assert_flat(self.static("fees_statistics_data", "?granularity=financialYear"))

    def test_statistics_explore(self):
        self.assert_flat(self.static("fees_statistics_explore", "?measure=billed&row_dim=financialYear&col_dim=none"))

    def test_statistics_explore_by_firm(self):
        self.assert_flat(self.static("fees_statistics_explore", "?measure=billed&row_dim=firm&col_dim=financialYear"))
