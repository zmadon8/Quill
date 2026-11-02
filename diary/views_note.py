"""The Note editor, its links and the link picker (Milestone 5, docs/DESIGN.md section 7 and decisions D33 onward).

Same rules as ``views_edit``: Editors of the signed-in user's profile only (Readers get 403, another profile's ids
give 404), POST with the CSRF token for every change, every change through the service layer. A Note is edited on its
own page (full screen on a phone): text, its links (add, remove, reorder) and More (Move to, Move up/down, History,
Delete). Every button on that page posts the whole form, so text typed but not yet saved is saved first with the
version it was opened at, in the same Undo step.
"""
from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse

from . import reading
from . import services as svc
from .models import Note, NoteLink, Subject, Subtopic, Topic
from .services.core import Ctx, ancestors, get_record, label, record_type
from .services.links import TARGET_KINDS
from .services.moves import NICE
from .services.sequences import members
from .sorting import sort_headings
from .views_edit import _next, _version, edit_endpoint, editor_page

#: Where a Note may sit and what a link may point at: the same five kinds of record (an Item may be a Nested Item or one inside it).
PLACE_KINDS = TARGET_KINDS
PURPOSES = ("link", "retarget", "move")


def _load_note(request, pk):
    note = Note._base_manager.filter(pk=pk, profile=request.profile, deleted_at__isnull=True).first()
    if note is None:
        raise Http404("That Note does not exist.")
    return note


def _default_back(note):
    """The reading view of the Subject the Note is in, at the Note (Edit mode on)."""
    chain = ancestors(note)
    if chain and chain[0][0] == "subject":
        return f"{reverse('read_subject', args=[chain[0][1].pk])}?edit=1#n-note-{note.pk}"
    return reverse("diary_home")


def _editor_url(note, back):
    return f"{reverse('edit_note', args=[note.pk])}?{urlencode({'next': back})}"


def _save_text_first(request, note):
    """Save the typed text if the form carried it (so no button on the page loses it). Returns True if it was saved."""
    if "text" not in request.POST:
        return False
    result = svc.edit(request.profile, request.user, "note", note.pk, {"text": request.POST.get("text", "")},
                      _version(request))
    return result.changed


def _person(user):
    if user is None:
        return "unknown"
    return user.get_full_name() or user.get_username()


def _link_rows(request, note):
    rows = []
    links = NoteLink._base_manager.filter(note=note, profile=request.profile, deleted_at__isnull=True)
    for link in links.order_by("position", "pk"):
        info = reading.note_link_info(link)
        rows.append({"id": link.pk, "version": link.version, "path": info["path"], "url": info["url"],
                     "gone": info["deleted"]})
    return rows


def _render(request, note, back, text=None, theirs=False, status=200):
    chain = ancestors(note)
    siblings = members(request.profile.pk, ("note", *_note_key(note)))
    context = {
        "note": note,
        "values": {"text": note.text if text is None else text},
        "links": _link_rows(request, note),
        "back": back,
        "where": " \u203a ".join(label(parent) for _, parent in chain),
        "created_by": _person(note.created_by),
        "updated_by": _person(note.updated_by),
        "can_shift": len(siblings) > 1,
        "theirs": theirs,
    }
    return render(request, "diary/note_editor.html", context, status=status)


def _note_key(note):
    for column in ("item", "section", "subtopic", "topic", "subject"):
        if getattr(note, f"{column}_id"):
            return column, getattr(note, f"{column}_id")
    raise Http404("That Note has no place.")


@editor_page
def note_editor(request, pk):
    """GET: the editor. POST: save the text (the form carries the version the Note was opened at)."""
    note = _load_note(request, pk)
    back = _next(request, _default_back(note))
    if request.method == "GET":
        return _render(request, note, back)
    if request.POST.get("merge"):
        messages.info(request, "Someone else changed this Note. Your text is below; compare it with the saved version, then Save.")
        return _render(request, note, back, text=request.POST.get("text", ""), theirs=True)
    result = svc.edit(request.profile, request.user, "note", note.pk, {"text": request.POST.get("text", "")},
                      _version(request))
    messages.success(request, "Saved." if result.changed else "No change.")
    return redirect(back)


def _target(request, name="target"):
    """('item', 5) from 'item:5'."""
    kind, _, pk = request.POST.get(name, "").partition(":")
    if kind not in PLACE_KINDS or not pk.isdigit():
        raise Http404("Unknown place.")
    return kind, int(pk)


@edit_endpoint
def note_link(request):
    """One action on the links of a Note, chosen by ``op``.

    ``add`` (``note``, ``target`` 'type:id'), ``up:<link id>`` / ``down:<link id>``, ``remove:<link id>`` (to the Trash,
    Undo available), ``retarget`` (``link``, ``target``) and ``purge`` (``link``: Admin only, removes a link for good,
    used from the permanent delete screen). Typed Note text in the same form is saved first. The answer is a redirect
    back to the editor (or to ``next``).
    """
    post = request.POST
    op, _, op_id = post.get("op", "").partition(":")
    note = None
    if post.get("note", "").isdigit():
        note = _load_note(request, int(post["note"]))
    back = _next(request)
    editor = _editor_url(note, _next(request, _default_back(note))) if note is not None else back
    if note is not None:
        _save_text_first(request, note)
    link_id = int(op_id) if op_id.isdigit() else (int(post["link"]) if post.get("link", "").isdigit() else None)
    if op == "add":
        if note is None:
            raise Http404("Unknown Note.")
        result = svc.add_link(request.profile, request.user, note.pk, _target(request))
        messages.success(request, "Link added." if result.changed else "That link is already there.")
        return redirect(editor)
    if link_id is None:
        raise Http404("Unknown link.")
    if op in ("up", "down"):
        svc.shift_link(request.profile, request.user, link_id, -1 if op == "up" else 1)
        return redirect(editor)
    if op == "remove":
        version = post.get(f"lv_{link_id}", "")
        svc.delete(request.profile, request.user, "notelink", link_id, int(version) if version.isdigit() else None)
        messages.success(request, "Link removed. It is in the Trash and Undo brings it back.")
        return redirect(editor)
    if op == "retarget":
        result = svc.retarget_link(request.profile, request.user, link_id, _target(request))
        messages.success(request, "The link now points at the new place." if result.changed else "It already points there.")
        return redirect(editor if note is not None else back)
    if op == "purge":
        if not request.user.is_admin:
            raise PermissionDenied
        svc.purge_link(request.profile, request.user, link_id)
        messages.success(request, "Link removed for good. Its version history is kept. Try the permanent delete again.")
        return redirect(back)
    raise Http404("Unknown action.")


