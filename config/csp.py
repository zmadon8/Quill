"""Content-Security-Policy, in REPORT-ONLY mode: the browser tells us what a policy would block, and blocks nothing.

Why: if a page ever put someone's text on the page unescaped, a Content-Security-Policy would stop that text from running as a
script. Switching a policy on before every page is ready would break features (an inline handler that is refused simply does
nothing), so this first step only collects reports. Each report is written to the log as one "CSP report" line.

When the reports have stayed quiet for a while, the policy can be sent as ``Content-Security-Policy`` instead (change
``HEADER`` below). Styles keep ``'unsafe-inline'`` for now: scripts are what a policy protects, and the pages carry about 40
inline style attributes that are not worth the noise yet.

Switch off with ``CSP_REPORT_ONLY=0`` in the environment.
"""
import json
import logging
import re
import time
from urllib.parse import urlsplit

from django.core.cache import cache
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger("csp")

REPORT_PATH = "/csp-report/"
HEADER = "Content-Security-Policy-Report-Only"
POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self' data:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    f"report-uri {REPORT_PATH}",
])

MAX_REPORT_BYTES = 8 * 1024
MAX_REPORTS_PER_MINUTE = 60  # per server process; more are dropped, so a broken page cannot flood the log


class CspReportOnlyMiddleware:
    """Adds the report-only policy to every HTML page."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        content_type = (response.get("Content-Type", "") or "").split(";")[0].strip().lower()
        if content_type == "text/html" and HEADER not in response:
            response[HEADER] = POLICY
        return response


def _clean(value, limit=200):
    """A report field as short, one-line text. A page address loses its query and fragment, and a secret Offline link its token."""
    text = str(value or "")[:500]
    if text.startswith(("http://", "https://")):
        parts = urlsplit(text)
        text = f"{parts.scheme}://{parts.netloc}{parts.path}"
    text = re.sub(r"(/offline/)[^/\s]+", r"\1<token>", text)
    return " ".join(text.split())[:limit]


@csrf_exempt
@require_POST
def report(request):
    """Receives a browser's policy report and logs one line. Public on purpose (the browser sends no login)."""
    try:
        length = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    if length > MAX_REPORT_BYTES:
        return HttpResponse(status=413)
    minute = "csp-reports-" + str(int(time.time() // 60))
    cache.add(minute, 0, 120)
    try:
        if cache.incr(minute) > MAX_REPORTS_PER_MINUTE:
            return HttpResponse(status=204)
    except ValueError:  # the counter expired between the two calls
        pass
    try:
        body = json.loads(request.body[:MAX_REPORT_BYTES].decode("utf-8", "replace"))
        data = body.get("csp-report") if isinstance(body, dict) else None
    except ValueError:
        data = None
    if isinstance(data, dict):
        logger.warning(
            "CSP report: %s blocked=%s page=%s source=%s:%s",
            _clean(data.get("effective-directive") or data.get("violated-directive"), 60),
            _clean(data.get("blocked-uri"), 120),
            _clean(data.get("document-uri")),
            _clean(data.get("source-file")),
            _clean(data.get("line-number"), 10),
        )
    return HttpResponse(status=204)
