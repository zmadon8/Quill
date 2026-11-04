"""The Item editor (Milestone 3c, docs/DESIGN.md sections 5.5 and 11).

Same rules as ``views_edit``: Editors of the signed-in user's profile only (Readers get 403, another
profile's ids give 404), POST with the CSRF token for every change, and every change goes through the
service layer. The editor page itself is a GET; saving is a POST of the whole form carrying the
version of the Item (and of each Case), so a stale save shows the conflict page and nothing is saved.
"""
from django.contrib import messages
from django.db import transaction
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse

from . import inline
from . import services as svc
from .models import CITATION_LAYOUT_CHOICES, FLAG_CHOICES, Case, Item
from .services.core import ancestors, label
from .services.errors import Conflict, Refused, ValidationFailed
from .views_edit import FLAG_TEXT_MAX, _next, _single_line, _version, editor_page, is_fetch



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
    return reverse("diary_home")


# ------------------------------------------------------------------ reading the form

def _case_rows(post):
    """The Cases as posted, in the order shown: [{id, version, citation, comment}]. Blank new rows are dropped."""
    ids, versions = post.getlist("case_id"), post.getlist("case_version")
    citations, comments = post.getlist("case_citation"), post.getlist("case_comment")
    # Older pages (open since before round 16) send no case_url: then the addresses are left as they are (None).
    urls = post.getlist("case_url") if "case_url" in post else None
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
            "url": (urls[number] if number < len(urls) else "") if urls is not None else None,
        }
        if row["id"] is None and not row["citation"] and not row["comment"].strip() and not (row["url"] or "").strip():
            continue
        rows.append(row)
    return rows


def _has_case_fields(post):
    """True if the form carried the citations list at all (a post without it must not wipe the citations)."""
    return any(name in post for name in ("case_id", "case_citation", "case_gone"))


def _gone_versions(post):
    """{case id: version} of the Cases the Editor removed, from 'id:version' values."""
    found = {}
    for value in post.getlist("case_gone"):
        raw_id, _, raw_version = value.partition(":")
        if raw_id.isdigit():
            found[int(raw_id)] = int(raw_version) if raw_version.isdigit() else None
    return found


def _layout(post):
    """The posted way to show citations ("inline" or "lines"), or None when the form did not send one."""
    value = post.get("citation_layout", "")
    return value if value in dict(CITATION_LAYOUT_CHOICES) else None


def _values(post):
    flag = post.get("flag", "none")
    return {
        "text": post.get("text", ""),
        "citation_layout": _layout(post),
        "flag": flag,
        "flag_text": "" if flag == "none" else _single_line(post.get("flag_text", "")),
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
        url_changes = {} if row["url"] is None else {"url": row["url"]}
        if row["id"] and not row["citation"] and not row["comment"].strip() and not (row["url"] or "").strip():
            svc.delete(profile, user, "case", row["id"], row["version"])
        elif row["id"]:
            svc.edit(profile, user, "case", row["id"], {"citation": row["citation"], "comment": row["comment"], **url_changes},
                     row["version"])
            order.append(row["id"])
        else:
            made = svc.create(profile, user, "case", parent=("item", item.pk), citation=row["citation"],
                              comment=row["comment"], **url_changes)
            order.append(made.record.pk)
    for index, pk in enumerate(order):
        svc.move(profile, user, "case", pk, None, index)


def _save(request, item, back):
    post = request.POST
    values = _values(post)
    with_cases = _has_case_fields(post)
    rows = _case_rows(post) if with_cases else []
    gone = _gone_versions(post)
    try:
        with transaction.atomic():
            if len(values["flag_text"]) > FLAG_TEXT_MAX:
                raise ValidationFailed(f"The flag text is too long ({FLAG_TEXT_MAX} characters at most).")
            changes = {name: values[name] for name in ("text", "flag", "flag_text")}
            if values["citation_layout"] is not None:
                changes["citation_layout"] = values["citation_layout"]
            svc.edit(request.profile, request.user, "item", item.pk, changes, _version(request))
            if with_cases:
                _save_cases(request, item, rows, gone)
    except Conflict as exc:
        # Show everything that was typed, not only the part that clashed, so nothing is lost.
        exc.mine = _everything_typed(values, rows)
        raise
    except Refused as exc:
        if is_fetch(request):
            raise  # the guard turns it into JSON (400)
        messages.error(request, exc.message)
        return _render(request, item, back, values=values, rows=rows if with_cases else None, status=400)
    if is_fetch(request):
        return inline.ok(request, **inline.row_payload(request, "item", item.pk, back))
    messages.success(request, "Saved.")
    return redirect(back)


def _everything_typed(values, rows):
    shown = {"Text": values["text"], "Flag": values["flag"], "Flag text": values["flag_text"]}
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
        values = {"text": item.text, "citation_layout": item.citation_layout, "flag": item.flag,
                  "flag_text": item.flag_text}
    if values.get("citation_layout") is None:
        values = {**values, "citation_layout": item.citation_layout}
    if rows is None:
        cases = Case._base_manager.filter(item=item, deleted_at__isnull=True, profile=request.profile)
        rows = [{"id": c.pk, "version": c.version, "citation": c.citation, "comment": c.comment, "url": c.url}
                for c in cases.order_by("position", "pk")]
    if not rows:
        # The first row is the main citation box; it is always there, empty if the Item has no citation yet.
        rows = [{"id": None, "version": None, "citation": "", "comment": "", "url": ""}]
    context = {
        "item": item,
        "kind_name": "Item",
        "values": values,
        "rows": rows,
        "flag_choices": FLAG_CHOICES,
        "layout_choices": CITATION_LAYOUT_CHOICES,
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
    rows = _case_rows(request.POST) if _has_case_fields(request.POST) else None
    messages.info(request, "Someone else changed this Item. Your text is below; compare it with the saved version, then Save.")
    return _render(request, item, back, values=values, rows=rows, theirs=True)
