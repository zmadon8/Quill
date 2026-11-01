"""The conflict screen (Milestone 3d, docs/DESIGN.md section 9.2 and decision M3-22).

Shown (HTTP 409) when a save, move, delete, restore or conversion was made against an older version
of a record. Nothing was saved. It shows what the Editor asked for next to what is stored now and
offers three choices:

* keep mine: the same request is sent again with the current version number, so it goes through;
* keep theirs: go back without changing anything;
* edit and merge: edit what was typed (the Item editor, the name box, the review note, or the tree
  picker for a move) with the current version number, then save.

Every typed value is carried in hidden fields, so nothing the Editor typed is lost.
"""
import html

from django.shortcuts import render
from django.utils.html import strip_tags

from .models import Case
from .services.core import MODELS
from .services.moves import NICE

#: What an address means, for conflicts that have no typed fields to compare.
OPERATIONS = {
    "edit_delete": "Move to the Trash",
    "edit_move": "Move to another place",
    "edit_landing": "Change where the Subject is listed",
    "edit_item_convert": "Change the type of the Item",
    "edit_item": "Save the Item",
    "trash_restore": "Restore from the Trash",
    "history_restore": "Restore an earlier version",
}
#: Posted fields the merge form lets the Editor change, per address: (field, label, multi-line).
MERGEABLE = {
    "edit_rename": ("name", "Name", False),
    "edit_review": ("note", "Review note", True),
}
IGNORED = {"csrfmiddlewaretoken", "merge"}


def plain(value):
    """A value as short readable text (formatting removed, yes/no for switches)."""
    if value is True:
        return "yes"
    if value is False:
        return "no"
    if value is None:
        return ""
    return html.unescape(strip_tags(str(value))).strip()


def _current_version(profile, kind, pk):
    model = MODELS.get(kind)
    if model is None or not str(pk).isdigit():
        return None
    return model._base_manager.filter(pk=int(pk), profile=profile).values_list("version", flat=True).first()


def _main_record(request):
    pk = request.resolver_match.kwargs.get("pk")
    if pk is not None:
        return "item", pk
    return request.POST.get("kind", ""), request.POST.get("id", "")


def fresh_fields(request):
    """The posted fields again, as [(name, value)], with every version number brought up to date.

    This is what "keep mine" and "edit and merge" send: the same request, now made against the
    current versions, so the Editor's explicit choice decides instead of a silent overwrite.
    """
    profile = request.profile
    kind, pk = _main_record(request)
    current = _current_version(profile, kind, pk)
    case_versions = {}
    if "case_id" in request.POST:
        ids = [int(v) for v in request.POST.getlist("case_id") if v.isdigit()]
        case_versions = dict(Case._base_manager.filter(pk__in=ids, profile=profile).values_list("pk", "version"))
    pairs = []
    cases = iter(request.POST.getlist("case_id"))
    for name, values in request.POST.lists():
        if name in IGNORED:
            continue
        for value in values:
            if name == "version" and current is not None:
                value = current
            elif name == "case_version":
                case_id = next(cases, "")
                if case_id.isdigit() and int(case_id) in case_versions:
                    value = case_versions[int(case_id)]
            elif name == "case_gone":
                raw_id = value.partition(":")[0]
                if raw_id.isdigit():
                    live = _current_version(profile, "case", raw_id)
                    if live is not None:
                        value = f"{raw_id}:{live}"
            pairs.append((name, value))
    return pairs


def _pretty(field):
    return field.replace("_", " ").capitalize()


def comparison(request, exc):
    """[(label, mine, theirs, differs)] for the side by side view."""
    name = request.resolver_match.url_name
    theirs = exc.theirs or {}
    rows = []
    if name == "edit_item":
        labels = {"Text": "text", "Citation": "citation", "Flag": "flag", "Flag text": "flag_text",
                  "For review": "needs_review", "Review note": "review_note"}
        for label_, value in exc.mine.items():
            column = labels.get(label_)
            stored = plain(theirs.get(column)) if column and exc.record_type == "item" else ""
            rows.append((label_, plain(value), stored, plain(value) != stored))
        if exc.record_type == "case":
            for column in ("citation", "comment"):
                rows.append((f"A Case changed by someone else: {column}", "(your Cases are listed above)",
                             plain(theirs.get(column)), True))
        return rows
    if exc.mine:
        for column, value in exc.mine.items():
            stored = plain(theirs.get(column))
            rows.append((_pretty(column), plain(value), stored, plain(value) != stored))
        return rows
    direction = request.POST.get("direction", "")
    asked = {"up": "Move up", "down": "Move down"}.get(direction) or OPERATIONS.get(name, "Change it")
    now = plain(theirs.get("name") or theirs.get("text") or theirs.get("citation") or "")
    deleted = " It is now in the Trash." if theirs.get("deleted_at") else ""
    rows.append(("What you asked for", asked, f"{now} (version {exc.current_version}).{deleted}".strip(), True))
    return rows


def conflict_page(request, exc, next_url):
    name = request.resolver_match.url_name
    pairs = fresh_fields(request)
    merge = {}
    if name == "edit_item":
        merge = {"type": "editor"}
    elif name in MERGEABLE and MERGEABLE[name][0] in request.POST:
        field, label_, multiline = MERGEABLE[name]
        merge = {"type": "fields", "field": field, "label": label_, "multiline": multiline,
                 "value": request.POST.get(field, "")}
        pairs = [(n, v) for n, v in pairs if n != field]
    elif name == "edit_move" and not request.POST.get("direction"):
        picker = {n: v for n, v in pairs if n in ("kind", "id", "version", "next")}
        merge = {"type": "picker", "fields": sorted(picker.items())}
    context = {
        "error": exc,
        "next_url": next_url,
        "kind_name": NICE.get(exc.record_type, "record"),
        "rows": comparison(request, exc),
        "fields": pairs,
        "action": request.path,
        "merge": merge,
    }
    return render(request, "diary/edit_conflict.html", context, status=409)
