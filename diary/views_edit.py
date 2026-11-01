"""Edit mode endpoints for headings and Items (Milestone 3b, docs/DESIGN.md decision M3-13).

Every endpoint is POST only, needs the CSRF token, and is for Editors of the signed-in user's
profile (Readers get 403; another profile's ids give 404). The views only read the form, call the
service layer in diary/services and send the browser back with a message. Nothing is changed
without going through the services, which do the renumbering, history and rules.
"""
from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseNotAllowed
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.html import escape
from django.utils.http import url_has_allowed_host_and_scheme

from . import services as svc
from . import undo_session
from .conflicts import conflict_page
from .models import Item, Subject, Subtopic, Topic
from .services.core import Ctx, descendants, get_record, label
from .services.errors import Conflict, NotFound, ServiceError
from .services.moves import ALLOWED_PARENTS, NICE
from .services.sequences import ident
from .views import profile_required, user_can_edit

EDIT_KINDS = ("subject", "topic", "subtopic", "section", "item")
RENAMEABLE = ("subject", "topic", "subtopic", "section")

#: What the Add form can create: choice -> (record type, extra fields).
ADDABLE = {
    "subject": ("subject", {}),
    "topic": ("topic", {}),
    "subtopic": ("subtopic", {}),
    "section": ("section", {}),
    "item": ("item", {"kind": "plain"}),
    "nested": ("item", {"kind": "nested"}),
}
ADD_NICE = {"nested": "Nested Item"}


def _next(request, default=None):
    """Where to go back to: the ``next`` address from the form (or the address) if it is on this site, else ``default`` or the Subjects page."""
    target = request.POST.get("next", "") or request.GET.get("next", "")
    if (
        target.startswith("/")
        and not target.startswith("//")
        and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure())
    ):
        return target
    return default or reverse("subjects")


def _conflict(request, exc):
    return conflict_page(request, exc, _next(request))


def _guarded(methods):
    """Decorator: signed in, has a profile, is an Editor of it, only ``methods``; service errors become messages or pages.

    A POST runs inside one Undo group (``action_group``), and the group is remembered in the session
    when the action wrote anything, so the Undo button reverses the whole action.
    """

    def decorate(view):
        @profile_required
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not user_can_edit(request):
                raise PermissionDenied
            if request.method not in methods:
                return HttpResponseNotAllowed(list(methods))
            with svc.action_group() as group:
                try:
                    response = view(request, *args, **kwargs)
                except NotFound as exc:
                    raise Http404(exc.message)
                except Conflict as exc:
                    response = _conflict(request, exc)
                except ServiceError as exc:
                    messages.error(request, exc.message or "That could not be done.")
                    response = redirect(_next(request))
            if request.method == "POST":
                undo_session.remember(request, group)
            return response

        return wrapper

    return decorate


#: POST only (every change).
edit_endpoint = _guarded(("POST",))
#: GET shows a page, POST changes (the Item editor).
editor_page = _guarded(("GET", "POST"))
#: GET only (Trash and History screens).
editor_get = _guarded(("GET",))


def _kind(request):
    kind = request.POST.get("kind", "")
    if kind not in EDIT_KINDS:
        raise Http404("Unknown record type.")
    return kind


def _record_id(request, name="id"):
    value = request.POST.get(name, "")
    if not value.isdigit():
        raise Http404("That record does not exist.")
    return int(value)


def _version(request):
    value = request.POST.get("version", "")
    return int(value) if value.isdigit() else None


def _index(request):
    value = request.POST.get("index", "")
    return int(value) if value.isdigit() else None


def _parent(request, name="parent"):
    """('topic', 5) from 'topic:5', or None when the field is empty."""
    value = request.POST.get(name, "")
    if not value:
        return None
    kind, _, pk = value.partition(":")
    if kind not in EDIT_KINDS or not pk.isdigit():
        raise Http404("Unknown place.")
    return kind, int(pk)


def _html(text):
    """Plain typed text as paragraphs (the service sanitises it again)."""
    return "".join(f"<p>{escape(line.strip())}</p>" for line in text.splitlines() if line.strip())


def _single_line(value):
    return " ".join(value.split())


