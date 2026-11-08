"""Small shared helpers for the statistics package (internal).

Keeps the ``maxFy`` semantics and a couple of constants in one place so the
submodules agree. No Django imports here; the FY string comparison is plain
lexical (FY labels sort chronologically as fixed-width ``YYYY-YY`` strings).
"""
from __future__ import annotations

__all__ = ["max_fy", "FY_RE", "is_fy_label"]

import re

#: A financial-year label looks like ``2026-27``.
FY_RE = re.compile(r"^\d{4}-\d{2}$")


def is_fy_label(value) -> bool:
    """Whether ``value`` is a ``YYYY-YY`` financial-year label."""
    return bool(FY_RE.match(str(value)))


def max_fy(a, b):
    """The larger (later) of two FY strings; a falsy value is ignored (TS ``maxFy``).

    ``maxFy('', x) == x`` and ``maxFy(x, None) == x``; when both are present the
    later string wins (plain lexical compare, since FY labels are fixed width).
    """
    if not a:
        return b
    if not b:
        return a
    return a if a >= b else b
