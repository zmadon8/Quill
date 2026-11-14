"""Matter services for the Fee Register (R-FIRM-1, R-FIRM-3, R-FIRM-5, brief 5.12).

Ports ``matterService.ts`` to the Django ORM. Every function takes ``profile``
explicitly and never reads the request. A matter belongs to exactly one firm and
one group; its name is unique within the firm (case-insensitive). New matters
are active (``is_archived = False``). The UI says "Group"; the model is
``Group`` and the original error codes say PARTNER (``PARTNER_NOT_FOUND``) kept
verbatim.

Return shapes (consistent across this module): ``create_matter``,
``update_matter``, ``archive_matter``, ``unarchive_matter`` and ``get_matter``
return the ``Matter`` instance. ``list_matters`` returns a queryset ordered by
``Lower(group name)`` then ``Lower(matter name)`` with ``select_related`` on firm
and group so a caller reads names without an extra query.

The MOVE cascade (R-FIRM-3): when ``firm_id`` and/or ``group_id`` change,
``update_matter`` validates the target firm/group (the group must belong to the
target firm), rejects a name collision in the TARGET firm, then in one
``transaction.atomic()`` updates the matter AND every one of its memos
(``Memo.objects.filter(matter=...).update(firm=..., group=...)``) because memos
denormalise ``firm_id`` / ``group_id`` (R-DATA-5) and must stay in sync.

Case-insensitive uniqueness is checked in Python first (clean
``DUPLICATE_MATTER_NAME``, brief 15 Q2) with the DB ``UniqueConstraint`` as the
backstop. No module-level mutable state.
"""
from __future__ import annotations

from django.db import transaction
from django.db.models.functions import Lower

from fees.errors import FeesError
from fees.models import Firm, Group, Matter, Memo
from fees.services import history
from fees.services.memos import MAX_MEMO_TEXT, touch

__all__ = [
    "MAX_MATTER_NAME",
    "validate_name",
    "MEMO_DEFAULT_FIELDS",
    "create_matter",
    "update_matter",
    "list_matters",
    "archive_matter",
    "unarchive_matter",
    "get_matter",
]

#: Matter names are 1 to 150 characters (R-FIRM-1).
MAX_MATTER_NAME = 150

#: The matter-level memo-default text fields (snapshotted onto a memo at create).
MEMO_DEFAULT_FIELDS = (
    "addressee_line1",
    "addressee_line2",
    "addressee_use_firm_name",
    "court_name",
    "client",
    "additional_details_left",
    "additional_details_right",
    "plaintiff_name",
    "plaintiff_type",
    "defendant_name",
    "defendant_type",
    "notes",
    "short_name",
)


def validate_name(raw):
    """Trims and returns a matter name, or raises ``INVALID_MATTER_NAME`` (R-FIRM-1).

    A matter name is 1 to 150 characters after trimming.
    """
    trimmed = (raw or "").strip()
    if len(trimmed) < 1 or len(trimmed) > MAX_MATTER_NAME:
        raise FeesError(
            "INVALID_MATTER_NAME",
            f"Matter name must be between 1 and {MAX_MATTER_NAME} characters",
        )
    return trimmed


def _group_in_firm_or_raise(profile, firm_id, group_id):
    """Returns the group if it belongs to ``firm_id`` in this profile, else raises."""
    group = Group.objects.filter(
        profile=profile, pk=group_id, firm_id=firm_id
    ).first()
    if group is None:
        raise FeesError(
            "PARTNER_NOT_FOUND",
            f"Group {group_id} is not part of firm {firm_id}",
        )
    return group


def _collect_memo_defaults(values):
    """Picks the memo-default fields present in ``values`` (a dict), trimming short_name."""
    out = {}
    court_name = values.get("court_name")
    if court_name is not None and len(str(court_name)) > MAX_MEMO_TEXT:
        raise FeesError(
            "INVALID_MATTER",
            f"Court name must be at most {MAX_MEMO_TEXT} characters",
        )
    for field in MEMO_DEFAULT_FIELDS:
        if field not in values:
            continue
        value = values[field]
        if field == "addressee_use_firm_name":
            out[field] = bool(value)
        elif field == "short_name":
            out[field] = (value or "").strip()
        else:
            out[field] = value if value is not None else ""
    return out


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def create_matter(profile, firm_id, group_id, name, **memo_defaults):
    """Creates an active matter under a firm and group (R-FIRM-1, R-FIRM-5).

    Validates the name (``INVALID_MATTER_NAME``), requires the firm to exist
    (``FIRM_NOT_FOUND``) and the group to belong to that firm
    (``PARTNER_NOT_FOUND``), and rejects a case-insensitive duplicate name within
    the firm (``DUPLICATE_MATTER_NAME``). ``memo_defaults`` are the optional
    matter-level memo-default text fields. Returns the created ``Matter``.
    """
    clean = validate_name(name)

    firm = Firm.objects.filter(profile=profile, pk=firm_id).first()
    if firm is None:
        raise FeesError("FIRM_NOT_FOUND", f"Firm {firm_id} not found")

    group = _group_in_firm_or_raise(profile, firm_id, group_id)

    if Matter.objects.filter(profile=profile, firm=firm, name__iexact=clean).exists():
        raise FeesError(
            "DUPLICATE_MATTER_NAME",
            f'A matter named "{clean}" already exists in this firm',
        )

    fields = {
        "profile": profile,
        "firm": firm,
        "group": group,
        "name": clean,
        "is_archived": False,
    }
    fields.update(_collect_memo_defaults(memo_defaults))
    with transaction.atomic():
        matter = Matter.objects.create(**fields)
        history.record(profile, "create", "matter", matter.pk, f"Added matter {matter.name}")
        touch(profile)
    return matter


