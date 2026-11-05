"""Where a user lands after signing in: Home (the default) or one program chosen in My settings."""
from django.urls import reverse

from . import programs, suite
from .profiles import get_profile_for

#: Programs in the order they are offered, and the URL name of each one's first page. Both are derived
#: from the program registry, so a program added there appears here without editing this module.
PROGRAM_KEYS = programs.program_keys()
PROGRAM_LANDING_URLS = {key: programs.get_program(key).landing_url_name for key in PROGRAM_KEYS}


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

