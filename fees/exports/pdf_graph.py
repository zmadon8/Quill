"""Memo PDFs made by Microsoft 365 (docs/FEES_PDF_EXPORT.md).

The memo's Word file (``word_template.render_memo_docx``) is uploaded to the app folder of the owner's OneDrive, Microsoft converts
it with Word's own engine (``GET /me/drive/items/{id}/content?format=pdf``), the PDF is streamed into a temporary file, and the Word
file is deleted from OneDrive again, also after a failure. Our server only uploads and downloads, so memory stays at a few MB.

Guards (section 3 of the design): one PDF at a time per worker process (a second request is refused at once, never queued), a
25 second limit on the whole export, a 20 MB cap on the PDF, and the PDF is fetched only from a Microsoft download host over HTTPS,
without our token. Every failure is a :class:`PdfError` with a message for the person; nothing here raises anything else.

The sign-in is the OAuth 2.0 authorisation-code flow with PKCE for a confidential web app, scope ``Files.ReadWrite.AppFolder``
(the app sees only ``OneDrive/Apps/<app name>``) and ``offline_access``. Tokens are stored encrypted with ``MS_GRAPH_TOKEN_KEY``
in ``fees.PdfConnection`` (never in a backup). Every HTTP call goes through :func:`_urlopen`, which the tests replace; no test
calls Microsoft.
"""
import base64
import datetime
import hashlib
import json
import secrets
import socket
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

GRAPH = "https://graph.microsoft.com/v1.0"
LOGIN_HOST = "https://login.microsoftonline.com"
SCOPES = "openid email profile offline_access Files.ReadWrite.AppFolder"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
#: The whole export (token, upload, convert, download) must finish within this many seconds (gunicorn's limit is 60).
TOTAL_SECONDS = 25
#: One HTTP call waits at most this long for Microsoft.
CALL_SECONDS = 15
#: Removing the Word file from OneDrive after the export gets its own short allowance.
DELETE_SECONDS = 8
MAX_PDF_BYTES = 20 * 1024 * 1024
CHUNK = 64 * 1024
#: Hosts Microsoft sends the converted PDF from (the link it redirects to is already signed, so no token goes there).
DOWNLOAD_HOSTS = ("sharepoint.com", "files.1drv.com", "livefilestore.com", "onedrive.com", "onedrive.live.com",
                  "microsoftpersonalcontent.com", "graph.microsoft.com")
#: Files this program leaves in the app folder start with this; the nightly cleanup removes old ones.
FILE_PREFIX = "quill-memo-"
LEFTOVER_AGE = timedelta(hours=1)
SECRET_WARNING_DAYS = 30

NOT_SET_UP = "PDF export is not set up on this site yet."
NOT_CONNECTED = "PDF export is not connected to Microsoft 365. An Admin can connect it in Fee Register > Settings > Word."
RECONNECT = "The Microsoft 365 sign-in has expired or was removed. An Admin can reconnect it in Fee Register > Settings > Word."
BUSY = "Another PDF is being made. Try again in a few seconds."
TIMEOUT = "Microsoft 365 took too long to make the PDF. Try again in a moment."
UNREACHABLE = "Microsoft 365 could not be reached. Try again in a moment."

_lock = threading.Lock()


class PdfError(Exception):
    """A PDF could not be made. ``message`` is safe to show; ``reconnect`` means the sign-in must be made again."""

    def __init__(self, message, reconnect=False):
        super().__init__(message)
        self.message = message
        self.reconnect = reconnect


# ---------------------------------------------------------------------------
# Configuration and stored connection
# ---------------------------------------------------------------------------


def configured():
    """True when the app's ID, secret and token key are all set (``config/settings.py``)."""
    return bool(settings.MS_GRAPH_CLIENT_ID and settings.MS_GRAPH_CLIENT_SECRET and settings.MS_GRAPH_TOKEN_KEY)


def _connection():
    from fees.models import PdfConnection

    return PdfConnection.objects.filter(pk=1).first()


def available():
    """True when a PDF can be asked for: configured and connected. One small query."""
    if not configured():
        return False
    from fees.models import PdfConnection

    return PdfConnection.objects.filter(pk=1).exclude(refresh_token="").exists()


def secret_expires():
    """The date the app's client secret expires (``MS_GRAPH_SECRET_EXPIRES``), or None when not given or not a date."""
    try:
        return datetime.date.fromisoformat(settings.MS_GRAPH_SECRET_EXPIRES) if settings.MS_GRAPH_SECRET_EXPIRES else None
    except ValueError:
        return None


