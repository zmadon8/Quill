"""Firm and Group services for the Fee Register (R-FIRM-1 to R-FIRM-5, brief 5.12).

Ports ``firmService.ts`` to the Django ORM. Every function takes ``profile``
explicitly (``accounts.Profile``) as its first argument and never reads the
request or settings globally: a profile is one separate Fee Register, so every
query is scoped to it. The UI always says "Group" but the model/table is
``Group`` (DB table "partners"); the ORIGINAL error codes say PARTNER
(``INVALID_PARTNER_NAME``, ``DUPLICATE_PARTNER_NAME``, ``PARTNER_NOT_FOUND``,
``TOO_MANY_PARTNERS``) and are kept verbatim so the ported toast strings line up
(R-FIRM-1, brief 15).

Deviation from the original noted deliberately: ``firmService.ts`` DERIVED a
firm's status from its matters; the Django model STORES ``status`` and it is set
manually (porting brief section 4, R-FIRM-5). ``list_firms`` filters and
``set_firm_status`` writes the stored column.

Return shapes (consistent across this module):

* ``create_firm`` / ``set_firm_status`` / ``update_firm`` return the ``Firm``
  instance.
* ``list_firms`` returns a ``Firm`` queryset ordered by ``Lower(name)``.
* ``get_firm`` returns a ``dict`` detail: ``{"firm": Firm, "groups": [Group],
  "matters": [dict]}`` where each matter dict carries ``matter`` (the ``Matter``
  instance), ``memo_status`` (``"Paid"`` / ``"Unpaid"`` / ``"Overdue"`` / None)
  and ``has_written_off``.
* ``add_group`` / ``update_group`` return the ``Group`` instance;
  ``remove_group`` returns ``None``.
* ``matter_rollups`` returns ``{matter_id: {"memo_status": ..., "has_written_off":
  bool}}``.
* ``recent_matters`` returns a list of dicts (see its docstring).

Transactions: ``create_firm`` wraps the firm insert AND the same-named group
insert in one ``transaction.atomic()`` (R-FIRM-2). Uniqueness is checked
case-insensitively in Python first (so the user gets a clean ``DUPLICATE_*``
error, brief 15 Q2) with the DB ``UniqueConstraint(Lower(name), scope)`` as the
backstop.

Efficiency: ``matter_rollups`` reads ``FeesSettings.overdue_days`` ONCE and
passes it down (no per-row settings read). It loads this firm's non-draft memos
in a single query and folds them in Python; the firm page is bounded, and the
stored ``Memo.total_fees`` / ``Memo.amount_paid`` are used for status so no fee
re-derivation happens. No module-level mutable state.
"""
from __future__ import annotations

from django.db import transaction
from django.db.models.functions import Lower

from fees.errors import FeesError
from fees.models import (
    FIRM_ACTIVE,
    FIRM_ARCHIVED,
    FeesSettings,
    Firm,
    Group,
    Matter,
    Memo,
)
from fees.services.memo_fees import compute_is_overdue
from fees.services.memos import touch
from fees.services.money import round2

__all__ = [
    "MAX_GROUPS",
    "MAX_FIRM_NAME",
    "MAX_GROUP_NAME",
    "validate_name",
    "create_firm",
    "list_firms",
    "get_firm",
    "set_firm_status",
    "update_firm",
    "add_group",
    "update_group",
    "remove_group",
    "matter_rollups",
    "recent_matters",
]

#: A firm may have at most this many groups (original ``MAX_PARTNERS``).
MAX_GROUPS = 50
#: Firm and group names are 1 to 200 characters (R-FIRM-1).
MAX_FIRM_NAME = 200
MAX_GROUP_NAME = 200


def validate_name(raw, invalid_code, max_len):
    """Trims ``raw`` and returns it, or raises ``FeesError(invalid_code, ...)``.

    A name must be 1 to ``max_len`` characters after trimming (R-FIRM-1).
    ``invalid_code`` is one of ``INVALID_FIRM_NAME`` / ``INVALID_PARTNER_NAME`` /
    ``INVALID_MATTER_NAME`` (the group code stays PARTNER to match the original).
    """
    trimmed = (raw or "").strip()
    if len(trimmed) < 1 or len(trimmed) > max_len:
        raise FeesError(
            invalid_code, f"Name must be between 1 and {max_len} characters"
        )
    return trimmed


