"""Content-Security-Policy in report-only mode: the header is sent, nothing is blocked, and reports are logged safely."""
import json

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from config import csp


class HeaderTests(SimpleTestCase):
    def run_middleware(self, content_type):
        middleware = csp.CspReportOnlyMiddleware(lambda request: HttpResponse("x", content_type=content_type))
        return middleware(RequestFactory().get("/"))

    def test_html_pages_get_the_report_only_header_and_never_the_blocking_one(self):
        response = self.run_middleware("text/html; charset=utf-8")
        policy = response[csp.HEADER]
        self.assertEqual(csp.HEADER, "Content-Security-Policy-Report-Only")
        self.assertFalse(response.has_header("Content-Security-Policy"))
        self.assertIn("script-src 'self'", policy)
        self.assertIn("report-uri /csp-report/", policy)
        self.assertIn("object-src 'none'", policy)
        self.assertNotIn("script-src 'self' 'unsafe", policy)  # scripts never get 'unsafe-inline' or 'unsafe-eval'

    def test_downloads_and_json_are_left_alone(self):
        for kind in ("application/json", "application/octet-stream", "text/plain"):
            self.assertFalse(self.run_middleware(kind).has_header(csp.HEADER), kind)


class SentWithPagesTests(TestCase):
    def test_a_real_page_carries_the_header(self):
        response = self.client.get(reverse("login"), secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("script-src 'self'", response[csp.HEADER])


class ReportTests(TestCase):
    def setUp(self):
        cache.clear()

    def post(self, data, **extra):
        return self.client.post(reverse("csp_report"), json.dumps(data), content_type="application/csp-report", secure=True, **extra)

    def test_a_report_is_logged_as_one_line(self):
        data = {"csp-report": {"effective-directive": "script-src-elem", "blocked-uri": "inline",
                               "document-uri": "https://x.example/caselaw/subjects/?q=secret#frag", "source-file": "https://x.example/static/js/site.js", "line-number": 12}}
        with self.assertLogs("csp", "WARNING") as logs:
            self.assertEqual(self.post(data).status_code, 204)
        line = logs.output[0]
        self.assertIn("script-src-elem", line)
        self.assertIn("https://x.example/caselaw/subjects/", line)
        self.assertNotIn("secret", line)  # the query string is dropped

    def test_a_secret_offline_link_is_never_logged(self):
        data = {"csp-report": {"effective-directive": "script-src", "document-uri": "https://x.example/offline/SECRETTOKEN123/download"}}
        with self.assertLogs("csp", "WARNING") as logs:
            self.post(data)
        self.assertNotIn("SECRETTOKEN123", logs.output[0])

    def test_junk_and_oversized_reports_are_refused_quietly(self):
        self.assertEqual(self.client.post(reverse("csp_report"), "not json", content_type="application/csp-report", secure=True).status_code, 204)
        big = json.dumps({"csp-report": {"blocked-uri": "x" * 20000}})
        self.assertEqual(self.client.post(reverse("csp_report"), big, content_type="application/csp-report", secure=True).status_code, 413)
        self.assertEqual(self.client.get(reverse("csp_report"), secure=True).status_code, 405)

    def test_a_flood_is_cut_off(self):
        data = {"csp-report": {"effective-directive": "script-src"}}
        with self.assertLogs("csp", "WARNING") as logs:
            for _ in range(csp.MAX_REPORTS_PER_MINUTE + 25):
                self.assertEqual(self.post(data).status_code, 204)
        self.assertEqual(len(logs.output), csp.MAX_REPORTS_PER_MINUTE)


@override_settings(MIDDLEWARE=[m for m in settings.MIDDLEWARE if "csp" not in m])
class SwitchedOffTests(TestCase):
    def test_without_the_middleware_no_header_is_sent(self):
        self.assertFalse(self.client.get(reverse("login"), secure=True).has_header(csp.HEADER))
