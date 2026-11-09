"""The permanent edit history (plan 6 and 16.4).

``record`` writes one ``InvestmentHistory`` row holding a full JSON snapshot of the record at that version. Rows are never
changed or removed by this program. A deleted entry can be restored from its ``delete`` row (``restore``): the row is
re-created with the same id and the whole history is re-checked first, so a restore that would break a selling limit is refused.
"""
import datetime
import uuid
from decimal import Decimal

from django.db import transaction
from django.db.models import Max

from investments.errors import InvestmentsError, not_found
from investments.models import (
    AltValue, CorporateActionResponse, Dividend, Folio, InvestmentHistory, Switch, Transaction, Transfer, new_group,
)

#: record_type -> model. Only these are logged (plan 6: transactions, dividends, corporate action confirmations, folio
#: numbers, alternative investment values; the later phases add dividends and confirmations here).
RECORD_MODELS = {
    "transaction": Transaction,
    "transfer": Transfer,
    "switch": Switch,
    "folio": Folio,
    "altvalue": AltValue,
    "dividend": Dividend,
    "ca_response": CorporateActionResponse,
}
TYPE_LABELS = {"transaction": "Transaction", "transfer": "Transfer", "switch": "Switch", "folio": "Folio number",
               "altvalue": "Alternative value",
               "dividend": "Dividend", "ca_response": "Corporate action confirmation"}


def record_type_of(obj):
    for name, model in RECORD_MODELS.items():
        if isinstance(obj, model):
            return name
    raise ValueError(f"{type(obj).__name__} is not a logged record")


def _plain(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def snapshot_of(obj):
    """All the record's columns as JSON-safe values (foreign keys as ids, Decimals as text)."""
    return {f.attname: _plain(getattr(obj, f.attname)) for f in obj._meta.concrete_fields}


def _instrument_id(obj, snap):
    if "instrument_id" in snap:
        return snap.get("instrument_id")
    action = getattr(obj, "action", None)
    return getattr(action, "instrument_id", None)


def record(profile, user, obj, kind, group=None, summary=""):
    """Log ``obj`` (its current values, or its last values for a delete) as a new version."""
    rtype = record_type_of(obj)
    last = InvestmentHistory.objects.filter(profile=profile, record_type=rtype, record_id=obj.pk).aggregate(m=Max("version"))["m"] or 0
    snap = snapshot_of(obj)
    return InvestmentHistory.objects.create(
        profile=profile, record_type=rtype, record_id=obj.pk, version=last + 1, snapshot=snap, change_kind=kind,
        changed_by=user if getattr(user, "pk", None) else None, group=group, summary=summary[:300],
        instrument_id_ref=_instrument_id(obj, snap),
    )


def previous_snapshot(profile, obj):
    """The snapshot before the newest version of ``obj`` (used to show old and new values), or None."""
    rtype = record_type_of(obj)
    rows = list(InvestmentHistory.objects.filter(profile=profile, record_type=rtype, record_id=obj.pk).order_by("-version")[:2])
    return rows[1].snapshot if len(rows) == 2 else None


def diff(old, new):
    """``[(field, old, new)]`` for the fields that differ between two snapshots."""
    out = []
    for key in sorted(set(old or {}) | set(new or {})):
        if (old or {}).get(key) != (new or {}).get(key):
            out.append((key, (old or {}).get(key), (new or {}).get(key)))
    return out


def rows_for(profile, instrument_id=None, record_type=None, limit=500):
    qs = InvestmentHistory.objects.filter(profile=profile).select_related("changed_by")
    if instrument_id:
        qs = qs.filter(instrument_id_ref=instrument_id)
    if record_type:
        qs = qs.filter(record_type=record_type)
    return qs.order_by("-changed_at", "-id")[:limit]


def can_restore(profile, row):
    """True for a ``delete`` or ``cancel`` row whose record has not already been brought back."""
    if row.change_kind not in ("delete", "cancel") or row.profile_id != profile.pk:
        return False
    model = RECORD_MODELS[row.record_type]
    if model.objects.filter(pk=row.record_id).exists():
        return False
    newest = InvestmentHistory.objects.filter(profile=profile, record_type=row.record_type, record_id=row.record_id).order_by("-version").first()
    return newest.pk == row.pk


@transaction.atomic
def restore(profile, user, history_id):
    """Bring a deleted record back with its old id. Refused if the history would no longer hold together."""
    from investments.services import transactions as txn_service

    row = InvestmentHistory.objects.filter(pk=history_id, profile=profile).first()
    if row is None:
        raise not_found("history entry")
    if not can_restore(profile, row):
        raise InvestmentsError("CANNOT_RESTORE", "This entry cannot be restored (it was not deleted, or it is already back).", 409)
    model = RECORD_MODELS[row.record_type]
    values = {}
    for f in model._meta.concrete_fields:
        raw = row.snapshot.get(f.attname)
        values[f.attname] = f.to_python(raw) if raw is not None else None
    obj = model(**values)
    if isinstance(obj, (Transaction, Transfer)):
        txn_service.verify_restored(profile, obj)
    obj.save(force_insert=True)
    record(profile, user, obj, "restore", group=new_group(), summary=f"Restored from history entry {row.pk}")
    from investments.services.core import touch

    if isinstance(obj, Transaction):
        txn_service._pin(profile, obj)
    touch(profile)
    return obj