def _normalize_status(raw):
    """Narrows a stored status to ``active`` / ``archived`` (defaults to active)."""
    return FIRM_ARCHIVED if raw == FIRM_ARCHIVED else FIRM_ACTIVE


# ---------------------------------------------------------------------------
# Firms
# ---------------------------------------------------------------------------

def create_firm(profile, name):
    """Creates a firm and a same-named group in one transaction (R-FIRM-2).

    Validates and trims the name (``INVALID_FIRM_NAME``), rejects a
    case-insensitive duplicate within the profile (``DUPLICATE_FIRM_NAME``), then
    inserts the ``Firm`` (status ``active``) AND a ``Group`` named the same inside
    one ``transaction.atomic()`` so the firm always has at least one group and a
    matter can be created right away. Returns the created ``Firm``.
    """
    clean = validate_name(name, "INVALID_FIRM_NAME", MAX_FIRM_NAME)
    if Firm.objects.filter(profile=profile, name__iexact=clean).exists():
        raise FeesError("DUPLICATE_FIRM_NAME", f'A firm named "{clean}" already exists')

    with transaction.atomic():
        firm = Firm.objects.create(profile=profile, name=clean, status=FIRM_ACTIVE)
        Group.objects.create(profile=profile, firm=firm, name=clean)
        touch(profile)
    return firm


def list_firms(profile, status_filter="all"):
    """Firms for a profile ordered by ``Lower(name)``, filtered on the STORED status.

    ``status_filter`` is ``"all"`` / ``"active"`` / ``"archived"`` (R-FIRM-4).
    Returns a queryset.
    """
    qs = Firm.objects.filter(profile=profile).order_by(Lower("name"))
    if status_filter in (FIRM_ACTIVE, FIRM_ARCHIVED):
        qs = qs.filter(status=status_filter)
    return qs


def _get_firm_or_raise(profile, firm_id):
    firm = Firm.objects.filter(profile=profile, pk=firm_id).first()
    if firm is None:
        raise FeesError("FIRM_NOT_FOUND", f"Firm {firm_id} not found")
    return firm


def get_firm(profile, firm_id):
    """Firm detail for the firm page: the firm, its groups, and matter roll-ups.

    Returns a dict ``{"firm": Firm, "groups": [Group ordered by Lower(name)],
    "matters": [{"matter": Matter, "memo_status": ..., "has_written_off": bool}]}``.
    Matters are ordered by ``Lower(name)``. Raises ``FIRM_NOT_FOUND`` if the firm
    is missing or not in this profile.
    """
    firm = _get_firm_or_raise(profile, firm_id)
    groups = list(firm.groups.order_by(Lower("name")))
    rollups = matter_rollups(profile, firm_id)
    matters = []
    for matter in firm.matters.order_by(Lower("name")):
        roll = rollups.get(matter.pk, {"memo_status": None, "has_written_off": False})
        matters.append(
            {
                "matter": matter,
                "memo_status": roll["memo_status"],
                "has_written_off": roll["has_written_off"],
            }
        )
    return {"firm": firm, "groups": groups, "matters": matters}


def set_firm_status(profile, firm_id, status):
    """Manually sets a firm's stored status to ``active`` or ``archived`` (R-FIRM-5)."""
    firm = _get_firm_or_raise(profile, firm_id)
    with transaction.atomic():
        firm.status = _normalize_status(status)
        firm.save(update_fields=["status", "updated_at"])
        touch(profile)
    return firm


def update_firm(profile, firm_id, name=None, notes=None):
    """Renames a firm (with a duplicate check) and/or updates its notes.

    ``name`` and ``notes`` default to ``None`` meaning "leave unchanged". A rename
    is validated (``INVALID_FIRM_NAME``) and rejected on a case-insensitive
    duplicate within the profile (``DUPLICATE_FIRM_NAME``). Returns the ``Firm``.
    """
    firm = _get_firm_or_raise(profile, firm_id)
    update_fields = []
    if name is not None:
        clean = validate_name(name, "INVALID_FIRM_NAME", MAX_FIRM_NAME)
        dupe = (
            Firm.objects.filter(profile=profile, name__iexact=clean)
            .exclude(pk=firm.pk)
            .exists()
        )
        if dupe:
            raise FeesError(
                "DUPLICATE_FIRM_NAME", f'A firm named "{clean}" already exists'
            )
        firm.name = clean
        update_fields.append("name")
    if notes is not None:
        firm.notes = notes
        update_fields.append("notes")
    if update_fields:
        update_fields.append("updated_at")
        with transaction.atomic():
            firm.save(update_fields=update_fields)
            touch(profile)
    return firm


