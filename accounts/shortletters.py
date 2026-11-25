"""The letters shown after shortened numbers (thousands, lacs, crores), chosen by each user (Settings > Display > My Display).

No Django imports, so the money formatters of the Fee Register and Investments can use it. ``accounts.middleware.ShortLettersMiddleware``
sets the signed-in user's letters for the length of a request; with nothing set the standard k, lac and cr are used. A blank box means
the standard letters for that unit.
"""
import contextvars

DEFAULTS = {"thousands": "k", "lac": "lac", "crore": "cr"}
MAX_LENGTH = 12

_current = contextvars.ContextVar("short_letters", default=None)


def get():
    """``{"thousands": ..., "lac": ..., "crore": ...}`` for the current request (the standard letters when none were chosen)."""
    chosen = _current.get() or {}
    return {key: (chosen.get(key) or "").strip() or default for key, default in DEFAULTS.items()}


def thousands():
    return get()["thousands"]


def lac():
    return get()["lac"]


def crore():
    return get()["crore"]


def use(letters):
    """Make ``letters`` (a dict that may leave a unit blank) the current ones; returns a token for :func:`release`."""
    return _current.set(dict(letters))


def release(token):
    _current.reset(token)


def valid(text):
    """True for letters a person may choose: up to 12 characters, letters, spaces, a dot or a hyphen (no digits, commas or markup)."""
    return len(text) <= MAX_LENGTH and all(ch.isalpha() or ch in " .-" for ch in text)
