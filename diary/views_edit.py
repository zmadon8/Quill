"""Edit mode endpoints for headings and Items (Milestone 3b, docs/DESIGN.md decision M3-13).

Every endpoint is POST only, needs the CSRF token, and is for Editors of the signed-in user's
profile (Readers get 403; another profile's ids give 404). The views only read the form, call the
service layer in diary/services and send the browser back with a message. Nothing is changed
without going through the services, which do the renumbering, history and rules.
"""
from functools import wraps
from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.html import escape, strip_tags
from django.utils.http import url_has_allowed_host_and_scheme

from . import inline
from . import services as svc
from . import undo_session
from .conflicts import conflict_page
from .models import FLAG_CHOICES, Section, Subject, Subtopic, Topic
from .richtext import plain_text, sanitise_html
from .services.core import Ctx, ancestors, check_version, descendants, get_record, label
from .services.errors import Conflict, NotFound, ServiceError, ValidationFailed
from .services.moves import ALLOWED_PARENTS, NICE
from .services.sequences import COLUMN_TYPE, ident, members, sequence_key
from .sorting import sort_headings
from .views import profile_required, user_can_edit

EDIT_KINDS = ("subject", "topic", "subtopic", "section", "item", "note")
RENAMEABLE = ("subject", "topic", "subtopic", "section")

#: What the Add form can create: choice -> (record type, extra fields).
ADDABLE = {
    "subject": ("subject", {}),
    "topic": ("topic", {}),
    "subtopic": ("subtopic", {}),
    "section": ("section", {}),
    "item": ("item", {}),
    "note": ("note", {}),
}
ADD_NICE = {}
#: Longest flag text an Item takes (the Item editor and the Add forms).
FLAG_TEXT_MAX = 300
#: Longest name the Add form accepts for each kind that has a name (the model field lengths).
HEADING_LIMITS = {
    "subject": Subject._meta.get_field("name").max_length,
    "topic": Topic._meta.get_field("name").max_length,
    "subtopic": Subtopic._meta.get_field("name").max_length,
    "section": Section._meta.get_field("name").max_length,
}


def _next(request, default=None):
    """Where to go back to: the ``next`` address from the form (or the address) if it is on this site, else ``default`` or the Subjects page."""
    target = request.POST.get("next", "") or request.GET.get("next", "")
    if (
        target.startswith("/")
        and not target.startswith("//")
        and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure())
    ):
        return target
    return default or reverse("diary_home")


def _conflict(request, exc):
    return conflict_page(request, exc, _next(request))


def is_fetch(request):
    """True for a request made by the Edit mode script, which wants JSON back instead of a page."""
    return request.headers.get("X-Requested-With") == "fetch"


def _json_error(message, status=400, **extra):
    return JsonResponse({"ok": False, "errors": [message], **extra}, status=status)


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
                request.undo_group = group
                try:
                    response = view(request, *args, **kwargs)
                except NotFound as exc:
                    raise Http404(exc.message)
                except Conflict as exc:
                    if is_fetch(request):
                        # ``conflict_url``: send the same form again to it without the fetch header and the existing
                        # conflict screen (keep mine / keep theirs / edit and merge) is the answer.
                        response = _json_error("Someone else changed this just now.", 409, conflict=True,
                                               conflict_url=request.path)
                    else:
                        response = _conflict(request, exc)
                except ServiceError as exc:
                    if is_fetch(request):
                        response = _json_error(exc.message or "That could not be done.")
                    else:
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


#: Records an entry can be added after (they share a position sequence with what is added).
AFTER_KINDS = ("topic", "subtopic", "section", "item")
#: What the Add page offers when adding after a record: the kinds that can sit beside it.
AFTER_CHOICES = {
    "topic": ("topic",),
    "subtopic": ("subtopic",),
    "section": ("item", "section"),
    "item": ("item", "section"),
}


def _after(source, name="after", kinds=AFTER_KINDS):
    """('item', 5) from 'item:5' in ``source`` (the form or the address), or None when there is none."""
    value = source.get(name, "")
    if not value:
        return None
    kind, _, pk = value.partition(":")
    if kind not in kinds or not pk.isdigit():
        raise Http404("Unknown place.")
    return kind, int(pk)


