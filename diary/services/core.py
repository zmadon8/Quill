"""Shared machinery: record lookup inside a profile, snapshots, history, versions, tree walking.

Every public service function opens ``transaction.atomic()``, finds records with ``get_record``
(always inside the caller's profile, rows locked), changes them only through ``commit`` or
``create`` (which bump the version and write a full snapshot to VersionHistory) and returns an
``ActionResult``. Nothing here removes rows.
"""
import contextlib
import contextvars
import datetime
import uuid
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

from ..models import (
    Case,
    Item,
    Note,
    NoteLink,
    Section,
    Subject,
    Subtopic,
    Topic,
    VersionHistory,
)
from .errors import Conflict, NotFound, Refused, ValidationFailed

MODELS = {
    "subject": Subject,
    "topic": Topic,
    "subtopic": Subtopic,
    "section": Section,
    "item": Item,
    "case": Case,
    "note": Note,
    "notelink": NoteLink,
}

#: Parent links of each type, in the order they are looked at, with the record type each one points to.
PARENT_LINKS = {
    "subject": (),
    "topic": (("subject", "subject"),),
    "subtopic": (("topic", "topic"), ("subject", "subject")),
    "section": (("subtopic", "subtopic"), ("topic", "topic"), ("subject", "subject")),
    "item": (("parent_item", "item"), ("subtopic", "subtopic"), ("topic", "topic"), ("subject", "subject")),
    "case": (("item", "item"),),
    "note": (
        ("item", "item"),
        ("section", "section"),
        ("subtopic", "subtopic"),
        ("topic", "topic"),
        ("subject", "subject"),
    ),
    "notelink": (("note", "note"),),
}

#: Columns that Undo and history restore never copy back from a snapshot.
SNAPSHOT_SKIP = {"id", "version", "created_at", "updated_at", "created_by", "updated_by", "profile"}


def record_type(obj):
    return type(obj).__name__.lower()


def model_for(kind):
    try:
        return MODELS[kind]
    except KeyError:
        raise NotFound(f"Unknown record type {kind!r}.")


_shared_group = contextvars.ContextVar("diary_action_group", default=None)


@contextlib.contextmanager
def action_group():
    """Make every service call inside the ``with`` share one Undo group (one user action = one group).

    Yields the group id. Used by the views, so that a screen that makes several service calls (the
    Item editor saves the Item and its Cases) is still one step for Undo.
    """
    group = uuid.uuid4()
    token = _shared_group.set(group)
    try:
        yield group
    finally:
        _shared_group.reset(token)


def _new_group():
    return _shared_group.get() or uuid.uuid4()


@dataclass
class Ctx:
    """Who is acting, in which profile, and which Undo group the history rows belong to."""

    profile: object
    user: object = None
    group: uuid.UUID = field(default_factory=_new_group)
    touched: list = field(default_factory=list)  # [(record_type, record_id)] written so far

    @property
    def profile_id(self):
        return self.profile.pk

    @property
    def actor(self):
        user = self.user
        return user if user is not None and getattr(user, "pk", None) else None


@dataclass
class ActionResult:
    """What a service call did. ``changed`` is False for a harmless repeat (nothing was written)."""

    record: object = None
    changed: bool = True
    group: uuid.UUID = None
    touched: list = field(default_factory=list)  # [(record_type, record_id)] in the order written
    info: dict = field(default_factory=dict)


def make_result(ctx, record=None, **info):
    touched = list(dict.fromkeys(ctx.touched))
    return ActionResult(record=record, changed=bool(touched), group=ctx.group if touched else None,
                        touched=touched, info=info)


def _touch(ctx, obj):
    ctx.touched.append((record_type(obj), obj.pk))


def snapshot(obj):
    """All columns of ``obj`` as JSON-friendly values (foreign keys as ids)."""
    data = {}
    for fld in obj._meta.concrete_fields:
        value = fld.value_from_object(obj)
        if isinstance(value, (datetime.datetime, datetime.date)):
            value = value.isoformat()
        elif isinstance(value, uuid.UUID):
            value = str(value)
        data[fld.attname] = value
    return data


