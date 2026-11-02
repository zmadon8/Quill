"""The 404 handler: a browser that asks for an address that matches no route is sent Home with a permanent (301)
redirect, as the owner asked (docs/DESIGN.md, Round 8). A real address whose record is missing gets a temporary
(302) redirect instead, because the record can come back from the Trash. Everything that is not a plain page request in a
browser (forms, fetch calls, assets, health checks) still gets a real 404."""
from django.contrib import messages
from django.contrib.messages.api import MessageFailure
from django.http import Http404, HttpResponsePermanentRedirect, HttpResponseRedirect
from django.urls import Resolver404, reverse
from django.views.defaults import page_not_found

from accounts.profiles import request_profile

ASSET_EXTENSIONS = (".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".map", ".json", ".txt", ".xml",
                    ".woff", ".woff2", ".webmanifest")
GONE_MESSAGE = "That page no longer exists."


def _is_browser_page_request(request):
    """True for a GET/HEAD that a browser made to show a page (not fetch, not an asset, not the health check)."""
    if request.method not in ("GET", "HEAD"):
        return False
    if "text/html" not in request.META.get("HTTP_ACCEPT", ""):
        return False
    if request.META.get("HTTP_X_REQUESTED_WITH", "") in ("fetch", "XMLHttpRequest"):
        return False
    path = request.path_info
    if path.startswith("/static/") or path == "/healthz/":
        return False
    return not path.lower().endswith(ASSET_EXTENSIONS)


def _destination(request):
    """Program Home for an address under /caselaw/ when the user has a profile there, else suite Home."""
    user = getattr(request, "user", None)
    if (request.path_info.startswith("/caselaw/") and user is not None and user.is_authenticated
            and request_profile(request) is not None):
        return reverse("diary_home")
    return reverse("home") + "?home=1"


def not_found(request, exception=None, template_name="404.html"):
    """handler404: 301 to Home for unmatched addresses, 302 for a missing record, a plain 404 for everything else."""
    if not _is_browser_page_request(request):
        return page_not_found(request, exception, template_name)
    if isinstance(exception, Http404) and not isinstance(exception, Resolver404):
        # The address exists but the record does not (deleted, or another profile's): say so on the page we land on.
        # Temporary (302): a restore from the Trash can make this address live again, so it must not be cached.
        try:
            messages.info(request, GONE_MESSAGE)
        except MessageFailure:
            pass
        return HttpResponseRedirect(_destination(request))
    return HttpResponsePermanentRedirect(_destination(request))