def _place_after(request, after, expected=None):
    """(record, parent, index) for a new entry placed directly after ``after``.

    The parent is the record's own parent and the index counts the live siblings up to and
    including it, so everything later is shifted down by the create service (the same numbering,
    History and Undo as any other add). ``expected`` is the version of the record the Editor saw.
    """
    record = get_record(Ctx(request.profile, request.user), after[0], after[1], lock=False)
    check_version(record, expected)
    key = sequence_key(record)
    if key is None:
        raise Http404("Unknown place.")
    parent = (COLUMN_TYPE[key[1]], key[2])
    siblings = [ident(m) for m in members(request.profile.pk, key)]
    if ident(record) not in siblings:
        raise Http404("That record is not in the list any more.")
    return record, parent, siblings.index(ident(record)) + 1


def _choice(request):
    """The inline form's choice: {'what', 'after', 'parent'} from ``ref`` ('item:5') and ``choice`` ('after:nested'), or None.

    The choice must be one the row offers (``inline.add_choices``), so the server, not the browser, decides what can be
    added where. ``inside`` choices go first inside the row; ``after`` choices go directly after it.
    """
    value = request.POST.get("choice", "")
    if not value:
        return None
    ref = _after(request.POST, "ref", kinds=EDIT_KINDS)
    if ref is None:
        raise Http404("Unknown place.")
    record = get_record(Ctx(request.profile, request.user), ref[0], ref[1], lock=False)
    if value not in dict(inline.add_choices(request.profile, ref[0], record)):
        raise ServiceError("That cannot be added in that place.")
    mode, _, what = value.partition(":")
    return {"what": what, "after": ref if mode == "after" else None, "parent": ref if mode == "inside" else None}


def _expected(request, name):
    value = request.POST.get(name, "")
    return int(value) if value.isdigit() else None


def _add_page(request):
    """The normal Add page: the same form as Edit mode, with the place chosen from the address.

    ``?after=item:5`` or ``?parent=topic:3`` names the row the "+ Add" button belonged to. The page offers exactly the
    types the inline form offers on that row (``inline.add_choices``, the one shared list) and posts ``ref`` and
    ``choice`` like it. It needs no JavaScript and is what a phone gets.
    """
    value = request.GET.get("after", "") or request.GET.get("parent", "")
    kind, _, pk = value.partition(":")
    if kind not in EDIT_KINDS or not pk.isdigit():
        raise Http404("Unknown place.")
    record = get_record(Ctx(request.profile, request.user), kind, int(pk), lock=False)
    choices = inline.add_choices(request.profile, kind, record)
    if not choices:
        raise Http404("Nothing can be added there.")
    options = [{"value": c, "label": text} for c, text in choices]
    after = bool(request.GET.get("after")) and not request.GET.get("parent")
    where = f"{'after' if after else 'inside'} the {NICE[kind]} \u201c{label(record)}\u201d"
    return render(request, "diary/add_page.html", {
        "options": options, "where": where, "ref": f"{kind}:{record.pk}", "ref_version": record.version,
        "next_url": _next(request), "flag_choices": FLAG_CHOICES, "values": {"flag": "none"},
        "default": choices[0][0],
    })


def _marking(post, kind):
    """The Flag and For review fields of a new Item (all of them) or Section (For review only), as the create service takes them.

    Validation is the Item editor's: a flag must be one of the choices, its text at most FLAG_TEXT_MAX characters.
    Other kinds get nothing, whatever was posted.
    """
    if kind not in ("item", "section"):
        return {}
    marked = post.get("needs_review") == "1"
    fields = {"needs_review": marked, "review_note": post.get("review_note", "").strip() if marked else ""}
    if kind == "item":
        flag = post.get("flag", "none")
        if flag not in {c[0] for c in FLAG_CHOICES}:
            raise ValidationFailed(f"{flag!r} is not a flag choice.")
        flag_text = "" if flag == "none" else _single_line(post.get("flag_text", ""))
        if len(flag_text) > FLAG_TEXT_MAX:
            raise ValidationFailed(f"The flag text is too long ({FLAG_TEXT_MAX} characters at most).")
        fields.update(flag=flag, flag_text=flag_text)
    return fields


