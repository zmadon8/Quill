"""The Written off memos switch (``FeesSettings.written_off_enabled``) for code that reads memos without reading settings.

With the switch off, every ``Memo.written_off`` flag is ignored (a written-off memo is an ordinary unpaid one) but nothing is
deleted, so switching back on shows the write-offs again. Services that already read ``FeesSettings`` take the switch from
that one read. The ledger and the exports annotate their memo query instead, which keeps their query counts unchanged.
"""
from django.db.models import Exists, OuterRef

from fees.models import FeesSettings

__all__ = ["annotate_switch", "is_written_off"]


def annotate_switch(queryset):
    """``queryset`` of memos with ``write_off_switched_off`` (True when the memo's profile has the feature off)."""
    return queryset.annotate(
        write_off_switched_off=Exists(
            FeesSettings.objects.filter(profile_id=OuterRef("profile_id"), written_off_enabled=False)
        )
    )


def is_written_off(memo):
    """Whether an annotated memo counts as written off: flagged, and the feature is on."""
    return bool(memo.written_off) and not memo.write_off_switched_off
