"""Clear a profile's transaction history (owner round 2026-11): Settings > General > Clear transaction history, Admin only.

Deletes every record of trading in the profile: purchases and sales (awaiting ones too), transfers, fund switches, dividends, SIP
schedules, folio numbers, alternative investments' dated values, corporate action confirmations and saved alert states; and, if
asked, the History log. Kept: the investments listed in the profile (with notes, links and sector index), portfolios, brokers,
guardrails, settings, and everything shared (investments, prices, indices). A "Before clearing profile" backup is taken first and
nothing is deleted if it cannot be made; restoring that backup brings everything back.
"""
from django.db import transaction

from investments.errors import InvestmentsError, forbidden
from investments.models import (
    AlertState, AltValue, CorporateActionResponse, Dividend, Folio, InvestmentHistory, InvestmentsStatsCache, SipSchedule, Switch,
    Transaction, Transfer,
)
from investments.services import core

#: (label, model), in the order they are deleted (protected links first).
RECORDS = (
    ("Purchases and sales", Transaction), ("Transfers", Transfer), ("Fund switches", Switch), ("Dividends", Dividend),
    ("SIP schedules", SipSchedule), ("Folio numbers", Folio), ("Alternative investment values", AltValue),
    ("Corporate action confirmations", CorporateActionResponse), ("Saved alert states", AlertState),
)


def preview(profile):
    """``[(label, count)]`` of what clearing would delete, and the History count."""
    rows = [(label, model.objects.filter(profile=profile).count()) for label, model in RECORDS]
    return rows, InvestmentHistory.objects.filter(profile=profile).count()


def clear(profile, user, confirm_name, include_history=False):
    """Back up, then delete the profile's transaction history. Returns ``{label: rows deleted}``."""
    from backups import services as backup_services

    if not getattr(user, "is_admin", False):
        raise forbidden("Only an Admin can clear the transaction history.")
    if (confirm_name or "").strip() != profile.name:
        raise InvestmentsError("CONFIRM_NAME", "Nothing was deleted. Type the profile's name exactly to confirm.", 400)
    try:
        backup_services.create_backup("pre_clear", user)
    except Exception as exc:
        raise InvestmentsError("BACKUP_FAILED", f"The safety backup could not be made, so nothing was deleted. ({exc})", 500)
    counts = {}
    with transaction.atomic():
        Transaction.objects.filter(profile=profile).update(switch=None)
        for label, model in RECORDS:
            counts[label] = model.objects.filter(profile=profile).delete()[0]
        if include_history:
            counts["History entries"] = InvestmentHistory.objects.filter(profile=profile).delete()[0]
        InvestmentsStatsCache.objects.filter(profile=profile).delete()
        core.touch(profile)
    return {k: v for k, v in counts.items() if v}