@editor_page
def add(request):
    """Add a Subject, heading, Section or Item.

    It goes at the end of its parent, or directly after the record named by ``after`` ('item:5';
    ``after_version`` is the version of that record the Editor saw). The Edit mode script sends
    ``first=1`` with a parent to put the new entry first inside it, so it appears right below the
    heading it was added from. A request with the header X-Requested-With: fetch gets JSON back
    (``ok``, and the new ``kind``, ``id``, ``version`` or the ``errors``) instead of a redirect.
    """
    if request.method == "GET":
        return _add_page(request)
    post = request.POST
    choice = _choice(request)
    what = choice["what"] if choice else post.get("what", "")
    if what not in ADDABLE:
        raise ServiceError("Choose what to add.")
    kind, extra = ADDABLE[what]
    parent, index = None, None
    after = choice["after"] if choice else _after(post)
    if choice and choice["parent"]:
        # A Note goes after the Items and Sections of its parent (the service keeps that order), so it is added last.
        parent, index = choice["parent"], (None if kind == "note" else 0)
    elif after:
        allowed = AFTER_CHOICES[after[0]]
        if what not in allowed:
            raise ServiceError("That cannot be added in that place.")
        _, parent, index = _place_after(request, after, _expected(request, "after_version"))
    elif not choice:
        if post.get("parent_type"):
            parent = (post.get("parent_type"), _record_id(request, "parent_id"))
        if parent and post.get("first") == "1" and kind != "note":
            index = 0
    # One "Text" box: the name of a heading or Section, the text of an Item.
    # (An older form that posts "name" for a heading still works.)
    typed = post.get("text", "") if "text" in post else post.get("name", "")
    fields = dict(extra)
    if kind in HEADING_LIMITS:
        name = _single_line(strip_tags(typed))
        if not name:
            raise ServiceError(f"Type the {NICE[kind]} name first.")
        if len(name) > HEADING_LIMITS[kind]:
            raise ServiceError(f"The {NICE[kind]} name is too long (at most {HEADING_LIMITS[kind]} characters).")
        fields["name"] = name
    fields.update(_marking(post, kind))
    if kind == "subject":
        fields["show_on_landing"] = post.get("landing", "1") == "1"
    cases = []
    if kind == "note":
        text = sanitise_html(typed) if post.get("text_format") == "html" else _html(typed)
        if not plain_text(text).strip():
            raise ServiceError("Type the Note text first. Links are added when you edit the Note.")
        fields["text"] = text
    if kind == "item":
        # The script sends cleaned HTML (text_format=html); without it the box is plain typed text.
        text = sanitise_html(typed) if post.get("text_format") == "html" else _html(typed)
        # A citation belongs to Items only; it is ignored for anything else.
        citation = _single_line(post.get("citation", ""))
        # The inline form can send several citations (case_citation / case_comment, in order); they become the Cases of the new Item.
        cases = _new_cases(post)
        if cases:
            citation = ""
        if not plain_text(text).strip() and not citation and not cases:
            raise ServiceError("Type the Item text (or a citation) first.")
        fields.update(text=text, citation=citation)
    # The Item and its Cases are one change: if a Case is refused, no half-made Item is left behind.
    with transaction.atomic():
        result = svc.create(request.profile, request.user, kind, parent=parent, index=index if index is not None else _index(request), **fields)
        for number, case in enumerate(cases):
            svc.create(request.profile, request.user, "case", parent=("item", result.record.pk), index=number, **case)
    if is_fetch(request):
        record = result.record
        # An Item or Section added under a Subject is housed in its Topic "1" (D61), which may be new: the page reloads.
        housed = kind in ("item", "section") and parent is not None and parent[0] == "subject" and bool(record.topic_id)
        payload = (inline.row_payload(request, kind, record.pk, _next(request))
                   if kind in ("item", "section") and not housed else {"reload": True})
        return inline.ok(request, kind=kind, id=record.pk, version=record.version, after=f"{kind}:{record.pk}", **payload)
    if kind == "note":
        messages.success(request, "Added the Note. Add its links below, or press Back to reading.")
        return redirect(f"{reverse('edit_note', args=[result.record.pk])}?{urlencode({'next': _next(request)})}")
    messages.success(request, f"Added the {ADD_NICE.get(what, NICE[kind])}.")
    return redirect(_next(request))


def _new_cases(post):
    """[{'citation', 'comment'}] from the parallel lists case_citation / case_comment; rows with neither are dropped."""
    comments = post.getlist("case_comment")
    rows = []
    for number, citation in enumerate(post.getlist("case_citation")):
        citation = _single_line(citation)
        comment = comments[number] if number < len(comments) else ""
        if citation or comment.strip():
            rows.append({"citation": citation, "comment": comment})
    return rows


