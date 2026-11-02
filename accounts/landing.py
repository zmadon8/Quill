"""Where a user lands after signing in: Home (the default) or one program chosen in My settings."""
from django.urls import reverse

from . import suite
from .profiles import get_profile_for

#: URL name of the first page of each program, by program key.
PROGRAM_LANDING_URLS = {suite.KEY_DIARY: "diary_home"}
#: Programs in the order they are offered.
PROGRAM_KEYS = [suite.KEY_DIARY]


def program_choices(programs=None):
    """``[("", Home name), (key, program name), ...]`` for ``programs`` (default: every program)."""
    names = suite.get_names()
    keys = PROGRAM_KEYS if programs is None else programs
    return [("", names[suite.KEY_HOME])] + [(key, names[key]) for key in keys]


def programs_for(user):
    """Program keys the user has a live profile for."""
    return [key for key in PROGRAM_KEYS if get_profile_for(user, key) is not None]


def landing_url(user):
    """The page to open after sign-in: the chosen program if the user still has a profile in it, else Home."""
    key = getattr(user, "landing_program", "")
    if key in PROGRAM_LANDING_URLS:
        profile = get_profile_for(user, key)
        if profile is not None:
            if key == suite.KEY_DIARY:
                from diary.opening import opening_url  # lazy: diary imports accounts

                return opening_url(user, profile)
            return reverse(PROGRAM_LANDING_URLS[key])
    return reverse("home")

