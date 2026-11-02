"""The Item editor, conversions and the review marker switch (Milestone 3c, docs/DESIGN.md sections 5.5, 6 and 11).

Same rules as ``views_edit``: Editors of the signed-in user's profile only (Readers get 403, another
profile's ids give 404), POST with the CSRF token for every change, and every change goes through the
service layer. The editor page itself is a GET; saving is a POST of the whole form carrying the
version of the Item (and of each Case), so a stale save shows the conflict page and nothing is saved.
"""
from urllib.parse import urlencode

from django.contrib import messages
from django.db import transaction
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse

from . import services as svc
from .models import FLAG_CHOICES, KIND_CHOICES, KIND_NESTED, Case, Item
from .services.core import ancestors, label
from .services.errors import Conflict, Refused, ValidationFailed
from .views_edit import _next, _record_id, _single_line, _version, edit_endpoint, editor_page

FLAG_TEXT_MAX = 300
KIND_NAMES = dict(KIND_CHOICES)


def _load_item(request, pk):
    item = Item._base_manager.filter(pk=pk, profile=request.profile, deleted_at__isnull=True).first()
    if item is None:
        raise Http404("That Item does not exist.")
    return item


def _default_back(item):
    """The reading view of the Subject the Item is in, at the Item (Edit mode on)."""
    chain = ancestors(item)
    if chain and chain[0][0] == "subject":
        return f"{reverse('read_subject', args=[chain[0][1].pk])}?edit=1#n-item-{item.pk}"
    return reverse("subjects")


def _editor_url(item, back):
    return f"{reverse('edit_item', args=[item.pk])}?{urlencode({'next': back})}"


# ------------------------------------------------------------------ reading the form

def _case_rows(post):
    """The Cases as posted, in the order shown: [{id, version, citation, comment}]. Blank new rows are dropped."""
    ids, versions = post.getlist("case_id"), post.getlist("case_version")
    citations, comments = post.getlist("case_citation"), post.getlist("case_comment")
    rows = []
    for number in range(len(citations)):
        raw_id = ids[number] if number < len(ids) else ""
        if raw_id and not raw_id.isdigit():
            raise Http404("That Case does not exist.")
        raw_version = versions[number] if number < len(versions) else ""
        row = {
            "id": int(raw_id) if raw_id else None,
            "version": int(raw_version) if raw_version.isdigit() else None,
            "citation": _single_line(citations[number]),
            "comment": comments[number] if number < len(comments) else "",
        }
        if row["id"] is None and not row["citation"] and not row["comment"].strip():
            continue
        rows.append(row)
    return rows


def _gone_versions(post):
    """{case id: version} of the Cases the Editor removed, from 'id:version' values."""
    found = {}
    for value in post.getlist("case_gone"):
        raw_id, _, raw_version = value.partition(":")
        if raw_id.isdigit():
            found[int(raw_id)] = int(raw_version) if raw_version.isdigit() else None
    return found


def _values(post):
    flag = post.get("flag", "none")
    return {
        "text": post.get("text", ""),
        "citation": _single_line(post.get("citation", "")),
        "flag": flag,
        "flag_text": "" if flag == "none" else _single_line(post.get("flag_text", "")),
        "needs_review": post.get("needs_review") == "1",
        "review_note": post.get("review_note", "").strip(),
    }


# ------------------------------------------------------------------ saving

def _save_cases(request, item, rows, gone):
    """Edit, add, remove and reorder the citations (Cases) of an Item so they end up exactly as posted.

    A saved citation whose citation and comment were both emptied is removed (to the Trash, with the
    version check), never kept as an empty Case and never dropped without that record.
    """
    profile, user = request.profile, request.user
    live = {c.pk: c for c in Case._base_manager.filter(item=item, deleted_at__isnull=True, profile=profile)}
    posted = {row["id"] for row in rows if row["id"]}
    for row in rows:
        if row["id"] and row["id"] not in live:
            raise Http404("That Case does not exist.")
    for pk in live:
        if pk not in posted:
            svc.delete(profile, user, "case", pk, gone.get(pk))
    order = []
    for row in rows:
        if row["id"] and not row["citation"] and not row["comment"].strip():
            svc.delete(profile, user, "case", row["id"], row["version"])
        elif row["id"]:
            svc.edit(profile, user, "case", row["id"], {"citation": row["citation"], "comment": row["comment"]},
                     row["version"])
            order.append(row["id"])
        else:
            made = svc.create(profile, user, "case", parent=("item", item.pk), citation=row["citation"],
                              comment=row["comment"])
            order.append(made.record.pk)
    for index, pk in enumerate(order):
        svc.move(profile, user, "case", pk, None, index)


def _save(request, item, back):
    post = request.POST
    values = _values(post)
    rows = _case_rows(post) if item.kind != KIND_NESTED else []
    gone = _gone_versions(post)
    try:
        with transaction.atomic():
            if len(values["flag_text"]) > FLAG_TEXT_MAX:
                raise ValidationFailed(f"The flag text is too long ({FLAG_TEXT_MAX} characters at most).")
            changes = {name: values[name] for name in ("text", "flag", "flag_text", "needs_review", "review_note")}
            if item.kind == KIND_NESTED:
                changes["citation"] = values["citation"]
            svc.edit(request.profile, request.user, "item", item.pk, changes, _version(request))
            if item.kind != KIND_NESTED:
                _save_cases(request, item, rows, gone)
    except Conflict as exc:
        # Show everything that was typed, not only the part that clashed, so nothing is lost.
        exc.mine = _everything_typed(values, rows, item.kind)
        raise
    except Refused as exc:
        messages.error(request, exc.message)
        return _render(request, item, back, values=values, rows=rows, status=400)
    messages.success(request, "Saved.")
    return redirect(back)