def status():
    """What Fee Register > Settings shows about PDF export (no secrets)."""
    conn = _connection() if configured() else None
    expires = secret_expires()
    today = timezone.localdate()
    return {
        "configured": configured(),
        "connected": bool(conn and conn.refresh_token),
        "account": conn.account if conn else "",
        "connected_at": conn.connected_at if conn else None,
        "connected_by": conn.connected_by if conn else "",
        "last_success_at": conn.last_success_at if conn else None,
        "last_error": conn.last_error if conn else "",
        "last_error_at": conn.last_error_at if conn else None,
        "secret_expires": expires,
        "secret_warning": bool(expires and expires - today <= timedelta(days=SECRET_WARNING_DAYS)),
    }


def disconnect():
    """Forget the Microsoft sign-in. (Microsoft keeps the app listed under the account's app permissions until it is removed there.)"""
    from fees.models import PdfConnection

    PdfConnection.objects.filter(pk=1).delete()


def _fernet():
    from cryptography.fernet import Fernet

    key = base64.urlsafe_b64encode(hashlib.sha256(settings.MS_GRAPH_TOKEN_KEY.encode("utf-8")).digest())
    return Fernet(key)


def _seal(text):
    return _fernet().encrypt(text.encode("utf-8")).decode("ascii") if text else ""


def _unseal(text):
    """The stored token, or "" when it cannot be read (for example the token key was changed: reconnect)."""
    if not text:
        return ""
    from cryptography.fernet import InvalidToken

    try:
        return _fernet().decrypt(text.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""


def _record_success():
    from fees.models import PdfConnection

    PdfConnection.objects.filter(pk=1).update(last_success_at=timezone.now(), last_error="", last_error_at=None)


def _record_error(message):
    from fees.models import PdfConnection

    PdfConnection.objects.filter(pk=1).update(last_error=message[:300], last_error_at=timezone.now())


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Redirects are not followed: the PDF link is checked first and fetched without the token."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _urlopen(request, timeout):
    """The one place this module talks to the internet (tests replace it)."""
    return urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout)


def _remaining(deadline):
    left = deadline - time.monotonic()
    if left <= 0.5:
        raise PdfError(TIMEOUT)
    return min(CALL_SECONDS, left)


def _send(method, url, deadline, token=None, data=None, content_type=None):
    """``(status, headers, response)``. ``response`` is readable (and closed by the caller); an HTTP error status is returned, not raised."""
    request = urllib.request.Request(url, data=data, method=method)
    if token:
        request.add_header("Authorization", "Bearer " + token)
    if content_type:
        request.add_header("Content-Type", content_type)
    request.add_header("Accept", "application/json")
    try:
        response = _urlopen(request, _remaining(deadline))
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc
    except (TimeoutError, socket.timeout):
        raise PdfError(TIMEOUT) from None
    except (urllib.error.URLError, OSError, ValueError):
        raise PdfError(UNREACHABLE) from None
    return getattr(response, "status", None) or response.getcode(), response.headers, response


def _read_json(response, limit=1024 * 1024):
    try:
        raw = response.read(limit)
    except (OSError, ValueError):
        return {}
    finally:
        _close(response)
    try:
        data = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _close(response):
    try:
        response.close()
    except Exception:  # noqa: BLE001 - closing must never turn into a failure of the export
        pass


def _graph_failure(status_code, headers, response):
    """The :class:`PdfError` for a Microsoft Graph error answer."""
    data = _read_json(response)
    if status_code == 401:
        return PdfError(RECONNECT, reconnect=True)
    if status_code in (429, 503):
        wait = (headers.get("Retry-After") or "").strip() if headers else ""
        later = f"in {wait} seconds" if wait.isdigit() else "in a minute"
        return PdfError(f"Microsoft 365 is busy. Try again {later}.")
    error = data.get("error") if isinstance(data.get("error"), dict) else {}
    detail = str(error.get("message") or error.get("code") or f"error {status_code}")[:160]
    return PdfError(f"Microsoft 365 could not make the PDF ({detail}).")


# ---------------------------------------------------------------------------
# Sign-in
# ---------------------------------------------------------------------------


def _endpoint(name):
    return f"{LOGIN_HOST}/{urllib.parse.quote(settings.MS_GRAPH_TENANT, safe='')}/oauth2/v2.0/{name}"