@edit_endpoint
def rename(request):
    kind = _kind(request)
    if kind not in RENAMEABLE:
        messages.error(request, "Items are changed in the Item editor, not renamed here.")
        return redirect(_next(request))
    name = _single_line(request.POST.get("name", ""))
    changes = {"name": name}
    if kind == "section" and request.POST.get("review_form") == "1":
        # The Section card has the For review switch and note next to the name: one save, one Undo step.
        marked = request.POST.get("needs_review") == "1"
        changes.update(needs_review=marked, review_note=request.POST.get("review_note", "").strip() if marked else "")
    result = svc.edit(request.profile, request.user, kind, _record_id(request), changes, _version(request))
    if is_fetch(request):
        # A new name can change the alphabetical place and the Contents panel, so the script reloads the page.
        if kind == "section":
            return inline.ok(request, changed=result.changed, **inline.row_payload(request, kind, result.record.pk, _next(request)))
        return inline.ok(request, changed=result.changed, reload=True)
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
    if is_fetch(request):
        # The inline Edit card says "goes to Trash, Undo available", so there is no second step: the answer carries the
        # Undo step. Items and Sections are removed from the page by the script (``element``) and the numbers refreshed.
        result = svc.delete(request.profile, request.user, kind, record_id, _version(request))
        payload = {"deleted": result.changed, "count": result.info.get("count", 1)}
        if kind in ("item", "section"):
            payload["element"] = f"row-n-section-{record_id}" if kind == "section" else f"n-item-{record_id}"
            payload.update(inline.labels_payload(request, kind, record_id))
        else:
            payload["reload"] = True
        return inline.ok(request, **payload)
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
        return redirect(reverse("diary_home") if kind == "subject" else _next_after_heading(request, kind, record_id))
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
        if is_fetch(request):
            return inline.ok(request, changed=result.changed, reload=True)
        messages.success(request, "Moved." if result.changed else "It is already at the end of the list.")
        return redirect(_next(request))
    parent, index = _parent(request), _index(request)
    if not request.POST.get("confirmed") and not is_fetch(request):
        preview = svc.preview_move(request.profile, request.user, kind, record_id, parent, index)
        obj = get_record(Ctx(request.profile, request.user), kind, record_id, lock=False)
        extra = {"confirmed": "1", "parent": request.POST.get("parent", ""), "index": request.POST.get("index", "")}
        lead = f"Move the {NICE[kind]} \u201c{label(obj)}\u201d here?"
        if not preview["changes"]:
            lead += " No numbers change."
        return _changes_page(request, "Move", reverse("edit_move"), _fields(request, **extra), preview, lead, "Move")
    result = svc.move(request.profile, request.user, kind, record_id, parent, index, version)
    if is_fetch(request):
        return inline.ok(request, changed=result.changed, reload=True)
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
    """The tree of every Subject, Topic and Sub-topic of the profile, flat, with depth.

    ``pick`` says whether ``obj`` may be moved under that entry (right type, not inside itself).
    """
    allowed = set(ALLOWED_PARENTS[kind])
    banned = {ident(d) for d in descendants(obj)} | {(kind, obj.pk)}
    live = {"profile": profile, "deleted_at__isnull": True}
    # Headings are listed alphabetically (diary/sorting.py), main Subjects first, then Other Subjects.
    subjects = sort_headings(Subject.objects.filter(show_on_landing=True, **live))
    subjects += sort_headings(Subject.objects.filter(show_on_landing=False, **live))
    topics, subs = {}, {}
    for topic in sort_headings(Topic.objects.filter(**live)):
        topics.setdefault(topic.subject_id, []).append(topic)
    for sub in sort_headings(Subtopic.objects.filter(**live)):
        subs.setdefault(("topic", sub.topic_id) if sub.topic_id else ("subject", sub.subject_id), []).append(sub)
    entries = []

    def add(rec, depth, kind_name):
        entries.append({
            "type": kind_name, "id": rec.pk, "label": label(rec), "kind_name": NICE[kind_name], "depth": depth,
            "pick": kind_name in allowed and (kind_name, rec.pk) not in banned,
        })

    for subject in subjects:
        add(subject, 0, "subject")
        for topic in topics.get(subject.pk, []):
            add(topic, 1, "topic")
            for sub in subs.get(("topic", topic.pk), []):
                add(sub, 2, "subtopic")
        for sub in subs.get(("subject", subject.pk), []):
            add(sub, 1, "subtopic")
    return entries