def apply_snapshot(obj, snap):
    """Copy the columns in ``snap`` back onto ``obj`` (not saved), except bookkeeping columns."""
    for fld in obj._meta.concrete_fields:
        if fld.name in SNAPSHOT_SKIP or fld.attname not in snap:
            continue
        value = snap[fld.attname]
        if value is not None and not fld.is_relation:
            value = fld.to_python(value)
        setattr(obj, fld.attname, value)


def get_record(ctx, kind, record_id, *, lock=True, include_deleted=False):
    """The record, found only inside ``ctx.profile``. Another profile's id is simply 'not found'."""
    model = model_for(kind)
    try:
        record_id = int(record_id)
    except (TypeError, ValueError):
        raise NotFound("That record does not exist.")
    qs = model._base_manager.filter(pk=record_id, profile_id=ctx.profile_id)
    if lock:
        qs = qs.select_for_update()
    obj = qs.first()
    if obj is None:
        raise NotFound("That record does not exist in this profile.")
    if obj.deleted_at is not None and not include_deleted:
        raise Refused("That record is in the Trash.")
    return obj


def check_version(obj, expected, mine=None):
    """Optimistic concurrency: refuse a save made against an older version, with both versions."""
    if expected is None:
        return
    if int(expected) != obj.version:
        raise Conflict(record_type(obj), obj.pk, int(expected), obj.version, snapshot(obj), mine)


def write_history(ctx, obj, kind):
    VersionHistory.objects.create(
        record_type=record_type(obj),
        record_id=obj.pk,
        version=obj.version,
        snapshot=snapshot(obj),
        changed_by=ctx.actor,
        profile_id=ctx.profile_id,
        change_kind=kind,
        group=ctx.group,
    )


def commit(ctx, obj, kind, check=True):
    """Save a change to an existing record: version +1, who, full snapshot.

    ``check=False`` skips the content rules (names, citation length, model clean()) for changes that
    only move, delete or restore a record, so old or imported data can always be moved to Trash.
    """
    if check:
        validate(ctx, obj)
    obj.version += 1
    obj.updated_by = ctx.actor
    obj.save()
    write_history(ctx, obj, kind)
    _touch(ctx, obj)
    return obj


def create(ctx, model, change_kind="create", **fields):
    obj = model(profile_id=ctx.profile_id, created_by=ctx.actor, updated_by=ctx.actor, **fields)
    validate(ctx, obj)
    obj.save()
    write_history(ctx, obj, change_kind)
    _touch(ctx, obj)
    return obj


def label(obj):
    """A short human name for a record (headings: the name; others: text or citation)."""
    kind = record_type(obj)
    if kind in ("subject", "topic", "subtopic"):
        return obj.name
    if kind == "section":
        return obj.name or "Section"
    if kind == "item":
        return (obj.text_plain.strip()[:60] or obj.citation[:60] or f"Item {obj.pk}")
    if kind == "case":
        return obj.citation[:60] or f"Case {obj.pk}"
    if kind == "note":
        return obj.text_plain.strip()[:60] or f"Note {obj.pk}"
    return f"Link {obj.pk}"


# ---------------------------------------------------------------- validation

def clean_name(value, what="name"):
    name = " ".join((value or "").split())
    if not name:
        raise ValidationFailed(f"The {what} is required.")
    return name


def live_subject_name_taken(profile_id, name, exclude_pk=None):
    qs = Subject._base_manager.filter(profile_id=profile_id, deleted_at__isnull=True).annotate(lowered=Lower("name"))
    qs = qs.filter(lowered=name.lower())
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    return qs.exists()


