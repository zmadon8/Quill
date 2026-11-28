"""The memos and allocations that count in the Fee Register's figures (owner round 2026-12).

A matter can be marked "Leave out of Statistics" (``Matter.exclude_from_statistics``). Its memos and the payments made to them
are then left out of Statistics, the Dashboard boxes and charts, the Year-End summary, the Home cards and the Excel exports of
those figures. They stay everywhere else: the Memos list, Feebook, Outstanding, History, search, Word and PDF memos, and the Excel
backup.

Every aggregate figure starts from one of these two querysets, so the rule is kept in one place. Both return an ordinary
queryset: filter and annotate it as usual.
"""
from django.db.models import Exists, OuterRef

from fees.models import Allocation, Memo, Payment

__all__ = ["memos", "allocations", "payments"]


def memos(profile):
    """The profile's memos (drafts too; filter ``is_draft`` as needed) whose matter is not left out of the figures."""
    return Memo.objects.filter(profile=profile, matter__exclude_from_statistics=False)


def allocations(profile):
    """The profile's payment allocations to memos whose matter is not left out of the figures."""
    return Allocation.objects.filter(profile=profile, memo__matter__exclude_from_statistics=False)


def payments(profile):
    """The profile's payments that count: one with an allocation to a counted memo, or with no allocation at all.

    A payment applied only to memos of left-out matters does not count; one shared between a left-out matter and another counts once.
    """
    counted = allocations(profile).filter(payment_id=OuterRef("pk"))
    any_allocation = Allocation.objects.filter(payment_id=OuterRef("pk"))
    return Payment.objects.filter(profile=profile).filter(Exists(counted) | ~Exists(any_allocation))
