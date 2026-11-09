"""The only place the program talks to the internet: standard-library ``urllib``, a short timeout, a short browser-like
``User-Agent`` (a long one was refused by Yahoo from Render, plan 30), and retry with growing delay and some randomness
(plan 15.2). Tests replace ``_urlopen`` and ``sleep``; no test ever calls a live service.
"""
import random
import time
import urllib.error
import urllib.request

from .base import FetchError

USER_AGENT = "Mozilla/5.0"
TIMEOUT = 15
_urlopen = urllib.request.urlopen
sleep = time.sleep


def _request(url, headers=None):
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*", **(headers or {})})


def open_url(url, *, timeout=TIMEOUT, headers=None):
    """An open response (a file-like object to stream). Raises :class:`FetchError`."""
    try:
        return _urlopen(_request(url, headers), timeout=timeout)
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