# ------------------------------------------------------------------ the picker

def _entry(obj, kind):
    kind_name = "Nested Item" if kind == "item" and obj.kind == "nested" else NICE[kind]
    opens = kind in ("subject", "topic", "subtopic") or (kind == "item" and obj.kind == "nested" and not obj.parent_item_id)
    return {"type": kind, "id": obj.pk, "label": label(obj), "kind_name": kind_name, "opens": opens}


def _children(profile, kind, obj):
    """The records directly inside a Subject, Topic, Sub-topic or Nested Item, headings first, then its Items and Sections."""
    live = {"profile": profile, "deleted_at__isnull": True}
    found = []
    if kind == "subject":
        found += [(t, "topic") for t in sort_headings(Topic.objects.filter(subject=obj, **live))]
        found += [(s, "subtopic") for s in sort_headings(Subtopic.objects.filter(subject=obj, **live))]
    elif kind == "topic":
        found += [(s, "subtopic") for s in sort_headings(Subtopic.objects.filter(topic=obj, **live))]
    if kind in ("subject", "topic", "subtopic"):
        for rec in members(profile.pk, ("run", kind, obj.pk)):
            found.append((rec, record_type(rec)))
    elif kind == "item":
        found += [(rec, "item") for rec in members(profile.pk, ("kids", "parent_item", obj.pk))]
    return [_entry(rec, rec_kind) for rec, rec_kind in found]


def _subjects(profile):
    live = {"profile": profile, "deleted_at__isnull": True}
    rows = sort_headings(Subject.objects.filter(show_on_landing=True, **live))
    rows += sort_headings(Subject.objects.filter(show_on_landing=False, **live))
    return [_entry(s, "subject") for s in rows]


@editor_page
def note_pick(request):
    """The tree picker for a Note: choose a place for a new link (``purpose=link``), another target for an existing link
    (``retarget``) or a new home for the Note (``move``). Drill down with ``at=type:id``; Subjects, Topics, Sub-topics,
    Sections, Items and Nested Items (and the Items inside them) can all be chosen. A POST (from the editor's "Add a
    link" button) saves the typed text first and then shows the picker.
    """
    source = request.POST if request.method == "POST" else request.GET
    purpose = source.get("purpose", "link" if request.method == "POST" else "")
    if purpose not in PURPOSES:
        raise Http404("Unknown purpose.")
    note = None
    link = None
    if purpose == "retarget":
        value = source.get("link", "")
        link = NoteLink._base_manager.filter(pk=value if value.isdigit() else 0, profile=request.profile).first()
        if link is None:
            raise Http404("Unknown link.")
        note_id = link.note_id
    else:
        value = source.get("note", "")
        if not value.isdigit():
            raise Http404("Unknown Note.")
        note_id = int(value)
    if purpose != "retarget":
        note = _load_note(request, note_id)
        if request.method == "POST":
            _save_text_first(request, note)
    back = _next(request)
    if request.method == "POST":
        params = {"purpose": purpose, "note": note.pk, "next": back}
        return redirect(f"{reverse('edit_note_pick')}?{urlencode(params)}")
    ctx_user = request.user
    at = source.get("at", "")
    here = None
    crumbs = []
    entries = []
    if at:
        kind, _, pk = at.partition(":")
        if kind not in PLACE_KINDS or not pk.isdigit():
            raise Http404("Unknown place.")
        obj = get_record(Ctx(request.profile, ctx_user), kind, int(pk), lock=False)
        here = _entry(obj, kind)
        crumbs = [{"label": label(parent), "at": f"{parent_kind}:{parent.pk}"} for parent_kind, parent in ancestors(obj)]
        entries = _children(request.profile, kind, obj)
    else:
        entries = _subjects(request.profile)
    params = {"purpose": purpose, "next": back}
    if note is not None:
        params["note"] = note.pk
    if link is not None:
        params["link"] = link.pk
        if source.get("note", "").isdigit():
            params["note"] = source["note"]
    context = {
        "purpose": purpose,
        "note": note,
        "link": link,
        "here": here,
        "crumbs": crumbs,
        "entries": entries,
        "base": f"{reverse('edit_note_pick')}?{urlencode(params)}",
        "back": back,
        "note_label": label(note) if note is not None else label(link.note),
        "version": note.version if note is not None else "",
        "link_version": link.version if link is not None else "",
        "editor_url": _editor_url(note or link.note, back),
        "owner_note": source.get("note", "") if purpose == "retarget" and source.get("note", "").isdigit() else "",
    }
    return render(request, "diary/note_pick.html", context)
