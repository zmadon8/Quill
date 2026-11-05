"""Per-request Fee Register scope helpers (design section 11).

A view resolves the signed-in user's Fee Register profile and its settings once per request and reuses
them. ``context(request)`` returns ``(profile, settings)`` and caches the pair on ``request._fees_ctx``
so a page does not look them up twice. No view uses these yet (views are Phase 7); they are here so the
schema tests and later services share one way in.
"""
from accounts.profiles import request_profile
from accounts.suite import KEY_FEES


def for_profile(request):
    """The signed-in user's Fee Register profile for this request, or None if they have none."""
    return request_profile(request, KEY_FEES)


def context(request):
    """``(profile, settings)`` for the request, cached on ``request._fees_ctx``.

    ``profile`` is the user's Fee Register profile (or None). When there is a profile, ``settings`` is its
    ``FeesSettings`` row, created with defaults the first time it is needed; with no profile ``settings``
    is None.
    """
    cached = getattr(request, "_fees_ctx", None)
    if cached is not None:
        return cached
    from .models import FeesSettings

    profile = for_profile(request)
    settings = None
    if profile is not None:
        settings, _created = FeesSettings.objects.get_or_create(profile=profile)
    result = (profile, settings)
    request._fees_ctx = result
    return result
