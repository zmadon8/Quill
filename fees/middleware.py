"""The FEES_ENABLED dark-launch guard: while the flag is off every /fees URL is a 404."""
from django.conf import settings
from django.http import Http404


class FeesEnabledMiddleware:
    """Return 404 for ``/fees`` and everything below it when ``settings.FEES_ENABLED`` is false.

    The flag is read from ``django.conf.settings`` on every request so a test can switch it with
    ``override_settings``. Models, migrations and the suite backup and restore are not behind this guard.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not getattr(settings, "FEES_ENABLED", True):
            path = request.path_info
            if path == "/fees" or path.startswith("/fees/"):
                raise Http404("The Fee Register is not available.")
        return self.get_response(request)