def validate(ctx, obj):
    """Required names, the unique live Subject name, and the model's own clean() rules."""
    kind = record_type(obj)
    if kind in ("subject", "topic", "subtopic"):
        if not obj.name.strip():
            raise ValidationFailed("The name is required.")
        if len(obj.name) > 300:
            raise ValidationFailed("The name is too long (300 characters at most).")
    if kind == "subject" and obj.deleted_at is None and live_subject_name_taken(ctx.profile_id, obj.name, obj.pk):
        raise ValidationFailed(f"A Subject called {obj.name!r} already exists.")
    if kind == "section" and len(obj.name) > 500:
        raise ValidationFailed("The name is too long (500 characters at most).")
    if kind == "item":
        if len(obj.citation) > 1000:
            raise ValidationFailed("The citation is too long (1000 characters at most).")
        if obj.kind == "multi" and obj.citation:
            raise ValidationFailed("A Multi-Item has no citation of its own; its Cases hold the citations.")
        if obj.parent_item_id is not None and obj.kind != "plain":
            raise ValidationFailed("An Item beneath a Nested Item must stay a plain Item (one level of nesting).")
    if kind == "case" and len(obj.citation) > 1000:
        raise ValidationFailed("The citation is too long (1000 characters at most).")
    if hasattr(obj, "clean") and kind in ("item", "case"):
        try:
            obj.clean()
        except ValidationError as exc:
            raise ValidationFailed("; ".join(exc.messages))


# ---------------------------------------------------------------- tree walking

def parent_of(obj):
    """(type, record) of the parent, or None for a Subject. Uses the default (profile-wide) lookups."""
    for column, kind in PARENT_LINKS[record_type(obj)]:
        pk = getattr(obj, f"{column}_id")
        if pk is not None:
            parent = MODELS[kind]._base_manager.filter(pk=pk, profile_id=obj.profile_id).first()
            return kind, parent
    return None


def ancestors(obj):
    """[(type, record)] from the top (Subject) down to the parent."""
    chain = []
    current = obj
    while True:
        found = parent_of(current)
        if found is None or found[1] is None:
            break
        chain.append(found)
        current = found[1]
    chain.reverse()
    return chain


def children_of(obj, live_only=False, lock=False):
    """Records that structurally belong to ``obj`` (Items sit in their container, not under a Section)."""
    kind = record_type(obj)
    pid = obj.profile_id

    def rows(model, **where):
        qs = model._base_manager.filter(profile_id=pid, **where)
        if live_only:
            qs = qs.filter(deleted_at__isnull=True)
        if lock:
            qs = qs.select_for_update()
        return list(qs.order_by("pk"))

    if kind == "subject":
        return (rows(Topic, subject=obj) + rows(Subtopic, subject=obj) + rows(Section, subject=obj)
                + rows(Item, subject=obj) + rows(Note, subject=obj))
    if kind == "topic":
        return rows(Subtopic, topic=obj) + rows(Section, topic=obj) + rows(Item, topic=obj) + rows(Note, topic=obj)
    if kind == "subtopic":
        return rows(Section, subtopic=obj) + rows(Item, subtopic=obj) + rows(Note, subtopic=obj)
    if kind == "section":
        return rows(Note, section=obj)
    if kind == "item":
        return rows(Item, parent_item=obj) + rows(Case, item=obj) + rows(Note, item=obj)
    if kind == "note":
        return rows(NoteLink, note=obj)
    return []


def descendants(obj, live_only=False, lock=False):
    """Every record below ``obj``, parents before their children."""
    found = []
    queue = [obj]
    while queue:
        current = queue.pop(0)
        for child in children_of(current, live_only, lock):
            found.append(child)
            queue.append(child)
    return found


def now():
    return timezone.now()


def next_free_name(model, profile_id, name, **scope):
    """'Name (restored)', 'Name (restored 2)', ... the first not used by a live sibling."""
    taken = {
        n.lower()
        for n in model._base_manager.filter(profile_id=profile_id, deleted_at__isnull=True, **scope).values_list(
            "name", flat=True
        )
    }
    candidate = f"{name} (restored)"
    n = 2
    while candidate.lower() in taken:
        candidate = f"{name} (restored {n})"
        n += 1
    return candidate


def q_target(kind, pks):
    """NoteLink filter: links whose target of type ``kind`` is one of ``pks``."""
    return Q(**{f"{kind}_id__in": list(pks)})
