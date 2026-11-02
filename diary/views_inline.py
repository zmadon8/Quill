"""The pieces of the inline Edit mode that are fetched as HTML (Round 7, docs/DESIGN.md Edit mode).

Two GET endpoints, both for Editors of the signed-in user's profile only (Readers get 403, another profile's ids give
404, same guard as views_edit). Each answers JSON ``{"ok": true, "html": ...}`` with the form or card to put in place:

* ``edit_inline_add`` (GET ``?ref=item:5``): the "+ Add" form that opens under a row, with the kinds that row offers;
* ``edit_inline_card`` (GET ``?kind=item&id=5``): the editing card that replaces a row.

Saving is done by the existing endpoints (edit_add, edit_item, edit_rename, edit_review, edit_move, edit_delete,
edit_item_convert, edit_undo) when the request carries ``X-Requested-With: fetch``; see docs/DESIGN.md.
"""
from urllib.parse import urlencode

from django.http import Http404, JsonResponse
from django.template.loader import render_to_string
from django.urls import reverse

from . import inline
from .models import FLAG_CHOICES, KIND_NESTED, Case
from .reading import run_of
from .services.core import Ctx, ancestors, get_record, label
from .services.moves import NICE
from .views_edit import EDIT_KINDS, _next, editor_get


def _ref(request, name="ref"):
    value = request.GET.get(name, "")
    kind, _, pk = value.partition(":")
    if kind not in EDIT_KINDS or not pk.isdigit():
        raise Http404("Unknown place.")
    return kind, int(pk)


def _where(record):
    """'in A. Arbitrability' style hint: the names above the record, outermost first."""
    names = [label(parent) for _, parent in ancestors(record)]
    return ("in " + " \u203a ".join(names)) if names else ""


@editor_get
def add_form(request):
    """The inline "+ Add" form for the row ``ref`` ('item:5', 'topic:3', ...)."""
    kind, pk = _ref(request)
    record = get_record(Ctx(request.profile, request.user), kind, pk, lock=False)
    choices = inline.add_choices(request.profile, kind, record)
    if not choices:
        raise Http404("Nothing can be added there.")
    after = any(value.startswith("after:") for value, _ in choices)
    # The page address that does the same without JavaScript (the full Add page).
    fallback = f"{reverse('edit_add')}?" + urlencode(
        {"after" if after and kind != "subject" else "parent": f"{kind}:{pk}", "next": _next(request)}
    )
    title = f"Add {'after' if after else 'inside'} {NICE[kind]} \u201c{label(record)}\u201d"
    html = render_to_string("diary/_inline_add.html", {
        "ref": f"{kind}:{pk}", "ref_version": record.version, "title": title, "choices": choices,
        "default": choices[0][0], "citation_whats": " ".join(inline.CITATION_WHATS), "fallback": fallback,
        "next_url": _next(request),
    }, request=request)
    return JsonResponse({
        "ok": True, "html": html, "ref": f"{kind}:{pk}", "version": record.version, "fallback": fallback,
        "choices": [{"value": value, "label": text} for value, text in choices],
    })


@editor_get
def edit_card(request):
    """The editing card for one Item, Section, Subject, Topic or Sub-topic (``kind`` and ``id`` in the address)."""
    kind = request.GET.get("kind", "")
    pk = request.GET.get("id", "")
    if kind not in EDIT_KINDS or not pk.isdigit():
        raise Http404("Unknown record.")
    record = get_record(Ctx(request.profile, request.user), kind, int(pk), lock=False)
    back = _next(request)
    context = {
        "kind": kind, "record": record, "back": back, "where": _where(record),
        "title": f"Editing {NICE[kind]}", "can_move": kind != "subject", "can_shift": False, "convert_to": [],
    }
    fallback = back
    if kind == "item":
        cases = Case._base_manager.filter(item=record, deleted_at__isnull=True, profile=request.profile)
        rows = [{"id": c.pk, "version": c.version, "citation": c.citation, "comment": c.comment}
                for c in cases.order_by("position", "pk")]
        if record.kind != KIND_NESTED and not rows:
            rows = [{"id": None, "version": None, "citation": "", "comment": ""}]
        context.update(
            values={"text": record.text, "citation": record.citation, "flag": record.flag, "flag_text": record.flag_text,
                    "needs_review": record.needs_review, "review_note": record.review_note},
            rows=rows, flag_choices=FLAG_CHOICES, can_shift=bool(run_of(record)),
            title="Editing Nested Item" if record.kind == KIND_NESTED else "Editing Item",
        )
        if not record.parent_item_id:
            context["convert_to"] = [("plain", "Item")] if record.kind == KIND_NESTED else [("nested", "Nested Item")]
        fallback = reverse("edit_item", args=[record.pk]) + "?" + urlencode({"next": back})
    else:
        context["name"] = record.name
        if kind == "section":
            context.update(values={"needs_review": record.needs_review, "review_note": record.review_note},
                           can_shift=True)
    context["fallback"] = fallback
    html = render_to_string("diary/_inline_card.html", context, request=request)
    return JsonResponse({"ok": True, "html": html, "kind": kind, "id": record.pk, "version": record.version,
                         "fallback": fallback})
