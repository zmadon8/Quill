"""The program registry (design section 10).

A "program" is one application inside the suite (today only the Case Law Diary; the Fee
Register is added in a later step). Shared-core code (the Admin Profiles and Users screens,
the profile switch, the landing redirect, the context processors, the profile purge and clear)
asks this registry which programs exist instead of hardcoding the diary, so a second program can
be added later without touching those screens.

With only the diary registered the behaviour of every screen is identical to before: the registry
returns the diary and nothing else.
"""
from dataclasses import dataclass
from typing import Callable

from .suite import KEY_DIARY, KEY_FEES


@dataclass(frozen=True)
class Program:
    """One program in the suite.

    ``key`` is the fixed internal identifier (also the value stored on ``Profile.program`` and the
    URL namespace). ``landing_url_name`` is the URL name of the program's first page. ``profile_models``
    is a zero-argument callable returning the model labels (``"app.Model"``) that carry a ``profile``
    column, parents first (delete children first by reversing); it is lazy so the backups registry is
    read only when needed, never at import time.
    """

    key: str
    landing_url_name: str
    profile_models: Callable[[], list]


def _diary_profile_models():
    from backups import registry

    return list(registry.PROFILE_MODELS)


#: Step A (this task): the diary only. The Fee Register registers itself later (design 10.2 step C).
PROGRAMS = {
    KEY_DIARY: Program(
        key=KEY_DIARY,
        landing_url_name="diary_home",
        profile_models=_diary_profile_models,
    ),
}


def register_program(program):
    """Add ``program`` to the registry (idempotent; a second call with the same key replaces it).

    A program registers itself from its app ``ready()`` (design 10.2 step C), so the shared-core
    screens pick it up without any edit here. Registration must not call ``reverse`` or touch the
    database: it only records the program's key, its landing URL name and its lazy ``profile_models``
    callable. The diary (step A above) is registered at import time; a later program appends itself.
    """
    PROGRAMS[program.key] = program
    return program


def fees_enabled():
    """True when the Fee Register is switched on (``settings.FEES_ENABLED``, read on every call)."""
    from django.conf import settings

    return bool(getattr(settings, "FEES_ENABLED", True))


def is_enabled(key):
    """True when program ``key`` is offered to users. Only the Fee Register can be switched off."""
    return key != KEY_FEES or fees_enabled()


def enabled_program_keys():
    """The registered program keys that are switched on, in registration order. Use this for anything that
    offers or opens a program; use ``program_keys`` where existing data must still be reached."""
    return [key for key in PROGRAMS if is_enabled(key)]


def program_keys():
    """The registered program keys, in registration order."""
    return list(PROGRAMS)


def get_program(key):
    """The ``Program`` for ``key``, or None if it is not registered."""
    return PROGRAMS.get(key)
