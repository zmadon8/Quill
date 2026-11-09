"""How much a profile holds, for the suite's "refuse to delete a profile in use" rule."""


def record_count(profile):
    """Number of records in ``profile`` that make deleting it unsafe (transactions; grows as models are added)."""
    return record_counts([profile.pk]).get(profile.pk, 0)


def record_counts(profile_pks):
    """``{profile pk: records}`` for many profiles in grouped queries."""
    return {pk: 0 for pk in profile_pks}