def start_sign_in(redirect_uri):
    """``(url, state, verifier)``: the Microsoft sign-in address, and the two values the callback must check (kept in the session)."""
    if not configured():
        raise PdfError(NOT_SET_UP)
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    query = urllib.parse.urlencode({
        "client_id": settings.MS_GRAPH_CLIENT_ID, "response_type": "code", "redirect_uri": redirect_uri, "response_mode": "query",
        "scope": SCOPES, "state": state, "code_challenge": challenge, "code_challenge_method": "S256", "prompt": "select_account",
    })
    return f"{_endpoint('authorize')}?{query}", state, verifier


def _token_call(fields, deadline):
    """POST to the token endpoint; the JSON answer, or :class:`PdfError`."""
    body = urllib.parse.urlencode({"client_id": settings.MS_GRAPH_CLIENT_ID, "client_secret": settings.MS_GRAPH_CLIENT_SECRET,
                                   "scope": SCOPES, **fields}).encode("ascii")
    status_code, _headers, response = _send("POST", _endpoint("token"), deadline, data=body,
                                            content_type="application/x-www-form-urlencoded")
    data = _read_json(response)
    if status_code == 200 and data.get("access_token"):
        return data
    if data.get("error") in ("invalid_grant", "interaction_required", "consent_required"):
        raise PdfError(RECONNECT, reconnect=True)
    if data.get("error") == "invalid_client":
        raise PdfError("Microsoft refused the app's ID or secret. Check MS_GRAPH_CLIENT_ID and MS_GRAPH_CLIENT_SECRET (the secret may have expired).")
    raise PdfError(UNREACHABLE if status_code >= 500 else "Microsoft refused the sign-in. Try Connect again.")


def _account_of(id_token):
    """The email (or name) in the sign-in's ID token. It came straight from Microsoft over HTTPS, so it is only read, not verified."""
    try:
        payload = id_token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError, AttributeError):
        return ""
    if not isinstance(claims, dict):
        return ""
    return str(claims.get("email") or claims.get("preferred_username") or claims.get("name") or "")[:200]


def _store_tokens(conn, data):
    conn.access_token = _seal(data["access_token"])
    conn.access_expires_at = timezone.now() + timedelta(seconds=max(60, int(data.get("expires_in") or 3600)) - 60)
    if data.get("refresh_token"):
        conn.refresh_token = _seal(data["refresh_token"])