# ---------------------------------------------------------------------------
# Groups (original "partners"; the UI always says "Group")
# ---------------------------------------------------------------------------

def add_group(profile, firm_id, name):
    """Adds a group to a firm (original ``addPartner``).

    Validates the name (``INVALID_PARTNER_NAME``), enforces at most ``MAX_GROUPS``
    per firm (``TOO_MANY_PARTNERS``) and rejects a case-insensitive duplicate
    within the firm (``DUPLICATE_PARTNER_NAME``). ``FIRM_NOT_FOUND`` if the firm
    is missing. Returns the created ``Group``.
    """
    firm = _get_firm_or_raise(profile, firm_id)
    clean = validate_name(name, "INVALID_PARTNER_NAME", MAX_GROUP_NAME)

    if firm.groups.count() >= MAX_GROUPS:
        raise FeesError(
            "TOO_MANY_PARTNERS", f"A firm may have at most {MAX_GROUPS} groups"
        )

    if firm.groups.filter(name__iexact=clean).exists():
        raise FeesError(
            "DUPLICATE_PARTNER_NAME", f'Group "{clean}" already exists in this firm'
        )

    with transaction.atomic():
        group = Group.objects.create(profile=profile, firm=firm, name=clean)
        touch(profile)
    return group


def update_group(profile, group_id, name):
    """Renames a group with a duplicate check (original ``updatePartner``).

    ``PARTNER_NOT_FOUND`` if the group is missing or not in this profile;
    ``INVALID_PARTNER_NAME`` / ``DUPLICATE_PARTNER_NAME`` on an invalid or
    case-insensitively colliding name within the same firm. Returns the ``Group``.
    """
    group = Group.objects.filter(profile=profile, pk=group_id).first()
    if group is None:
        raise FeesError("PARTNER_NOT_FOUND", f"Group {group_id} not found")

    clean = validate_name(name, "INVALID_PARTNER_NAME", MAX_GROUP_NAME)
    dupe = (
        Group.objects.filter(firm_id=group.firm_id, name__iexact=clean)
        .exclude(pk=group.pk)
        .exists()
    )
    if dupe:
        raise FeesError(
            "DUPLICATE_PARTNER_NAME", f'Group "{clean}" already exists in this firm'
        )

    with transaction.atomic():
        group.name = clean
        group.save(update_fields=["name", "updated_at"])
        touch(profile)
    return group


def remove_group(profile, firm_id, group_id):
    """Removes a group (original ``removePartner``); refuses if a matter uses it.

    ``PARTNER_NOT_FOUND`` if the group is missing or not under this firm/profile.
    If any ``Matter`` still references the group, raises ``FeesError("GROUP_IN_USE",
    ..., status=409)`` BEFORE attempting the delete (R-FIRM-2) so the caller gets a
    clean, documented error rather than a raw ``IntegrityError`` / protected-delete
    failure. The original had no dedicated code; ``GROUP_IN_USE`` (409) is added to
    ``errors.py`` for this case. Otherwise deletes the group and returns ``None``.
    """
    group = Group.objects.filter(
        profile=profile, pk=group_id, firm_id=firm_id
    ).first()
    if group is None:
        raise FeesError("PARTNER_NOT_FOUND", f"Group {group_id} not found")

    if Matter.objects.filter(profile=profile, group=group).exists():
        raise FeesError(
            "GROUP_IN_USE",
            "This group still has matters, so it cannot be removed.",
            status=409,
        )

    with transaction.atomic():
        group.delete()
        touch(profile)
    return None


# ---------------------------------------------------------------------------
# Roll-ups and recent matters (R-FIRM-4, brief 5.12)
# ---------------------------------------------------------------------------

def _overdue_days_for(profile):
    """Reads ``FeesSettings.overdue_days`` ONCE (0 when there is no settings row)."""
    value = (
        FeesSettings.objects.filter(profile=profile)
        .values_list("overdue_days", flat=True)
        .first()
    )
    return value or 0