def picker_tree(entries, current=None):
    """The flat ``picker_entries`` as a nested list for the collapsible Move to tree.

    Each node is the entry plus ``children`` (the entries one level down, in order), ``open_id`` (an id for the
    sub-list, set only when there are children) and ``current`` (True for the Subject the record sits in now,
    given as ``current`` = ('subject', pk)).
    """
    roots, stack = [], []
    for entry in entries:
        node = {**entry, "children": [], "open_id": "", "current": (entry["type"], entry["id"]) == current}
        del stack[entry["depth"]:]
        (stack[-1]["children"] if stack else roots).append(node)
        stack.append(node)

    def name(nodes):
        for node in nodes:
            if node["children"]:
                node["open_id"] = f"picker-sub-{node['type']}-{node['id']}"
            name(node["children"])
    name(roots)
    return roots


@edit_endpoint
def move_to(request):
    """The tree picker: choose the new place for a heading, Section or Item."""
    kind, record_id = _kind(request), _record_id(request)
    if kind not in ALLOWED_PARENTS:
        messages.error(request, f"A {NICE[kind]} cannot be moved.")
        return redirect(_next(request))
    obj = get_record(Ctx(request.profile, request.user), kind, record_id, lock=False)
    if kind == "note":
        return redirect(f"{reverse('edit_note_pick')}?{urlencode({'purpose': 'move', 'note': obj.pk, 'next': _next(request)})}")
    chain = ancestors(obj)
    current = ("subject", chain[0][1].pk) if chain and chain[0][0] == "subject" else None
    entries = picker_entries(request.profile, kind, obj)
    return render(
        request,
        "diary/edit_move_to.html",
        {"entries": entries, "tree": picker_tree(entries, current), "new_options": svc.new_heading_options(request.profile, request.user, obj),
         "fields": sorted(_fields(request).items()),
         "kind_name": NICE[kind], "record_label": label(obj), "next_url": _next(request)},
    )


@edit_endpoint
def move_new(request):
    """Move to a NEW Topic (in the record's Subject) or Sub-topic (in its Topic), from the top of the Move to picker.

    Three steps on one address: ask for the name, show the numbers that change (preview), then do it. The new heading
    and the move are one Undo step. Name problems (empty, already used among its siblings) show the name form again.
    """
    kind, record_id = _kind(request), _record_id(request)
    new_kind = request.POST.get("new_heading", "")
    if new_kind not in ("topic", "subtopic"):
        raise Http404("Unknown heading type.")
    name = request.POST.get("name", "")
    obj = get_record(Ctx(request.profile, request.user), kind, record_id, lock=False)
    options = {o["kind"]: o for o in svc.new_heading_options(request.profile, request.user, obj)}
    if new_kind not in options:
        messages.error(request, f"A new {NICE[new_kind]} cannot be made for this {NICE[kind]}.")
        return redirect(_next(request))
    where = options[new_kind]
    base_fields = _fields(request, new_heading=new_kind)

    def ask(error=""):
        return render(request, "diary/edit_move_new.html", {
            "fields": sorted(base_fields.items()), "kind_name": NICE[kind], "record_label": label(obj),
            "new_name": NICE[new_kind], "parent_name": where["parent"].name, "parent_kind": NICE[where["parent_kind"]],
            "name": name, "error": error, "next_url": _next(request),
            "max_length": HEADING_LIMITS[new_kind],
        })

    if not request.POST.get("name_given"):
        return ask()
    try:
        if not request.POST.get("confirmed"):
            preview = svc.preview_move_to_new_heading(request.profile, request.user, kind, record_id, new_kind, name)
            lead = (f"Make the new {NICE[new_kind]} \u201c{preview['heading']}\u201d in {where['parent'].name} and move the "
                    f"{NICE[kind]} \u201c{label(obj)}\u201d into it?")
            if not preview["changes"]:
                lead += " No numbers change."
            fields = _fields(request, new_heading=new_kind, name_given="1", name=preview["heading"], confirmed="1")
            return _changes_page(request, "Move to a new " + NICE[new_kind], reverse("edit_move_new"), fields, preview, lead, "Make it and move")
        svc.move_to_new_heading(request.profile, request.user, kind, record_id, new_kind, name, _version(request))
    except svc.ValidationFailed as exc:
        return ask(exc.message)
    messages.success(request, f"Moved into the new {NICE[new_kind]}.")
    return redirect(_next(request))
