"""Per-request Investments profile helper (the same idea as ``fees.scope``)."""
from accounts.profiles import request_profile
from accounts.suite import KEY_INVESTMENTS


def for_profile(request):
    """The signed-in user's Investments profile for this request, or None if they have none."""
    return request_profile(request, KEY_INVESTMENTS)