@edit_endpoint
def add(request):
    """Add a Subject, heading, Section, Item or Nested Item at the end of its parent."""
    post = request.POST
    what = post.get("what", "")
    if what not in ADDABLE:
        messages.error(request, "Choose what to add.")
        return redirect(_next(request))
    kind, extra = ADDABLE[what]
    parent = None
    if post.get("parent_type"):
        parent = (post.get("parent_type"), _record_id(request, "parent_id"))
    name = _single_line(post.get("name", ""))
    fields = dict(extra)
    if kind in ("subject", "topic", "subtopic", "section"):
        fields["name"] = name
    if kind == "subject":
        fields["show_on_landing"] = post.get("landing", "1") == "1"
    if kind == "item":
        text = _html(post.get("text", ""))
        citation = _single_line(post.get("citation", ""))
        if not text and not citation:
            messages.error(request, "Type the Item text (or a citation) first.")
            return redirect(_next(request))
        fields.update(text=text, citation=citation)
    svc.create(request.profile, request.user, kind, parent=parent, index=_index(request), **fields)
    messages.success(request, f"Added the {ADD_NICE.get(what, NICE[kind])}.")
    return redirect(_next(request))


@edit_endpoint
def rename(request):
    kind = _kind(request)
    if kind not in RENAMEABLE:
        messages.error(request, "Items are changed in the Item editor, not renamed here.")
        return redirect(_next(request))
    name = _single_line(request.POST.get("name", ""))
    result = svc.edit(request.profile, request.user, kind, _record_id(request), {"name": name}, _version(request))
    messages.success(request, "Renamed." if result.changed else "The name was already that.")
    return redirect(_next(request))


def _fields(request, **extra):
    """The hidden fields that are sent back with a confirmation form."""
    post = request.POST
    fields = {"kind": post.get("kind", ""), "id": post.get("id", ""), "version": post.get("version", ""),
              "next": _next(request)}
    fields.update(extra)
    return fields


def _changes_page(request, title, action, fields, preview, lead, confirm_label, danger=False):
    return render(
        request,
        "diary/edit_confirm.html",
        {"title": title, "action": action, "fields": sorted(fields.items()), "changes": preview["changes"],
         "count": preview.get("count"), "lead": lead, "confirm_label": confirm_label, "danger": danger,
         "next_url": _next(request)},
    )


@edit_endpoint
def delete(request):
    """Move to Trash. The first POST shows what will happen; the second (confirmed=1) does it."""
    kind, record_id = _kind(request), _record_id(request)
    if not request.POST.get("confirmed"):
        preview = svc.preview_delete(request.profile, request.user, kind, record_id)
        obj = get_record(Ctx(request.profile, request.user), kind, record_id, lock=False)
        lead = f"Move the {NICE[kind]} \u201c{label(obj)}\u201d to the Trash?"
        if preview["count"] > 1:
            lead += f" It and {preview['count'] - 1} record{'s' if preview['count'] > 2 else ''} below it go together."
        return _changes_page(request, "Delete", reverse("edit_delete"), _fields(request, confirmed="1"), preview,
                             lead, "Move to Trash", danger=True)
    result = svc.delete(request.profile, request.user, kind, record_id, _version(request))
    if not result.changed:
        messages.info(request, "That was already in the Trash.")
    else:
        messages.success(request, f"Moved {result.info.get('count', 1)} record(s) to the Trash.")
    if kind in ("subject", "topic", "subtopic"):
        return redirect(reverse("subjects") if kind == "subject" else _next_after_heading(request, kind, record_id))
    return redirect(_next(request))


def _next_after_heading(request, kind, record_id):
    """A deleted Topic or Sub-topic has no page any more, so go to the whole Subject it was in."""
    if kind == "topic":
        subject_id = Topic._base_manager.get(pk=record_id, profile=request.profile).subject_id
    else:
        row = Subtopic._base_manager.select_related("topic").get(pk=record_id, profile=request.profile)
        subject_id = row.subject_id or row.topic.subject_id
    keep = "?edit=1" if "edit=1" in _next(request) else ""
    return f"{reverse('read_subject', args=[subject_id])}{keep}"


