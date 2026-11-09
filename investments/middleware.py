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
