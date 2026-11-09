"""How much a profile holds, for the suite's "refuse to delete a profile in use" rule."""
from django.db.models import Count


def record_counts(profile_pks):
    """``{profile pk: number of transactions}`` for many profiles in one grouped query."""
    from investments.models import Transaction

    counts = dict(Transaction.objects.filter(profile_id__in=list(profile_pks)).values_list("profile_id").annotate(n=Count("pk")).order_by())
    return {pk: counts.get(pk, 0) for pk in profile_pks}


def record_count(profile):
    """Number of records in ``profile`` that make deleting it unsafe (transactions)."""
    return record_counts([profile.pk])[profile.pk]