def finish_sign_in(code, verifier, redirect_uri, who):
    """Exchange the code from Microsoft's callback for tokens and save the connection. Returns the account's email."""
    from fees.models import PdfConnection

    if not configured():
        raise PdfError(NOT_SET_UP)
    data = _token_call({"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri, "code_verifier": verifier},
                       time.monotonic() + TOTAL_SECONDS)
    if not data.get("refresh_token"):
        raise PdfError("Microsoft did not allow the site to stay signed in. Try Connect again and accept the permissions.")
    conn = PdfConnection.objects.filter(pk=1).first() or PdfConnection(pk=1)
    _store_tokens(conn, data)
    conn.account = _account_of(data.get("id_token", ""))
    conn.connected_at = timezone.now()
    conn.connected_by = (who or "")[:150]
    conn.last_error, conn.last_error_at = "", None
    conn.save()
    return conn.account


def _access_token(deadline, force=False):
    """A valid access token, refreshed (and the refresh token renewed) when needed. A dead sign-in is forgotten."""
    from fees.models import PdfConnection

    conn = _connection()
    refresh = _unseal(conn.refresh_token) if conn else ""
    if not refresh:
        raise PdfError(NOT_CONNECTED if not conn or not conn.refresh_token else RECONNECT, reconnect=bool(conn))
    if not force and conn.access_expires_at and conn.access_expires_at > timezone.now():
        token = _unseal(conn.access_token)
        if token:
            return token
    try:
        data = _token_call({"grant_type": "refresh_token", "refresh_token": refresh}, deadline)
    except PdfError as err:
        if err.reconnect:
            PdfConnection.objects.filter(pk=1).update(refresh_token="", access_token="", access_expires_at=None)
        raise
    _store_tokens(conn, data)
    PdfConnection.objects.filter(pk=1).update(access_token=conn.access_token, access_expires_at=conn.access_expires_at,
                                              refresh_token=conn.refresh_token)
    return data["access_token"]


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------


def _upload(token, data, deadline):
    name = f"{FILE_PREFIX}{uuid.uuid4().hex}.docx"
    url = f"{GRAPH}/me/drive/special/approot:/{name}:/content"
    status_code, headers, response = _send("PUT", url, deadline, token=token, data=data, content_type=DOCX_TYPE)
    if status_code not in (200, 201):
        raise _graph_failure(status_code, headers, response)
    item_id = _read_json(response).get("id")
    if not item_id:
        raise PdfError("Microsoft 365 did not accept the Word file.")
    return str(item_id)


def allowed_download(url):
    """True for an HTTPS address on a Microsoft download host."""
    parts = urllib.parse.urlparse(url or "")
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(host == h or host.endswith("." + h) for h in DOWNLOAD_HOSTS)


def _stream_pdf(response, deadline):
    """The PDF body in a temporary file (at the start), within the size and time limits."""
    out = tempfile.TemporaryFile()
    size = 0
    try:
        while True:
            if time.monotonic() > deadline:
                raise PdfError(TIMEOUT)
            try:
                chunk = response.read(CHUNK)
            except (TimeoutError, socket.timeout):
                raise PdfError(TIMEOUT) from None
            except OSError:
                raise PdfError(UNREACHABLE) from None
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_PDF_BYTES:
                raise PdfError("The PDF Microsoft 365 made is larger than 20 MB, so it was not sent.")
            out.write(chunk)
        out.seek(0)
        if out.read(5) != b"%PDF-":
            raise PdfError("Microsoft 365 did not send a PDF.")
        out.seek(0)
        return out
    except BaseException:
        out.close()
        raise
    finally:
        _close(response)


def _download_pdf(token, item_id, deadline):
    url = f"{GRAPH}/me/drive/items/{urllib.parse.quote(item_id, safe='')}/content?format=pdf"
    status_code, headers, response = _send("GET", url, deadline, token=token)
    if status_code == 200:
        return _stream_pdf(response, deadline)
    if status_code in (301, 302, 303, 307, 308):
        location = headers.get("Location", "") if headers else ""
        _close(response)
        if not allowed_download(location):
            raise PdfError("Microsoft 365 sent the PDF from an address this site does not trust.")
        status_code, headers, response = _send("GET", location, deadline)   # the link is signed: no token is sent
        if status_code == 200:
            return _stream_pdf(response, deadline)
    raise _graph_failure(status_code, headers, response)


def _delete(token, item_id):
    """Remove the Word file from OneDrive. Failures are ignored here; the nightly cleanup catches anything left."""
    try:
        _status, _headers, response = _send("DELETE", f"{GRAPH}/me/drive/items/{urllib.parse.quote(item_id, safe='')}",
                                            time.monotonic() + DELETE_SECONDS, token=token)
        _close(response)
    except PdfError:
        pass


def convert(docx_bytes):
    """The PDF of a Word file, as a temporary file at its start. Raises :class:`PdfError` (with the reason) on any failure."""
    if not configured():
        raise PdfError(NOT_SET_UP)
    if not _lock.acquire(blocking=False):
        raise PdfError(BUSY)
    try:
        deadline = time.monotonic() + TOTAL_SECONDS
        token = _access_token(deadline)
        item_id = _upload(token, docx_bytes, deadline)
        try:
            pdf = _download_pdf(token, item_id, deadline)
        finally:
            _delete(token, item_id)
        _record_success()
        return pdf
    except PdfError as err:
        _record_error(err.message)
        raise
    finally:
        _lock.release()


def keep_alive():
    """The nightly step: renew the sign-in (so it never reaches Microsoft's 90 days unused) and remove files older than an hour from
    the app folder. Returns the number removed; :class:`PdfError` when the sign-in cannot be renewed."""
    if not configured() or not _connection():
        return 0
    deadline = time.monotonic() + TOTAL_SECONDS * 2
    token = _access_token(deadline, force=True)
    status_code, headers, response = _send("GET", f"{GRAPH}/me/drive/special/approot/children?$select=id,name,createdDateTime&$top=200",
                                           deadline, token=token)
    if status_code != 200:
        raise _graph_failure(status_code, headers, response)
    cutoff = timezone.now() - LEFTOVER_AGE
    removed = 0
    for item in _read_json(response, limit=4 * 1024 * 1024).get("value") or []:
        name = str(item.get("name") or "")
        created = _parse_time(item.get("createdDateTime"))
        if name.startswith(FILE_PREFIX) and item.get("id") and created is not None and created < cutoff:
            _delete(token, str(item["id"]))
            removed += 1
    return removed


def _parse_time(text):
    try:
        return datetime.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
