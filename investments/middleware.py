"""The INVESTMENTS_ENABLED dark-launch guard: while the flag is off every /investments URL is a 404."""
from django.conf import settings
from django.http import Http404


class InvestmentsEnabledMiddleware:
    """Return 404 for ``/investments`` and everything below it when ``settings.INVESTMENTS_ENABLED`` is false.

    The flag is read from ``django.conf.settings`` on every request so a test can switch it with
    ``override_settings``. Models, migrations and the suite backup and restore are not behind this guard.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not getattr(settings, "INVESTMENTS_ENABLED", True):
            path = request.path_info
            if path == "/investments" or path.startswith("/investments/"):
                raise Http404("Investments is not available.")
        return self.get_response(request)


class RequestTimingMiddleware:
    """Measure where the time goes, when ``QUILL_PERF_LOG=1`` is set (off otherwise, and then it costs one attribute test per request).

    Each request under /investments/ logs one line, ``PERF GET /investments/ 200 total=412ms db=290ms queries=37``, to the ordinary log (on
    Render: the service's Logs tab), and the response carries a ``Server-Timing`` header, which the browser's Network tab shows under Timing.
    Compare a page before and after a change, or find the pages with the most queries."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings

        if not getattr(settings, "PERF_LOG", False) or not request.path_info.startswith("/investments/"):
            return self.get_response(request)
        import logging
        import time

        from django.db import connection

        spent = [0.0, 0]

        def timed(execute, sql, params, many, context):
            started = time.perf_counter()
            try:
                return execute(sql, params, many, context)
            finally:
                spent[0] += time.perf_counter() - started
                spent[1] += 1

        started = time.perf_counter()
        with connection.execute_wrapper(timed):
            response = self.get_response(request)
        total_ms, db_ms = (time.perf_counter() - started) * 1000, spent[0] * 1000
        response["Server-Timing"] = f'total;dur={total_ms:.0f}, db;dur={db_ms:.0f}, queries;desc="{spent[1]}"'
        logging.getLogger("quill.perf").info("PERF %s %s %s total=%.0fms db=%.0fms queries=%d", request.method, request.path_info,
                                             response.status_code, total_ms, db_ms, spent[1])
        return response
