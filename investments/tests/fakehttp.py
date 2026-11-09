"""A fake internet for the adapter tests: routes a URL to a recorded fixture, a canned status or a failure. No test calls a live service."""
import io
import urllib.error
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_bytes()


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class FakeNet:
    """``routes`` is a list of ``(substring, handler)``; a handler is bytes, an int status, or a list of those used in turn."""

    def __init__(self, routes=None):
        self.routes = list(routes or [])
        self.calls = []
        self.sleeps = []
        self.agents = []

    def add(self, needle, *answers):
        self.routes.append((needle, list(answers)))

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.calls.append(url)
        self.agents.append(request.get_header("User-agent"))
        for needle, answers in self.routes:
            if needle in url:
                answer = answers[0] if len(answers) == 1 else answers.pop(0)
                if isinstance(answer, int):
                    raise urllib.error.HTTPError(url, answer, "error", {}, io.BytesIO(b"err"))
                if isinstance(answer, Exception):
                    raise answer
                return FakeResponse(answer)
        raise urllib.error.HTTPError(url, 404, "no route in the fake net", {}, io.BytesIO(b""))