def matter_rollups(profile, firm_id, overdue_days=None):
    """Per-matter rolled-up status over a firm's NON-DRAFT memos (R-FIRM-4).

    Folds every non-draft memo of the firm per matter. A memo's status comes from
    the STORED ``total_fees`` / ``amount_paid`` (paid when ``amount_paid >=
    total_fees``, a 0 total is paid); overdue uses ``compute_is_overdue`` with
    ``overdue_days``. Per matter:

    * ``has_written_off`` is True if any memo is written off;
    * ``memo_status`` is derived from LIVE (not-written-off) memos only:
      None if the matter has no memos OR every memo is written off; else
      ``"Overdue"`` if any live memo is overdue; else ``"Unpaid"`` if any live
      not-written-off memo is unpaid; else ``"Paid"``.

    ``overdue_days`` defaults to the profile's ``FeesSettings.overdue_days`` read
    once here; a caller that already holds it (e.g. a firm page rendering many
    firms) passes it in to avoid repeated settings reads. Returns
    ``{matter_id: {"memo_status": ..., "has_written_off": bool}}``.
    """
    if overdue_days is None:
        overdue_days = _overdue_days_for(profile)

    rows = Memo.objects.filter(profile=profile, firm_id=firm_id, is_draft=False).values(
        "matter_id", "date", "written_off", "total_fees", "amount_paid"
    )

    acc = {}
    for r in rows:
        matter_id = r["matter_id"]
        a = acc.get(matter_id)
        if a is None:
            a = {
                "any_overdue": False,
                "any_unpaid": False,
                "any_written_off": False,
                "live_count": 0,
                "has_memo": False,
            }
            acc[matter_id] = a

        total = round2(r["total_fees"])
        paid = round2(r["amount_paid"])
        written_off = bool(r["written_off"])
        is_paid = paid >= total
        is_overdue = compute_is_overdue(
            r["date"], "Paid" if is_paid else "Unpaid", written_off, overdue_days
        )

        a["has_memo"] = True
        if written_off:
            a["any_written_off"] = True
        else:
            a["live_count"] += 1
        if is_overdue:
            a["any_overdue"] = True
        if not is_paid and not written_off:
            a["any_unpaid"] = True

    out = {}
    for matter_id, a in acc.items():
        if not a["has_memo"] or a["live_count"] == 0:
            memo_status = None
        elif a["any_overdue"]:
            memo_status = "Overdue"
        elif a["any_unpaid"]:
            memo_status = "Unpaid"
        else:
            memo_status = "Paid"
        out[matter_id] = {
            "memo_status": memo_status,
            "has_written_off": a["any_written_off"],
        }
    return out


def recent_matters(profile, limit=10):
    """Recently billed matters for the dashboard (R-FIRM-4, brief 5.12).

    Non-draft memos grouped by matter, ordered by latest memo date descending
    then matter id descending, limited to ``limit``. For each matter returns a
    dict with ``matter_id``, ``matter_name``, ``firm_id``, ``firm_name``,
    ``last_memo_date``, ``last_memo_number`` (the number of the latest memo by
    date desc, seq desc, id desc), ``last_memo_id``, ``memo_count`` and
    ``is_archived``.

    The grouped query (one row per matter) is done in SQL; the latest memo
    number is a bounded per-matter lookup (at most ``limit`` extra queries). This
    small N+1 is deferred to a later efficiency pass if the dashboard grows (the
    list is capped at ``limit``, default 10).
    """
    from django.db.models import Count, Max

    grouped = (
        Memo.objects.filter(profile=profile, is_draft=False)
        .values("matter_id")
        .annotate(last_date=Max("date"), memo_count=Count("id"))
        .order_by("-last_date", "-matter_id")[:limit]
    )

    results = []
    for g in grouped:
        matter_id = g["matter_id"]
        latest = (
            Memo.objects.filter(profile=profile, matter_id=matter_id, is_draft=False)
            .order_by("-date", "-seq", "-id")
            .values("id", "memo_number")
            .first()
        )
        matter = (
            Matter.objects.filter(pk=matter_id)
            .values("name", "firm_id", "is_archived", "firm__name")
            .first()
        )
        results.append(
            {
                "matter_id": matter_id,
                "matter_name": matter["name"] if matter else "",
                "firm_id": matter["firm_id"] if matter else None,
                "firm_name": matter["firm__name"] if matter else "",
                "last_memo_date": g["last_date"],
                "last_memo_number": latest["memo_number"] if latest else None,
                "last_memo_id": latest["id"] if latest else None,
                "memo_count": g["memo_count"],
                "is_archived": bool(matter["is_archived"]) if matter else False,
            }
        )
    return results
