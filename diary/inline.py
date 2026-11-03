"""Helpers for the inline Edit mode (Round 7, docs/DESIGN.md Edit mode): which kinds a row's "+ Add" offers, and the
JSON the script gets back after a change (the changed row as HTML, the new numbers, the Undo step).

No view lives here. ``views_inline`` (the form and card fragments), ``views_edit`` and ``views_item`` (the changes,
which answer a request with the header ``X-Requested-With: fetch`` in JSON) use it.
"""
from django.http import JsonResponse
from django.template.loader import render_to_string

from . import reading, undo_session
from .services.core import Ctx, ancestors, get_record
from .services.moves import NICE
from .templatetags.diary_tags import dotted

#: Choice value -> button text, per kind of row. A choice is "<mode>:<what>": "inside" puts the new entry first inside
#: the row (a heading), "after" puts it directly after the row. ``what`` is a key of views_edit.ADDABLE.
CHOICE_LABELS = {
    "after:item": "Item",
    "after:section": "Section",
    "after:topic": "Topic",
    "after:subtopic": "Sub-topic",
    "inside:item": "Item inside",
    "inside:topic": "Topic",
    "inside:subtopic": "Sub-topic",
    "inside:note": "Note",
}
#: What can carry a citation (the others get a greyed-out citation box).
CITATION_WHATS = ("item",)


def add_choices(profile, kind, record):
    """[(choice, label)] that "+ Add" offers on a row of ``kind`` ('subject', 'topic', 'subtopic', 'section', 'item').

    After an Item or Section: Item, Section. Every row also offers Note ("inside:note": a Note on that Subject, Topic, Sub-topic, Section or Item, shown beneath it). After a Topic: Item inside, Sub-topic, Topic. After a
    Sub-topic: Item inside, Sub-topic. A Subject offers Item inside, Topic and Note: every Subject is alike (D81), and a Sub-topic always
    sits in a Topic. Headings always land in their alphabetical place.
    """
    if kind in ("item", "section"):
        return [(c, CHOICE_LABELS[c]) for c in ("after:item", "after:section", "inside:note")]
    if kind == "topic":
        return [(c, CHOICE_LABELS[c]) for c in ("inside:item", "inside:subtopic", "inside:note", "after:topic")]
    if kind == "subtopic":
        return [(c, CHOICE_LABELS[c]) for c in ("inside:item", "inside:note", "after:subtopic")]
    if kind == "subject":
        wanted = ["inside:item", "inside:topic", "inside:note"]
        return [(c, CHOICE_LABELS[c]) for c in wanted]
    return []


def undo_payload(request):
    """{'group', 'text'} of the action just made in this request, or None when it wrote nothing."""
    group = getattr(request, "undo_group", None)
    if group is None:
        return None
    from .models import VersionHistory

    if not VersionHistory.objects.filter(profile=request.profile, group=group).exists():
        return None
    return {"group": str(group), "text": undo_session.describe(request.profile, group)}


def ok(request, **data):
    """The JSON answer to a successful change made with fetch."""
    return JsonResponse({"ok": True, "undo": undo_payload(request), **data})


def _subject_of(request, kind, pk):
    obj = get_record(Ctx(request.profile, request.user), kind, pk, lock=False, include_deleted=True)
    if kind == "subject":
        return obj
    chain = ancestors(obj)
    return chain[0][1] if chain and chain[0][0] == "subject" else None


def _walk(blocks):
    """Every Item and Section block."""
    for block in blocks:
        if block["kind"] in ("item", "section"):
            yield block


def row_payload(request, kind, pk, next_url):
    """What the script needs after a row was added or changed.

    ``element`` is the id of the element to replace (an Item's ``n-item-N``, a Section's wrapper ``row-n-section-N``), ``anchor`` the id of the Item or Section
    itself (for links), ``html`` its new markup, ``after_anchor`` the id of the row before it (the
    element to insert it after when ``anchor`` is not on the page yet; None when it is the first in the Subject), and
    ``labels`` the new generated number of every Item and Section of the Subject, keyed by anchor. A
    heading (or anything not an Item or Section) gives ``{"reload": True}``: its place and the Contents panel change.
    """
    if kind not in ("item", "section"):
        return {"reload": True}
    subject = _subject_of(request, kind, pk)
    if subject is None:
        return {"reload": True}
    blocks = reading.build_reading(subject, request.user)["blocks"]
    found = [b for b in _walk(blocks) if b["kind"] == kind and b["id"] == pk]
    if not found:
        return {"reload": True}
    shown = found[0]
    html = render_to_string(
        "diary/_row.html",
        {"b": shown, "can_edit": True, "edit_mode": True, "next_url": next_url, "request": request},
        request=request,
    )
    previous = None
    for other in blocks:
        if other.get("anchor") == shown["anchor"]:
            break
        if other.get("anchor"):
            previous = other["anchor"]
    labels = {b["anchor"]: dotted(b["label"]) for b in _walk(blocks)}
    element = f"row-{shown['anchor']}" if shown["kind"] == "section" else shown["anchor"]
    return {"element": element, "anchor": shown["anchor"], "html": html, "after_anchor": previous, "labels": labels}


def labels_payload(request, kind, pk):
    """Just the new numbers (after a move), or a reload for anything that is not an Item or Section."""
    if kind not in ("item", "section"):
        return {"reload": True}
    subject = _subject_of(request, kind, pk)
    if subject is None:
        return {"reload": True}
    blocks = reading.build_reading(subject, request.user)["blocks"]
    return {"labels": {b["anchor"]: dotted(b["label"]) for b in _walk(blocks)}}


def kind_word(kind):
    return NICE.get(kind, "record")
