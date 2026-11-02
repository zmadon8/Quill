"""Version history and Undo screens (Milestone 3d, docs/DESIGN.md sections 5.7 and 9.1, M3-21).

Editors of the profile only (Readers get 403). History is read inside ``request.profile``: a record of
another profile has no history here (404). Restoring a version and Undo are POSTs with the CSRF token.
"""
from django.conf import settings
from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse

from . import inline, nested_conversion
from . import services as svc
from . import undo_session
from .conflicts import plain
from .services.core import MODELS, Ctx, get_record, label
from .services.errors import NameClash, NotFound, UndoWarning
from .services.moves import NICE
from .services.records import EDITABLE
from .views_edit import _json_error, _next, _record_id, _version, edit_endpoint, editor_get, is_fetch

#: Columns that say where a record is or how it was made, not what it says: shown last in a snapshot.
BOOKKEEPING = ("id", "profile_id", "version", "created_at", "updated_at", "created_by_id", "updated_by_id",
               "deleted_at", "delete_batch")


def _person(user):
    if user is None:
        return "unknown"
    return user.get_full_name() or user.get_username()


def _rows(profile, kind, pk):
    if kind not in MODELS:
        raise Http404("Unknown record type.")
    rows = list(svc.history_for(profile, kind, pk).select_related("changed_by"))
    if not rows:
        raise Http404("There is no history for that record in this profile.")
    return rows


def _current(profile, kind, pk):
    """The record as it is now (live or in Trash), or None if it was deleted permanently."""
    try:
        return get_record(Ctx(profile, None), kind, pk, lock=False, include_deleted=True)
    except NotFound:
        return None


def _name(kind, snapshot, pk):
    if "name" in snapshot:
        return snapshot["name"] or NICE[kind]
    return plain(snapshot.get("text") or snapshot.get("citation") or "")[:60] or f"{NICE[kind]} {pk}"


@editor_get
def history(request, kind, pk):
    """Every saved version of one record, newest first."""
    rows = _rows(request.profile, kind, pk)
    record = _current(request.profile, kind, pk)
    entries = [
        {"version": r.version, "kind": r.get_change_kind_display(), "when": r.changed_at, "who": _person(r.changed_by),
         "current": record is not None and r.version == record.version}
        for r in rows
    ]
    back = _next(request, reverse("diary_home"))
    return render(
        request,
        "diary/history.html",
        {
            "kind": kind,
            "pk": pk,
            "kind_name": NICE[kind],
            "title": label(record) if record is not None else _name(kind, rows[0].snapshot, pk),
            "entries": entries,
            "in_trash": record is not None and record.deleted_at is not None,
            "gone": record is None,
            "can_restore": record is not None and record.deleted_at is None and kind in EDITABLE,
            "back": back,
            "history_days": settings.HISTORY_RETENTION_DAYS,
        },
    )


@editor_get
def history_version(request, kind, pk, version):
    """The full snapshot of one version, with the restore button."""
    rows = _rows(request.profile, kind, pk)
    row = next((r for r in rows if r.version == version), None)
    if row is None:
        raise Http404("That version does not exist.")
    record = _current(request.profile, kind, pk)
    content = EDITABLE.get(kind, ())
    fields = []
    for name, value in sorted(row.snapshot.items(), key=lambda kv: (kv[0] in BOOKKEEPING, kv[0])):
        fields.append({"name": name.replace("_", " "), "value": plain(value), "content": name in content,
                       "differs": record is not None and name in content and plain(getattr(record, name)) != plain(value)})
    live = record is not None and record.deleted_at is None
    # A version from before the 10d merge keeps its one citation in the Item; restoring it writes that text into
    # Case (a), replacing what Case (a) holds now. Say so before the button is pressed.
    old_citation = (
        nested_conversion.old_snapshot_citation(row.snapshot) if live and kind == "item" else None
    )
    return render(
        request,
        "diary/history_version.html",
        {
            "kind": kind,
            "pk": pk,
            "kind_name": NICE[kind],
            "version": row.version,
            "when": row.changed_at,
            "who": _person(row.changed_by),
            "change": row.get_change_kind_display(),
            "fields": fields,
            "can_restore": live and kind in EDITABLE and row.version != record.version,
            "current_version": record.version if record is not None else None,
            "replaces_case_a": old_citation is not None,
            "old_citation": old_citation,
            "back": _next(request, reverse("diary_home")),
        },
    )


@edit_endpoint
def history_restore(request):
    """Make an earlier version's content current again, as a new version (history is never rewritten)."""
    kind = request.POST.get("kind", "")
    if kind not in MODELS:
        raise Http404("Unknown record type.")
    pk, version = _record_id(request), request.POST.get("restore_version", "")
    if not version.isdigit():
        raise Http404("That version does not exist.")
    result = svc.restore_version(request.profile, request.user, kind, pk, int(version), _version(request))
    back = _next(request, reverse("history", args=[kind, pk]))
    if result.changed:
        messages.success(request, f"Restored version {version} as a new version.")
    else:
        messages.info(request, "The record already has that content.")
    return redirect(back)


def _undo_page(request, exc, group):
    return render(
        request,
        "diary/undo_confirm.html",
        {"changed": exc.changed, "group": group, "next_url": _next(request), "message": exc.message},
    )


@edit_endpoint
def undo(request):
    """Undo one action of this session (the newest unless ``group`` says which). A changed record asks first."""
    wanted = undo_session.parse(request.POST.get("group", ""))
    if wanted is None or str(wanted) not in undo_session.groups(request):
        if is_fetch(request):
            return _json_error("There is nothing to undo.")
        messages.error(request, "There is nothing to undo.")
        return redirect(_next(request))
    try:
        svc.undo_group(request.profile, request.user, wanted, force=request.POST.get("force") == "1")
    except UndoWarning as exc:
        if is_fetch(request):
            # Records changed since: the script sends the same form without the fetch header to get the confirm page.
            return _json_error(exc.message, 409, needs_page=True, undo_url=request.path)
        return _undo_page(request, exc, wanted)
    except NameClash as exc:
        if is_fetch(request):
            return _json_error(f"Undo stopped: the name {exc.name!r} is used by another record now. Nothing was changed.")
        messages.error(request, f"Undo stopped: the name {exc.name!r} is used by another record now. Nothing was changed.")
        return redirect(_next(request))
    undo_session.forget(request, wanted)
    if is_fetch(request):
        return inline.ok(request, undone=True, reload=True)
    messages.success(request, "Undone.")
    return redirect(_next(request))
