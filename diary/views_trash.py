"""The Trash screen: list, Restore and permanent delete (Milestone 3d, docs/DESIGN.md sections 5.6 and 9.6, M3-21).

Editors of the profile only (Readers get 403 and see no link). Permanent delete is also Admin only (the
suite-wide Admin flag, working with the Editor role of their own membership). Everything is inside
``request.profile``; another profile's ids are 404. Changes are POSTs with the CSRF token.
"""
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse

from . import services as svc
from .models import TrashBatch
from .services.core import MODELS, PARENT_LINKS, Ctx, ancestors, descendants, get_record, label, record_type
from .services.errors import NameClash, ParentInTrash, PermanentDeleteRefused
from .services.moves import NICE
from .services.trash import incoming_links
from .views_edit import _next, _record_id, _version, edit_endpoint, editor_get

TRASH_KINDS = ("subject", "topic", "subtopic", "section", "item", "case", "note", "notelink")


def _kind(request):
    kind = request.POST.get("kind", "")
    if kind not in TRASH_KINDS:
        raise Http404("Unknown record type.")
    return kind


def _parent_key(rec):
    for column, kind in PARENT_LINKS[record_type(rec)]:
        pk = getattr(rec, f"{column}_id")
        if pk is not None:
            return kind, pk
    return None


def _person(user):
    if user is None:
        return "unknown"
    return user.get_full_name() or user.get_username()


def trash_entries(profile):
    """One entry for each top of a deleted batch: a trashed record whose parent is not trashed in the same batch.

    A record restored on its own with its parent chain leaves the rest of its batch in Trash; those
    records become tops here, so nothing in Trash is ever out of sight.
    """
    trashed = {}
    for kind in TRASH_KINDS:
        for rec in MODELS[kind]._base_manager.filter(profile=profile, deleted_at__isnull=False):
            trashed[(kind, rec.pk)] = rec
    batches = {b.id: b for b in TrashBatch.objects.filter(profile=profile).select_related("created_by")}
    # Members of each batch under each trashed record, from the rows already loaded (no further walking).
    kids = {}
    for key, rec in trashed.items():
        parent = _parent_key(rec)
        above = trashed.get(parent)
        if above is not None and above.delete_batch == rec.delete_batch:
            kids.setdefault(parent, []).append(key)

    def batch_size(key):
        total, stack = 0, [key]
        while stack:
            total += 1
            stack.extend(kids.get(stack.pop(), ()))
        return total

    entries = []
    for (kind, pk), rec in trashed.items():
        above = trashed.get(_parent_key(rec))
        if above is not None and above.delete_batch == rec.delete_batch:
            continue
        batch = batches.get(rec.delete_batch)
        chain = ancestors(rec)
        entries.append(
            {
                "type": kind,
                "id": pk,
                "version": rec.version,
                "label": label(rec),
                "kind_name": NICE[kind],
                "path": " > ".join(label(a) for _, a in chain),
                "parent_in_trash": any(a.deleted_at is not None for _, a in chain),
                "count": batch_size((kind, pk)),
                "deleted_at": rec.deleted_at,
                "deleted_by": _person(batch.created_by) if batch else "unknown",
                "batch_label": batch.label if batch else "",
            }
        )
    entries.sort(key=lambda e: (e["deleted_at"], e["id"]), reverse=True)
    return entries


@editor_get
def trash(request):
    return render(
        request,
        "diary/trash.html",
        {"entries": trash_entries(request.profile), "can_delete_permanently": request.user.is_admin},
    )


def _renames(post):
    """{(type, id): name} from the ``rename_<type>_<id>`` fields (kept in the form across prompts)."""
    found = {}
    for key, value in post.items():
        parts = key.split("_")
        if len(parts) == 3 and parts[0] == "rename" and parts[1] in TRASH_KINDS and parts[2].isdigit():
            found[(parts[1], int(parts[2]))] = value
    return found


def _restore_fields(request, renames, parents):
    fields = {"kind": request.POST.get("kind", ""), "id": request.POST.get("id", ""),
              "version": request.POST.get("version", ""), "next": _next(request, reverse("trash"))}
    if parents:
        fields["restore_parents"] = "1"
    for (kind, pk), name in renames.items():
        fields[f"rename_{kind}_{pk}"] = name
    return sorted(fields.items())


@edit_endpoint
def restore(request):
    """Restore a record with the part of its batch at or below it.

    A parent in Trash asks first (restore the chain too); a clashing Subject or Topic name asks for a new one.
    """
    kind, record_id = _kind(request), _record_id(request)
    parents = request.POST.get("restore_parents") == "1"
    renames = _renames(request.POST)
    back = _next(request, reverse("trash"))
    try:
        result = svc.restore(request.profile, request.user, kind, record_id, _version(request),
                             new_names=renames or None, restore_parents=parents)
    except ParentInTrash as exc:
        chain = [{"kind_name": NICE[k], "label": name} for k, _, name in exc.chain]
        return render(request, "diary/trash_parents.html",
                      {"chain": chain, "fields": _restore_fields(request, renames, True), "next_url": back})
    except NameClash as exc:
        field = f"rename_{exc.record_type}_{exc.record_id}"
        return render(request, "diary/trash_rename.html",
                      {"clash": exc, "kind_name": NICE[exc.record_type], "field": field,
                       "fields": _restore_fields(request, renames, parents), "next_url": back})
    if not result.changed:
        messages.info(request, "That was not in the Trash.")
    else:
        messages.success(request, f"Restored {result.info.get('count', 1)} record(s).")
    return redirect(back)


def _permanent_page(request, kind, obj, status=200):
    ctx = Ctx(request.profile, request.user)
    below = descendants(obj)
    members = [obj] + below
    counts = {}
    for rec in members:
        counts[record_type(rec)] = counts.get(record_type(rec), 0) + 1
    links = incoming_links(ctx, members)
    context = {
        "kind": kind,
        "id": obj.pk,
        "kind_name": NICE[kind],
        "label": label(obj),
        "counts": [(NICE[k], n) for k, n in counts.items()],
        "total": len(members),
        "links": links,
        "back": reverse("trash"),
        "version": request.POST.get("version", ""),
    }
    return render(request, "diary/trash_permanent.html", context, status=status)


@edit_endpoint
def permanent_delete(request):
    """Delete a record in the Trash for good. Admin only. The first POST names what is lost; confirmed=1 does it."""
    if not request.user.is_admin:
        raise PermissionDenied
    kind, record_id = _kind(request), _record_id(request)
    obj = get_record(Ctx(request.profile, request.user), kind, record_id, lock=False, include_deleted=True)
    if obj.deleted_at is None:
        messages.error(request, "Only records in the Trash can be deleted permanently.")
        return redirect(reverse("trash"))
    if not request.POST.get("confirmed"):
        return _permanent_page(request, kind, obj)
    try:
        result = svc.permanent_delete(request.profile, request.user, kind, record_id)
    except PermanentDeleteRefused:
        return _permanent_page(request, kind, obj, status=409)
    total = sum(result.info.get("deleted", {}).values())
    messages.success(request, f"Deleted permanently: {total} record(s). Their version history is kept.")
    return redirect(reverse("trash"))
