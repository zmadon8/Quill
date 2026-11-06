"""Role decorators and error mapping for the Fee Register views (design sections 12 and 13).

* ``fees_reader`` / ``fees_editor``: the shared ``program_*_required(KEY_FEES)`` decorators. An anonymous user
  is sent to the login page, a signed-in user with no Fee Register membership gets 403, and a Reader may not
  use an Editor view (403).
* ``fees_read_write``: GET and HEAD need any role (Reader or Editor), every other method needs an Editor.
* ``handle_fees_errors(json=...)``: turns a ``FeesError`` into the JSON error body for a JSON view, or into a
  flash message plus a redirect for an HTML view (a 404 code is a real 404 so another profile's id never
  leaks). ``heavy.Busy`` becomes the 503 busy page.

A view never calls ``touch``: the services already bump ``data_version``.
"""
from functools import wraps

from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from accounts.permissions import program_editor_required, program_reader_required
from accounts.suite import KEY_FEES
from fees.errors import FeesError
from fees.services.heavy import Busy

fees_reader = program_reader_required(KEY_FEES)
fees_editor = program_editor_required(KEY_FEES)

_READ_METHODS = ("GET", "HEAD")


def fees_read_write(view):
    """GET and HEAD for any Fee Register role; every other method for an Editor only."""
    reader_view = fees_reader(view)
    editor_view = fees_editor(view)

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.method in _READ_METHODS:
            return reader_view(request, *args, **kwargs)
        return editor_view(request, *args, **kwargs)

    return wrapper


def error_body(err):
    """The JSON body for a ``FeesError`` (design section 13)."""
    return {
        "ok": False,
        "error": err.code,
        "code": err.code,
        "message": err.message,
        "details": err.details,
    }


def error_response(err):
    """The JSON response for a ``FeesError``, with the error's HTTP status."""
    from django.core.serializers.json import DjangoJSONEncoder

    return JsonResponse(error_body(err), status=err.status, encoder=DjangoJSONEncoder)


def busy_response(request):
    """The 503 "system is busy" page."""
    return render(request, "fees/busy.html", status=503)


def safe_back(request, fallback=None):
    """The same-site page the user came from, else ``fallback`` (default: the Dashboard)."""
    target = request.META.get("HTTP_REFERER", "")
    if target and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return target
    return fallback or reverse("fees_dashboard")


def handle_fees_errors(json=False, fallback=None):
    """Decorator: map ``FeesError`` and ``Busy`` to a response.

    ``json=True``: ``{"ok": false, "error": code, "code": code, "message": ..., "details": ...}`` with the
    error's status. ``json=False``: a ``*_NOT_FOUND`` (404) error raises ``Http404``; any other error is a
    flash message and a redirect back (``fallback`` is a URL name, default the page the user came from, else
    the Dashboard). ``Busy`` is the 503 page for HTML and ``{"ok": false, "error": "BUSY"}`` for JSON.
    """

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            try:
                return view(request, *args, **kwargs)
            except FeesError as err:
                if json:
                    return error_response(err)
                if err.status == 404:
                    raise Http404(err.message) from err
                messages.error(request, err.message)
                return redirect(reverse(fallback) if fallback else safe_back(request))
            except Busy as exc:
                if json:
                    body = {"ok": False, "error": "BUSY", "code": "BUSY", "message": str(exc), "details": None}
                    return JsonResponse(body, status=503)
                return busy_response(request)

        return wrapper

    return decorator
