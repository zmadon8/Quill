"""Investments tests. No test may reach the internet (plan rule: no live price calls in tests): the only network function is replaced
here by one that refuses at once; a test that needs answers patches in ``investments.tests.fakehttp.FakeNet``."""
import io
import urllib.error

from investments.adapters import http


def _no_network(request, timeout=None):
    raise urllib.error.HTTPError(getattr(request, "full_url", str(request)), 403, "network disabled in tests", {}, io.BytesIO(b""))


http._urlopen = _no_network
