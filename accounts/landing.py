"""Where a user lands after signing in: Home (the default) or one program chosen in My settings.

The program list and each program's first page are read from the program registry on every call (not
snapshotted at import time), so a program that registers itself from its app ``ready()`` after this
module is first imported still shows up here.
"""
from django.urls import reverse

from . import programs, suite
from .profiles import get_profile_for

def program_keys():
    """Programs in the order they are offered. Derived from the registry on every call, so a program that
    registers itself from its app ``ready()`` (after this module is imported) still appears here."""
    return programs.program_keys()


def landing_url_name(key):
    """The URL name of ``key``'s first page, or None if the program is not registered."""
    program = programs.get_program(key)
    return program.landing_url_name if program is not None else None


def program_choices(program_keys_=None):
    """``[("", Home name), (key, program name), ...]`` for the given keys (default: every registered program)."""
    names = suite.get_names()
    keys = program_keys() if program_keys_ is None else program_keys_
    return [("", names[suite.KEY_HOME])] + [(key, names[key]) for key in keys]


def programs_for(user):
    """Program keys the user has a live profile for."""
    return [key for key in program_keys() if get_profile_for(user, key) is not None]


def landing_url(user):
    """The page to open after sign-in: the chosen program if the user still has a profile in it, else Home."""
    key = getattr(user, "landing_program", "")
    url_name = landing_url_name(key)
    if url_name is not None:
        profile = get_profile_for(user, key)
        if profile is not None:
            if key == suite.KEY_DIARY:
                from diary.opening import opening_url  # lazy: diary imports accounts

                return opening_url(user, profile)
            return reverse(url_name)
    return reverse("home")