@edit_endpoint
def move(request):
    """Up/down (``direction``), or to a place (``parent`` 'type:id', and/or ``index``).

    A move to a place shows the renumbering first; the same POST with confirmed=1 does it. Drag and
    drop sends confirmed=1 because the dropped position is already what the Editor chose.
    """
    kind, record_id, version = _kind(request), _record_id(request), _version(request)
    direction = request.POST.get("direction", "")
    if direction in ("up", "down"):
        result = svc.shift(request.profile, request.user, kind, record_id, -1 if direction == "up" else 1, version)
        messages.success(request, "Moved." if result.changed else "It is already at the end of the list.")
        return redirect(_next(request))
    parent, index = _parent(request), _index(request)
    if not request.POST.get("confirmed"):
        preview = svc.preview_move(request.profile, request.user, kind, record_id, parent, index)
        obj = get_record(Ctx(request.profile, request.user), kind, record_id, lock=False)
        extra = {"confirmed": "1", "parent": request.POST.get("parent", ""), "index": request.POST.get("index", "")}
        lead = f"Move the {NICE[kind]} \u201c{label(obj)}\u201d here?"
        if not preview["changes"]:
            lead += " No numbers change."
        return _changes_page(request, "Move", reverse("edit_move"), _fields(request, **extra), preview, lead, "Move")
    result = svc.move(request.profile, request.user, kind, record_id, parent, index, version)
    messages.success(request, "Moved." if result.changed else "It is already there.")
    return redirect(_next(request))


@edit_endpoint
def landing(request):
    """Move a Subject between the landing page list and Other Subjects."""
    show = request.POST.get("show", "1") == "1"
    result = svc.set_landing(request.profile, request.user, _record_id(request), show, _version(request))
    if not result.changed:
        messages.info(request, "No change.")
    else:
        messages.success(request, "The Subject is now on the landing page." if show else "The Subject is now under Other Subjects.")
    return redirect(_next(request))


def picker_entries(profile, kind, obj):
    """The tree of every Subject, Topic, Sub-topic and Nested Item of the profile, flat, with depth.

    ``pick`` says whether ``obj`` may be moved under that entry (right type, not inside itself).
    """
    allowed = set(ALLOWED_PARENTS[kind])
    if kind == "item" and obj.kind != "plain":
        allowed.discard("item")
    banned = {ident(d) for d in descendants(obj)} | {(kind, obj.pk)}
    live = {"profile": profile, "deleted_at__isnull": True}
    subjects = list(Subject.objects.filter(show_on_landing=True, **live).order_by("landing_position", "name", "pk"))
    subjects += list(Subject.objects.filter(show_on_landing=False, **live).order_by("other_acts_position", "name", "pk"))
    topics, subs, nested = {}, {}, {}
    for topic in Topic.objects.filter(**live).order_by("position", "pk"):
        topics.setdefault(topic.subject_id, []).append(topic)
    for sub in Subtopic.objects.filter(**live).order_by("position", "pk"):
        subs.setdefault(("topic", sub.topic_id) if sub.topic_id else ("subject", sub.subject_id), []).append(sub)
    for item in Item.objects.filter(kind="nested", parent_item__isnull=True, **live).order_by("position", "pk"):
        for column in ("subject", "topic", "subtopic"):
            if getattr(item, f"{column}_id"):
                nested.setdefault((column, getattr(item, f"{column}_id")), []).append(item)
    entries = []

    def add(rec, depth, kind_name):
        entries.append({
            "type": kind_name, "id": rec.pk, "label": label(rec), "kind_name": NICE[kind_name], "depth": depth,
            "pick": kind_name in allowed and (kind_name, rec.pk) not in banned,
        })

    def add_nested(column, pk, depth):
        for item in nested.get((column, pk), []):
            add(item, depth, "item")

    for subject in subjects:
        add(subject, 0, "subject")
        add_nested("subject", subject.pk, 1)
        for topic in topics.get(subject.pk, []):
            add(topic, 1, "topic")
            add_nested("topic", topic.pk, 2)
            for sub in subs.get(("topic", topic.pk), []):
                add(sub, 2, "subtopic")
                add_nested("subtopic", sub.pk, 3)
        for sub in subs.get(("subject", subject.pk), []):
            add(sub, 1, "subtopic")
            add_nested("subtopic", sub.pk, 2)
    return entries


@edit_endpoint
def move_to(request):
    """The tree picker: choose the new place for a heading, Section or Item."""
    kind, record_id = _kind(request), _record_id(request)
    if kind not in ALLOWED_PARENTS:
        messages.error(request, f"A {NICE[kind]} cannot be moved.")
        return redirect(_next(request))
    obj = get_record(Ctx(request.profile, request.user), kind, record_id, lock=False)
    return render(
        request,
        "diary/edit_move_to.html",
        {"entries": picker_entries(request.profile, kind, obj), "fields": sorted(_fields(request).items()),
         "kind_name": NICE[kind], "record_label": label(obj), "next_url": _next(request)},
    )
