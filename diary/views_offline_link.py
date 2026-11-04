"""Round 21 (D100): the public page and download behind an Offline link's secret address.

These two views are deliberately OPEN: they have no login decorator, because the address itself is the key (the owner
chose a secret link with no password, so it works at once on a phone with poor network). They therefore:
  * answer every wrong, switched-off or deleted link with the SAME small 404 page, so nothing is revealed;
  * never build the file (they only hand out the copy an Admin or the nightly job saved earlier);
  * keep the token out of the app's own log lines (the explicit log calls leave it out and a filter on the console
    handler redacts it from Django's request warnings; the web server's access log still shows it);
  * tell search engines, caches and other sites to keep away (headers on every response).
"""
import hmac
import logging
import re

from django.http import HttpResponse
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.http import content_disposition_header, http_date
from django.views.decorators.http import require_safe

from accounts.models import OfflineLink, hash_token
from accounts.profiles import effective_export_name

from .offline_link import download_limited

logger = logging.getLogger(__name__)

MAX_TOKEN_LENGTH = 100
NOT_WORKING = "This link is not working. Ask for a new one."
NO_COPY = "No copy is ready yet. Please ask the Admin to make one."
RANGE_RE = re.compile(r"^bytes=(\d+)-(\d*)$")


def size_text(size):
    """A short size for a phone screen: 3.4 MB, or KB for a tiny file."""
    if size < 100 * 1024:
        return f"{max(size, 1) / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _headers(response, cache):
    response["Cache-Control"] = cache
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _message(text, status, cache="private, no-store"):
    body = render_to_string("diary/offline_public_message.html", {"message": text})
    return _headers(HttpResponse(body, status=status), cache)


def _find(token):
    """The switched-on link of a live profile for this token, or None for any reason at all."""
    if not token or len(token) > MAX_TOKEN_LENGTH:
        return None
    link = (
        OfflineLink.objects.select_related("profile").defer("copy_data").filter(token_hash=hash_token(token)).first()
    )
    if link is None or not hmac.compare_digest(link.token.encode("utf-8"), token.encode("utf-8")):
        return None
    if not link.enabled or link.profile.deleted_at is not None:
        return None
    return link


@require_safe
def offline_public(request, token):
    link = _find(token)
    if link is None:
        return _message(NOT_WORKING, 404)
    context = {
        "name": effective_export_name(link.profile),
        "link": link,
        "has_copy": link.has_copy,
        "size": size_text(link.copy_size),
        "download_url": reverse("offline_download", args=[token]),
    }
    return _headers(HttpResponse(render_to_string("diary/offline_public.html", context)), "private, no-store")


def _etag(link, size):
    return '"%d-%d"' % (int(link.copy_made_at.timestamp() * 1000000), size)


@require_safe
def offline_download(request, token):
    link = _find(token)
    if link is None:
        return _message(NOT_WORKING, 404)
    if not link.has_copy:
        return _message(NO_COPY, 404)

    # Every GET that sends a body is counted: a full download or retry from byte 0 against the main limit, a resumed
    # range (start above 0) against a looser separate cap. HEAD is answered from the stored metadata and not counted.
    etag_given = request.META.get("HTTP_IF_RANGE", "")
    match = RANGE_RE.match(request.META.get("HTTP_RANGE", "").strip())
    wanted = None
    if match and (not etag_given or etag_given == _etag(link, link.copy_size)):
        wanted = (int(match.group(1)), int(match.group(2)) if match.group(2) else None)

    if request.method == "HEAD":
        response = HttpResponse(b"", content_type="text/html; charset=utf-8")
        response["Content-Length"] = str(link.copy_size)
        return _file_headers(response, link, link.copy_size)

    resume = wanted is not None and wanted[0] > 0
    if download_limited(request, link, resume=resume):
        response = _message("Too many downloads. Please try again in an hour.", 429)
        response["Retry-After"] = "3600"
        return response

    data = OfflineLink.objects.filter(pk=link.pk).values_list("copy_data", flat=True).first()
    if data is None:
        return _message(NO_COPY, 404)
    data = memoryview(data)  # PostgreSQL gives a memoryview already; slicing it does not copy
    total = len(data)

    status, body, first, last = 200, data, 0, total - 1
    if wanted is not None:
        first, last = wanted[0], wanted[1] if wanted[1] is not None else total - 1
        if first >= total or last < first:
            response = _headers(HttpResponse(status=416), "private, no-cache")
            response["Content-Range"] = f"bytes */{total}"
            return response
        last = min(last, total - 1)
        status, body = 206, data[first : last + 1]

    response = HttpResponse(body, status=status, content_type="text/html; charset=utf-8")
    if status == 206:
        response["Content-Range"] = f"bytes {first}-{last}/{total}"
    if first == 0 and status == 200:
        logger.info("Offline copy downloaded: profile %s, %s bytes", link.profile_id, total)
    return _file_headers(response, link, total)


def _file_headers(response, link, total):
    response["Content-Disposition"] = content_disposition_header(True, link.copy_name or "Offline copy.html")
    response["Accept-Ranges"] = "bytes"
    response["ETag"] = _etag(link, total)
    response["Last-Modified"] = http_date(link.copy_made_at.timestamp())
    return _headers(response, "private, no-cache")
