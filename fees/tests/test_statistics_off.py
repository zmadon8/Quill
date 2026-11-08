"""Owner decision 3: with Statistics switched off nothing in the statistics engine runs.

The Statistics page, the year-end page, every statistics JSON endpoint, the saved views, the adjustment
grid and the three statistics exports refuse. The JSON ones answer ``STATISTICS_DISABLED`` with HTTP 409;
the page shows a short message with status 200; the file exports flash the message and redirect. Each test
patches the engine entry points to raise, so a call to any of them fails the test. With Statistics on,
behaviour is unchanged.
"""
from contextlib import ExitStack
from unittest import mock

from django.contrib.messages import get_messages
from django.test import override_settings
from django.urls import reverse

from fees.errors import FeesError, status_for
from fees.models import FeesSettings, PeriodAdjustment, SavedView
from fees.tests.test_views_read import SeededViewsBase

ENGINE = (
    "fees.services.statistics.get_period_statistics",
    "fees.services.statistics.get_pivot",
    "fees.services.statistics.get_year_end_summary",
    "fees.services.statistics.list_saved_views",
    "fees.services.statistics.save_saved_view",
    "fees.services.statistics.delete_saved_view",
    "fees.services.statistics.list_adjustments",
    "fees.services.statistics.save_adjustment",
    "fees.exports.xlsx.get_period_statistics",
    "fees.exports.tax_summary.get_year_end_summary",
    "fees.services.stats_cache.get_or_compute",
)
MESSAGE = "Statistics is switched off in Settings."
JSON_GETS = (
    ("fees_statistics_data", "?granularity=month&fy=2026-27"),
    ("fees_statistics_explore", "?measure=billed&row_dim=financialYear&col_dim=none"),
    ("fees_statistics_views", ""),
    ("fees_settings_statistics_grid", "?fy=2026-27"),
)
FILE_GETS = (
    ("fees_statistics_export", "?granularity=month&fy=2026-27"),
    ("fees_statistics_annual_export", "?fy=2026-27"),
    ("fees_statistics_tax_summary", "?fy=2026-27"),
)
PAGE_GETS = (
    ("fees_statistics", ""),
    ("fees_statistics", "?tab=edit&fy=2026-27"),
    ("fees_statistics", "?tab=explore"),
    ("fees_statistics_year_end", "?fy=2026-27"),
)


def tripwires(stack):
    """Make every statistics engine entry point raise if it is called."""
    for target in ENGINE:
        stack.enter_context(mock.patch(target, side_effect=AssertionError("engine called: " + target)))


@override_settings(SECURE_SSL_REDIRECT=False)
class StatisticsOffTests(SeededViewsBase):
    def setUp(self):
        super().setUp()
        FeesSettings.objects.filter(profile=self.profile).update(statistics_enabled=False)

    def off(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        tripwires(stack)

    def test_the_error_code_is_409_with_a_message(self):
        self.assertEqual(status_for("STATISTICS_DISABLED"), 409)
        self.assertEqual(FeesError("STATISTICS_DISABLED").message, MESSAGE)

    def test_pages_say_it_is_off_and_compute_nothing(self):
        self.off()
        for user in (self.reader, self.editor):
            self.login(user)
            for name, query in PAGE_GETS:
                with self.subTest(page=name, query=query, user=user.username):
                    response = self.client.get(reverse(name) + query)
                    self.assertEqual(response.status_code, 200)
                    text = response.content.decode("utf-8")
                    self.assertIn(MESSAGE, text)
                    self.assertNotIn("still correct", text)
                    self.assertNotIn("<caption>", text)

    def test_only_an_editor_gets_the_settings_link(self):
        self.off()
        self.login(self.reader)
        reader = self.client.get(reverse("fees_statistics")).content.decode("utf-8")
        self.assertNotIn("Open Settings", reader)
        self.login(self.editor)
        editor = self.client.get(reverse("fees_statistics")).content.decode("utf-8")
        self.assertIn('<a href="%s">Open Settings</a>' % reverse("fees_settings"), editor)

    def test_json_endpoints_answer_409_and_compute_nothing(self):
        self.off()
        for user in (self.reader, self.editor):
            self.login(user)
            for name, query in JSON_GETS:
                with self.subTest(endpoint=name, user=user.username):
                    response = self.client.get(reverse(name) + query)
                    self.assertEqual(response.status_code, 409)
                    body = response.json()
                    self.assertFalse(body["ok"])
                    self.assertEqual(body["error"], "STATISTICS_DISABLED")
                    self.assertEqual(body["code"], "STATISTICS_DISABLED")
                    self.assertEqual(body["message"], MESSAGE)

    def test_editing_is_blocked_when_off(self):
        self.off()
        self.login(self.editor)
        before = (SavedView.objects.filter(profile=self.profile).count(), PeriodAdjustment.objects.filter(profile=self.profile).count())
        view = SavedView.objects.filter(profile=self.profile).first()
        posts = (
            (reverse("fees_statistics_views"), {"name": "N", "measure": "billed", "row_dim": "month", "col_dim": "none"}),
            (reverse("fees_statistics_view_delete", kwargs={"view_id": view.pk}), {}),
            (reverse("fees_settings_statistics_grid"), {"fy": "2026-27", "month": "4", "working_days": "5"}),
        )
        for url, data in posts:
            with self.subTest(url=url):
                response = self.client.post(url, data)
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json()["error"], "STATISTICS_DISABLED")
                page = self.client.post(url, dict(data, return_to="statistics"))
                self.assertEqual(page.status_code, 302)
                self.assertIn(MESSAGE, [str(m) for m in get_messages(page.wsgi_request)])
        after = (SavedView.objects.filter(profile=self.profile).count(), PeriodAdjustment.objects.filter(profile=self.profile).count())
        self.assertEqual(before, after)

    def test_exports_refuse_and_compute_nothing(self):
        self.off()
        self.login(self.reader)
        for name, query in FILE_GETS:
            with self.subTest(export=name):
                response = self.client.get(reverse(name) + query)
                self.assertEqual(response.status_code, 302)
                self.assertIn(MESSAGE, [str(m) for m in get_messages(response.wsgi_request)])
                self.assertFalse(response.has_header("Content-Disposition"))

    def test_the_page_makes_no_cache_write(self):
        from fees.models import StatsCache

        self.off()
        self.login(self.reader)
        self.client.get(reverse("fees_statistics"))
        self.client.get(reverse("fees_statistics_data") + "?granularity=month&fy=2026-27")
        self.assertFalse(StatsCache.objects.filter(profile=self.profile).exists())


@override_settings(SECURE_SSL_REDIRECT=False)
class StatisticsOnTests(SeededViewsBase):
    """With Statistics on the same routes work as before."""

    def setUp(self):
        super().setUp()
        FeesSettings.objects.filter(profile=self.profile).update(statistics_enabled=True)

    def test_pages_and_endpoints_answer(self):
        self.login(self.reader)
        for name, query in PAGE_GETS + JSON_GETS:
            with self.subTest(route=name, query=query):
                response = self.client.get(reverse(name) + query)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn(MESSAGE, response.content.decode("utf-8"))
        for name, query in FILE_GETS:
            with self.subTest(export=name):
                response = self.client.get(reverse(name) + query)
                self.assertEqual(response.status_code, 200)