def _everything_typed(values, rows, kind):
    shown = {"Text": values["text"], "Flag": values["flag"], "Flag text": values["flag_text"],
             "For review": "yes" if values["needs_review"] else "no", "Review note": values["review_note"]}
    if kind == KIND_NESTED:
        shown["Citation"] = values["citation"]
    for number, row in enumerate(rows, start=1):
        shown[f"Citation {number}"] = row["citation"]
        shown[f"Citation {number} comment"] = row["comment"]
    return shown


# ------------------------------------------------------------------ the editor page

def _person(user):
    if user is None:
        return "unknown"
    return user.get_full_name() or user.get_username()


def _render(request, item, back, values=None, rows=None, status=200, theirs=False):
    if values is None:
        values = {"text": item.text, "citation": item.citation, "flag": item.flag, "flag_text": item.flag_text,
                  "needs_review": item.needs_review, "review_note": item.review_note}
    if rows is None:
        cases = Case._base_manager.filter(item=item, deleted_at__isnull=True, profile=request.profile)
        rows = [{"id": c.pk, "version": c.version, "citation": c.citation, "comment": c.comment}
                for c in cases.order_by("position", "pk")]
    if item.kind != KIND_NESTED and not rows:
        # The first row is the main citation box; it is always there, empty if the Item has no citation yet.
        rows = [{"id": None, "version": None, "citation": "", "comment": ""}]
    convertible = [] if item.parent_item_id else [(key, name) for key, name in KIND_CHOICES if key != item.kind]
    context = {
        "item": item,
        "kind_name": KIND_NAMES[item.kind],
        "has_cases": item.kind != KIND_NESTED,
        "values": values,
        "rows": rows,
        "flag_choices": FLAG_CHOICES,
        "convertible": convertible,
        "back": back,
        "created_by": _person(item.created_by),
        "updated_by": _person(item.updated_by),
        "item_label": label(item),
        "theirs": theirs,
    }
    return render(request, "diary/item_editor.html", context, status=status)


@editor_page
def item_editor(request, pk):
    """GET: the editor. POST: save it (the whole form, with the versions it was opened at)."""
    item = _load_item(request, pk)
    back = _next(request, _default_back(item))
    if request.method == "POST" and request.POST.get("merge"):
        return _merge(request, item, back)
    if request.method == "POST":
        return _save(request, item, back)
    return _render(request, item, back)


def _merge(request, item, back):
    """Edit and merge (after a conflict): the editor again with what was typed, at the current version.

    Nothing is saved. The saved values are shown above the form for comparison.
    """
    values = _values(request.POST)
    rows = _case_rows(request.POST) if item.kind != KIND_NESTED else []
    messages.info(request, "Someone else changed this Item. Your text is below; compare it with the saved version, then Save.")
    return _render(request, item, back, values=values, rows=rows, theirs=True)


# ------------------------------------------------------------------ conversions

@edit_endpoint
def item_convert(request, pk):
    """Change to Item / Nested Item. The first POST shows the preview; confirmed=1 does it."""
    item = _load_item(request, pk)
    post = request.POST
    back = _next(request, _default_back(item))
    to_kind = post.get("to_kind", "")
    option = post.get("option") or None
    editor = _editor_url(item, back)
    if post.get("confirmed"):
        try:
            result = svc.convert_item(request.profile, request.user, item.pk, to_kind, _version(request), option,
                                      accept_warnings=post.get("accept") == "1")
        except (Refused, svc.ConfirmationRequired) as exc:
            messages.error(request, exc.message)
        else:
            if result.changed:
                messages.success(request, f"Changed to {KIND_NAMES[to_kind]}.")
            else:
                messages.info(request, f"It is already a {KIND_NAMES[to_kind]}.")
            return redirect(editor)
    preview = svc.preview_conversion(request.profile, request.user, item.pk, to_kind, option)
    if not preview["changed"]:
        messages.info(request, f"It is already a {KIND_NAMES[to_kind]}.")
        return redirect(editor)
    context = {
        "item": item,
        "preview": preview,
        "from_name": KIND_NAMES[preview["from_kind"]],
        "to_name": KIND_NAMES[preview["to_kind"]],
        "to_kind": preview["to_kind"],
        "option": option or "",
        "back": back,
        "editor_url": editor,
        "version": item.version,
        "item_label": label(item),
    }
    return render(request, "diary/item_convert.html", context)


# ------------------------------------------------------------------ review marker

@edit_endpoint
def review(request):
    """One click set or clear of the For review marker on an Item or a Section.

    ``set`` is 1 or 0. A note may come with it (``note``); clearing the marker also clears the note
    (the old note stays in the history).
    """
    kind = request.POST.get("kind", "")
    if kind not in ("item", "section"):
        raise Http404("Only Items and Sections have a For review marker.")
    marked = request.POST.get("set") == "1"
    changes = {"needs_review": marked}
    if not marked:
        changes["review_note"] = ""
    elif "note" in request.POST:
        changes["review_note"] = request.POST.get("note", "").strip()
    result = svc.edit(request.profile, request.user, kind, _record_id(request), changes, _version(request))
    if not result.changed:
        messages.info(request, "No change.")
    else:
        messages.success(request, "Marked for review." if marked else "Review marker cleared.")
    return redirect(_next(request))
