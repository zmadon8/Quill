"""The per-user interface preferences endpoint (column widths).

GET returns the saved object for a key; POST saves it. Any Fee Register role may use it: the data is the
user's own interface state, not fee data, so a Reader can keep their column widths too. It never touches
``data_version`` (see ``fees.services.prefs``).
"""
import json

from django.views.decorators.http import require_http_methods

from fees import scope
from fees.decorators import fees_reader, handle_fees_errors
from fees.errors import FeesError
from fees.pages import json_ok
from fees.services import prefs

#: Largest request body read for a save; the service has its own, tighter, limit on the value.
MAX_BODY = 16 * 1024


def _posted(request):
    """``(key, data)`` from a JSON body or from form fields ``key`` and ``data`` (a JSON text)."""
    if (request.content_type or "").split(";")[0].strip() == "application/json":
        raw = request.body
        if len(raw) > MAX_BODY:
            raise FeesError("INVALID_PREF", "The saved widths are too large.")
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, ValueError):
            raise FeesError("INVALID_PREF", "The request is not valid JSON.") from None
        if not isinstance(body, dict):
            raise FeesError("INVALID_PREF", "The request must be an object.")
        return body.get("key"), body.get("data")
    text = request.POST.get("data", "")
    if len(text) > MAX_BODY:
        raise FeesError("INVALID_PREF", "The saved widths are too large.")
    try:
        data = json.loads(text) if text else None
    except ValueError:
        raise FeesError("INVALID_PREF", "The widths are not valid JSON.") from None
    return request.POST.get("key"), data


@fees_reader
@handle_fees_errors(json=True)
@require_http_methods(["GET", "HEAD", "POST"])
def prefs_endpoint(request):
    profile, _settings = scope.context(request)
    if request.method == "POST":
        key, data = _posted(request)
        saved = prefs.set_pref(profile, request.user, key, data)
        return json_ok({"key": key, "data": saved})
    key = request.GET.get("key", "")
    return json_ok({"key": key, "data": prefs.get_prefs(profile, request.user, key)})