# ---------------------------------------------------------------------------
# Update (rename + the firm/group MOVE that cascades to memos)
# ---------------------------------------------------------------------------

def update_matter(profile, matter_id, name=None, firm_id=None, group_id=None, **memo_defaults):
    """Renames and/or MOVES a matter, cascading a move to its memos (R-FIRM-3).

    ``name``, ``firm_id`` and ``group_id`` default to ``None`` meaning
    "unchanged". When ``firm_id`` and/or ``group_id`` change, the target firm must
    exist (``FIRM_NOT_FOUND``) and the target group must belong to the target firm
    (``PARTNER_NOT_FOUND``). A rename or a move checks the TARGET firm for a
    case-insensitive name collision (``DUPLICATE_MATTER_NAME``). The matter row and
    ALL its memos are updated in one ``transaction.atomic()`` so the denormalised
    ``firm_id`` / ``group_id`` on memos stay in step with the matter. The
    matter-level memo-default fields in ``memo_defaults`` are also applied.
    Returns the ``Matter``.
    """
    matter = Matter.objects.filter(profile=profile, pk=matter_id).first()
    if matter is None:
        raise FeesError("MATTER_NOT_FOUND", f"Matter {matter_id} not found")

    target_firm_id = firm_id if firm_id is not None else matter.firm_id
    target_group_id = group_id if group_id is not None else matter.group_id
    moved = target_firm_id != matter.firm_id or target_group_id != matter.group_id

    if moved:
        target_firm = Firm.objects.filter(profile=profile, pk=target_firm_id).first()
        if target_firm is None:
            raise FeesError("FIRM_NOT_FOUND", f"Firm {target_firm_id} not found")
        _group_in_firm_or_raise(profile, target_firm_id, target_group_id)

    # Name uniqueness is always checked against the TARGET firm.
    new_name = None
    if name is not None:
        new_name = validate_name(name)
        clash_name = new_name
    elif moved:
        clash_name = matter.name
    else:
        clash_name = None

    if clash_name is not None:
        dupe = (
            Matter.objects.filter(
                profile=profile, firm_id=target_firm_id, name__iexact=clash_name
            )
            .exclude(pk=matter.pk)
            .exists()
        )
        if dupe:
            raise FeesError(
                "DUPLICATE_MATTER_NAME",
                f'A matter named "{clash_name}" already exists in this firm',
            )

    memo_default_updates = _collect_memo_defaults(memo_defaults)

    with transaction.atomic():
        update_fields = []
        if new_name is not None:
            matter.name = new_name
            update_fields.append("name")
        if moved:
            matter.firm_id = target_firm_id
            matter.group_id = target_group_id
            update_fields.extend(["firm", "group"])
        for field, value in memo_default_updates.items():
            setattr(matter, field, value)
            update_fields.append(field)
        if update_fields:
            update_fields.append("updated_at")
            matter.save(update_fields=update_fields)
        if moved:
            Memo.objects.filter(profile=profile, matter=matter).update(
                firm_id=target_firm_id, group_id=target_group_id
            )
        if update_fields:
            verb = "Moved" if moved else "Changed"
            history.record(profile, "move" if moved else "update", "matter", matter.pk, f"{verb} matter {matter.name}")
        touch(profile)

    return matter


# ---------------------------------------------------------------------------
# List / Get
# ---------------------------------------------------------------------------

def list_matters(profile, firm_id=None, status_filter="all"):
    """Matters ordered by ``Lower(group name)`` then ``Lower(matter name)`` (R-FIRM-4).

    Optionally scoped to ``firm_id``. ``status_filter`` is ``"all"`` /
    ``"active"`` / ``"archived"`` on ``is_archived``. ``select_related`` on firm
    and group avoids an N+1 when reading their names. Returns a queryset.
    """
    qs = Matter.objects.filter(profile=profile).select_related("firm", "group")
    if firm_id is not None:
        qs = qs.filter(firm_id=firm_id)
    if status_filter == "active":
        qs = qs.filter(is_archived=False)
    elif status_filter == "archived":
        qs = qs.filter(is_archived=True)
    return qs.order_by(Lower("group__name"), Lower("name"))


def get_matter(profile, matter_id):
    """Returns a matter (with firm and group preloaded) for the matter page.

    Raises ``MATTER_NOT_FOUND`` if missing or not in this profile. The returned
    instance carries all the memo-default fields.
    """
    matter = (
        Matter.objects.filter(profile=profile, pk=matter_id)
        .select_related("firm", "group")
        .first()
    )
    if matter is None:
        raise FeesError("MATTER_NOT_FOUND", f"Matter {matter_id} not found")
    return matter


# ---------------------------------------------------------------------------
# Archive / Unarchive
# ---------------------------------------------------------------------------

def _set_archived(profile, matter_id, archived):
    matter = Matter.objects.filter(profile=profile, pk=matter_id).first()
    if matter is None:
        raise FeesError("MATTER_NOT_FOUND", f"Matter {matter_id} not found")
    with transaction.atomic():
        if matter.is_archived != archived:
            matter.is_archived = archived
            matter.save(update_fields=["is_archived", "updated_at"])
            history.record(
                profile, "update", "matter", matter.pk,
                f"{'Archived' if archived else 'Unarchived'} matter {matter.name}",
            )
        touch(profile)
    return matter


def archive_matter(profile, matter_id):
    """Archives a matter (``is_archived = True``). Returns the ``Matter`` (R-FIRM-5)."""
    return _set_archived(profile, matter_id, True)


def unarchive_matter(profile, matter_id):
    """Unarchives a matter (``is_archived = False``). Returns the ``Matter``."""
    return _set_archived(profile, matter_id, False)
