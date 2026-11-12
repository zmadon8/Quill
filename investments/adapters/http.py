"""The only place the program talks to the internet: standard-library ``urllib``, a short timeout, a short browser-like
``User-Agent`` (a long one was refused by Yahoo from Render, plan 30), and retry with growing delay and some randomness
(plan 15.2). Tests replace ``_urlopen`` and ``sleep``; no test ever calls a live service.
"""
import ipaddress
import random
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from .base import FetchError

USER_AGENT = "Mozilla/5.0"
TIMEOUT = 15


def check_public(url):
    """Refuse an address whose host is, or resolves to, a loopback, private, link-local or otherwise non-public address
    (the server must not be made to read its own network). Raises :class:`FetchError`."""
    host = urllib.parse.urlparse(url).hostname
    if not host:
        raise FetchError("The address has no host.")
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise FetchError(f"Could not resolve {host}: {exc}", retryable=True) from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global:
            raise FetchError(f"{host} is not a public address, so it was not fetched.")


class _GuardedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_public(urllib.parse.urljoin(req.full_url, newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _safe_urlopen(request, timeout=None):
    """``urlopen`` that checks the host first and every redirect hop (tests replace ``_urlopen``, so they never resolve a name)."""
    check_public(request.full_url)
    return urllib.request.build_opener(_GuardedRedirect).open(request, timeout=timeout)


_urlopen = _safe_urlopen
sleep = time.sleep


def _request(url, headers=None):
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*", **(headers or {})})


def open_url(url, *, timeout=TIMEOUT, headers=None):
    """An open response (a file-like object to stream). Raises :class:`FetchError`."""
    try:
        return _urlopen(_request(url, headers), timeout=timeout)
    except FetchError:
        raise
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code} from {url.split('?')[0]}", status=exc.code, retryable=exc.code == 429 or exc.code >= 500) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise FetchError(f"Could not reach {url.split('?')[0]}: {exc}", retryable=True) from exc


def get(url, *, timeout=TIMEOUT, headers=None, max_bytes=20_000_000):
    """The body of ``url`` as bytes (capped)."""
    with open_url(url, timeout=timeout, headers=headers) as response:
        body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise FetchError("The answer was larger than expected, so it was not read.")
    return body


def with_retry(fn, *, tries=3, base=2.0, rng=random.random):
    """Call ``fn()``; on a retryable failure wait ``base * 2**attempt`` plus up to a second and try again. Gives up after ``tries``."""
    last = None
    for attempt in range(tries):
        try:
            return fn()
        except FetchError as exc:
            last = exc
            if not exc.retryable or attempt == tries - 1:
                raise
            sleep(base * (2 ** attempt) + rng())
    raise last  # pragma: no cover
