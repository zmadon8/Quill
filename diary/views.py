import copy
import logging
from functools import wraps
from urllib.parse import urlencode, urlsplit

from django.core.exceptions import PermissionDenied
from django.db import connection
from django.db.models import Count, Q
from django.db.models.functions import Coalesce
from django.http import Http404, HttpResponse
from django.utils import timezone
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from accounts import landing as account_landing
from accounts.models import ROLE_EDITOR
from accounts.models import Profile
from accounts.permissions import admin_required, reader_required
from accounts.profiles import export_file_name, request_profile, request_role
from accounts.suite import KEY_DIARY

from . import reading, undo_session
from .opening import remember_page
from .params import safe_int
from . import search as search_module
from .forms import ProfileSettingsForm
from .importer import loader as import_loader
from .importer import service as import_service
from .models import Item, Subject, Subtopic, Topic
from .sorting import sort_headings

NO_PROFILE_MESSAGE = "No profile assigned - ask the Admin"


def profile_required(view):
    """Signed-in users only, and only those with a Case Law Diary profile.

    A user with no profile gets a 403 page saying so (decision P6: a clear page, not a redirect).
    The profile is passed to the view as ``request.profile``; every query must use it.
    """

    @reader_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        profile = request_profile(request)
        if profile is None:
            return render(request, "diary/no_profile.html", {"message": NO_PROFILE_MESSAGE}, status=403)
        request.profile = profile
        return view(request, *args, **kwargs)

    return wrapper


def user_can_edit(request):
    """Only Editors of the profile may edit; Admins follow the role of their own membership."""
    return request_role(request, request.profile.program) == ROLE_EDITOR


def edit_context(request):
    """Template variables for Edit mode. Edit mode is on only for Editors, with ?edit=1 in the address.

    ``next_url`` is where an edit sends the browser back to; ``toggle_url`` flips Edit mode.
    """
    can_edit = user_can_edit(request)
    edit_mode = can_edit and request.GET.get("edit") == "1"
    return {
        "undo": undo_session.latest(request) if edit_mode else None,
        "can_edit": can_edit,
        "edit_mode": edit_mode,
        "edit_qs": "?edit=1" if edit_mode else "",
        "next_url": request.get_full_path(),
        "toggle_url": request.path if edit_mode else f"{request.path}?edit=1",
    }


def _subjects(profile, **filters):
    return Subject.objects.filter(profile=profile, deleted_at__isnull=True, **filters)


def _sorted_subjects(profile, **filters):
    """Live Subjects in alphabetical order (diary/sorting.py); the stored positions are the kept Word order."""
    return sort_headings(_subjects(profile, **filters))


def opening_subject_for(user, profile):
    """The user's chosen opening Subject, only if it is live and in ``profile`` (else None)."""
    settings = getattr(user, "diary_settings", None)
    subject = settings.opening_subject if settings else None
    if subject is None or subject.profile_id != profile.pk or subject.deleted_at is not None:
        return None
    return subject


def item_counts_by_subject(profile):
    """One aggregate query: {subject_id: (items, items_for_review)} for live Items at any depth.

    An Item belongs to a Subject through its Topic, Sub-topic or Nested-Item parent, so the owning
    Subject is the first non-null of those paths (a Nested Item's children go one level further).
    Items whose own Topic, Sub-topic or Nested-Item parent is deleted are not counted.
    """
    owner = Coalesce(
        "subject_id",
        "topic__subject_id",
        "subtopic__subject_id",
        "subtopic__topic__subject_id",
        "parent_item__subject_id",
        "parent_item__topic__subject_id",
        "parent_item__subtopic__subject_id",
        "parent_item__subtopic__topic__subject_id",
    )
    rows = (
        Item.objects.filter(profile=profile, deleted_at__isnull=True)
        .exclude(
            Q(topic__deleted_at__isnull=False)
            | Q(subtopic__deleted_at__isnull=False)
            | Q(subtopic__topic__deleted_at__isnull=False)
            | Q(parent_item__deleted_at__isnull=False)
        )
        .annotate(owner=owner)
        .values("owner")
        .annotate(items=Count("pk"), review=Count("pk", filter=Q(needs_review=True)))
        .order_by()
    )
    return {r["owner"]: (r["items"], r["review"]) for r in rows}


@profile_required
@remember_page
def subjects(request):
    """Index: Subjects on the landing page with item counts, then the Other Subjects below a divider."""
    profile = request.profile
    counts = item_counts_by_subject(profile)
    landing = list(_sorted_subjects(profile, show_on_landing=True))
    for subject in landing:
        subject.item_count = counts.get(subject.pk, (0, 0))[0]
    other = list(_sorted_subjects(profile, show_on_landing=False))
    for subject in other:
        subject.item_count = counts.get(subject.pk, (0, 0))[0]
    live_ids = set(_subjects(profile).values_list("pk", flat=True))
    total_items = sum(n for pk, (n, _) in counts.items() if pk in live_ids)
    total_review = sum(r for pk, (_, r) in counts.items() if pk in live_ids)
    return render(request, "diary/subjects.html", {
        **edit_context(request),
        "subjects": landing,
        "other_subjects": other,
        "subject_total": len(live_ids),
        "item_total": total_items,
        "review_total": total_review,
    })


def _referred_from_this_site(request):
    """True when the request came from a page of this site (same host in the Referer header)."""
    referer = request.META.get("HTTP_REFERER", "")
    return bool(referer) and urlsplit(referer).netloc == request.get_host()


@reader_required
def home(request):
    """Suite Home: the program picker (only the case law diary today).

    An entry visit (bare ``/`` with no same-origin Referer and no ``?home=1``) by a user who chose a landing
    program in My settings, and still has a profile there, goes straight to that program. Every deliberate
    Home link (icon, Alt+H, brand, Cancel, Back fallback) carries ``?home=1``, and in-site navigation sends a
    same-origin Referer, so Home itself stays reachable. See docs/DESIGN.md.
    """
    if request.method == "GET" and not request.GET.get("home") and not _referred_from_this_site(request):
        target = account_landing.landing_url(request.user)
        if target != reverse("home"):
            return redirect(target)
    return render(request, "diary/home.html", {"diary_profile": request_profile(request)})


@profile_required
def profile_settings(request):
    """Settings of the user's profile. Editors can change the Display Name, the export name and the "All" default; Readers only view them."""
    profile = request.profile
    can_edit = user_can_edit(request)
    form = ProfileSettingsForm(request.POST or None, instance=copy.copy(profile))  # a copy: an invalid POST must not change the header
    if request.method == "POST":
        if not can_edit:
            raise PermissionDenied
        if form.is_valid():
            form.save()
            messages.success(request, "Profile settings saved.")
            return redirect("profile_settings")
    return render(
        request,
        "diary/profile_settings.html",
        {"form": form, "can_edit": can_edit, "preview": export_file_name(form.instance)},
    )


@profile_required
def other_subjects(request):
    """Other Subjects now sit on the Subjects page; the old address redirects there (keeping Edit mode)."""
    keep = "?edit=1" if edit_context(request)["edit_mode"] else ""
    return redirect(f"{reverse('diary_home')}{keep}#other-subjects")


def _panel_subjects(profile):
    """Every live Subject of the profile for the Subjects view of the Contents panel: main first, then Other, in order."""
    return {
        "panel_main": list(_sorted_subjects(profile, show_on_landing=True)),
        "panel_other": list(_sorted_subjects(profile, show_on_landing=False)),
    }


IN_CONTEXT_COOKIE = "quill_in_context"


def _in_context(request, scope=None):
    """Whether the side-panel Contents links open the whole Subject (at the heading) or just that Topic or Sub-topic.

    The profile's ``reading_all_mode`` decides: always the whole Subject, always only that Topic or Sub-topic, or,
    in "remember" mode, the view this browser used last (cookie ``quill_in_context``, written by site.js when a
    reading page loads: "0" is a single Topic or Sub-topic, anything else the whole Subject). With no cookie yet
    the profile's ``reading_all_default`` decides. Clicking a Topic or Sub-topic heading in the reading body
    never depends on this: that link always carries its own target.

    A reading page passes its ``scope``: in "remember" mode the page being shown is itself the view in use, so
    the cookie (which site.js writes only after the page has rendered) is ignored and ``scope == "subject"``
    decides. The cookie only matters for pages with no scope (the Subject contents page)."""
    mode = request.profile.reading_all_mode
    if mode != Profile.READING_ALL_REMEMBER:
        return mode == Profile.READING_ALL_ALWAYS_ON
    if scope is not None:
        return scope == "subject"
    cookie = request.COOKIES.get(IN_CONTEXT_COOKIE)
    if cookie is None:
        return bool(request.profile.reading_all_default)
    return cookie != "0"


@profile_required
@remember_page
def subject_contents(request, pk):
    subject = get_object_or_404(_subjects(request.profile), pk=pk)
    context = reading.build_reading(subject, request.user)
    context.update(subject=subject, crumbs=_crumbs(subject), in_context=_in_context(request),
                   **edit_context(request), **_panel_subjects(request.profile))
    return render(request, "diary/subject_contents.html", context)


def _render_reading(request, subject, scope, target, crumbs):
    context = reading.build_reading(subject, request.user, scope, target)
    current_topic = target.pk if scope == "topic" else (target.topic_id if scope == "subtopic" else None)
    context.update(subject=subject, scope=scope, target=target, crumbs=crumbs, toc_current_topic=current_topic,
                   in_context=_in_context(request, scope), **edit_context(request), **_panel_subjects(request.profile))
    return render(request, "diary/reader.html", context)


def _crumbs(subject):
    crumbs = []
    if not subject.show_on_landing:
        crumbs.append((None, "Other Subjects", "other_subjects"))
    crumbs.append((subject.pk, subject.name, "read_subject"))
    return crumbs


@profile_required
@remember_page
def read_subject(request, pk):
    subject = get_object_or_404(_subjects(request.profile), pk=pk)
    return _render_reading(request, subject, "subject", None, _crumbs(subject))


@profile_required
@remember_page
def read_topic(request, pk):
    topic = get_object_or_404(Topic.objects.select_related("subject"), pk=pk, profile=request.profile,
                              deleted_at__isnull=True, subject__deleted_at__isnull=True)
    crumbs = _crumbs(topic.subject) + [(topic.pk, topic.name, None)]
    return _render_reading(request, topic.subject, "topic", topic, crumbs)


@profile_required
@remember_page
def read_subtopic(request, pk):
    subtopic = get_object_or_404(Subtopic.objects.select_related("subject", "topic__subject"), pk=pk,
                                 profile=request.profile, deleted_at__isnull=True)
    topic = subtopic.topic
    subject = topic.subject if topic else subtopic.subject
    if subject.deleted_at is not None or (topic is not None and topic.deleted_at is not None):
        raise Http404
    crumbs = _crumbs(subject)
    if topic:
        crumbs.append((topic.pk, topic.name, "read_topic"))
    crumbs.append((subtopic.pk, subtopic.name, None))
    return _render_reading(request, subject, "subtopic", subtopic, crumbs)


def healthz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return HttpResponse("database unavailable", status=503, content_type="text/plain")
    return HttpResponse("ok", content_type="text/plain")


def _review_rows(profile):
    """Every live Item and Section marked For review in ``profile``, with its path (document order after import).

    This is Search's "For review only" with an empty query (diary/search.py, which locates records with
    diary/locate.py), so the two always list the same records, Items inside Nested Items included.
    """
    rows = []
    for r in search_module.run_search(profile, "", review_only=True):
        text = r.text
        rows.append({
            "kind": "Item, inside a Nested Item" if r.in_nested else r.kind,
            "subject_id": r.subject_id,
            "path": " > ".join(name for name, _url in r.path),
            "text": text if len(text) <= 160 else text[:157] + "...",
            "note": r.review_note,
            "url": r.url,
            "order": r.order,
        })
    return rows  # run_search already returns them in Diary order


@profile_required
@remember_page
def review_list(request):
    """Docs/DESIGN.md section 5.12: everything marked For review, with path and note."""
    rows = _review_rows(request.profile)
    subject_counts = {}
    for r in rows:
        subject_counts[r["subject_id"]] = subject_counts.get(r["subject_id"], 0) + 1
    panel = _panel_subjects(request.profile)
    choices = [(s.pk, s.name, subject_counts[s.pk]) for s in panel["panel_main"] + panel["panel_other"]
               if s.pk in subject_counts]
    chosen = None
    raw = request.GET.get("subject", "")
    if safe_int(raw) in subject_counts:
        chosen = safe_int(raw)
        rows = [r for r in rows if r["subject_id"] == chosen]
    return render(request, "diary/review_list.html", {
        "rows": rows, "total": len(rows), "all_total": sum(subject_counts.values()),
        "subject_choices": choices, "chosen_subject": chosen,
    })


SEARCH_PAGE = 50
SEARCH_MAX = 1000


@profile_required
@remember_page
def search(request):
    """Global Search (docs/DESIGN.md section 10). Everything is in the address, so Back and bookmarks work."""
    profile = request.profile
    query = request.GET.get("q", "").strip()[:500]
    panel = _panel_subjects(profile)
    live = {s.pk for s in panel["panel_main"] + panel["panel_other"]}
    raw = request.GET.get("subject", "")
    subject_id = safe_int(raw) if safe_int(raw) in live else None
    citations_only = request.GET.get("citations") == "1"
    review_only = request.GET.get("review") == "1"
    raw_limit = request.GET.get("limit", "")
    limit = safe_int(raw_limit) or SEARCH_PAGE
    limit = min(limit, SEARCH_MAX)
    searched = bool(query) or citations_only or review_only
    results = search_module.run_search(
        profile, query, subject_id=subject_id, citations_only=citations_only, review_only=review_only
    ) if searched else []
    more_params = {"q": query, "limit": min(limit + SEARCH_PAGE, SEARCH_MAX)}
    if subject_id:
        more_params["subject"] = subject_id
    if citations_only:
        more_params["citations"] = 1
    if review_only:
        more_params["review"] = 1
    return render(request, "diary/search.html", {
        "q": query, "searched": searched, "results": results[:limit], "total": len(results),
        "has_more": len(results) > limit and limit < SEARCH_MAX,
        "more_query": urlencode(more_params),
        "main_subjects": panel["panel_main"], "other_subjects": panel["panel_other"],
        "chosen_subject": subject_id, "citations_only": citations_only, "review_only": review_only,
    })


logger = logging.getLogger(__name__)

MAX_IMPORT_MB = 25


def _import_context(extra=None):
    context = {
        "profiles": Profile.objects.filter(program=KEY_DIARY, deleted_at__isnull=True).order_by("name"),
        "max_mb": MAX_IMPORT_MB,
    }
    context.update(extra or {})
    return context


IMPORT_COMMAND = "python manage.py import_docx --profile {name!r} --import"


@admin_required
def import_word(request):
    """Admin only: dry run and reconciliation of the Word file against a chosen profile (Milestone 2).

    The import itself is NOT run from this screen (decision D-e in docs/DESIGN.md): it makes about 2,500 saves
    and two backups, which can outlast the 60-second web request limit on Render. It is run from the Render Shell
    with the ``import_docx`` command, which has no such limit. This screen shows the exact command.
    """
    if request.method != "POST":
        return render(request, "diary/import.html", _import_context())
    action = request.POST.get("action", "")
    upload = request.FILES.get("file")
    profile = Profile.objects.filter(
        pk=request.POST.get("profile") or None, program=KEY_DIARY, deleted_at__isnull=True
    ).first()

    def again(message):
        messages.error(request, message)
        return render(request, "diary/import.html", _import_context({"chosen": profile}))

    if action == "import":
        return again(
            "The import is not run from this screen (it can take longer than the web request limit). Run the dry "
            "run here, then in the Render Shell run: "
            + IMPORT_COMMAND.format(name=profile.name if profile else "<profile name>")
        )
    if upload is None:
        return again("Choose the Word file first.")
    if upload.size > MAX_IMPORT_MB * 1024 * 1024:
        return again(f"That file is larger than {MAX_IMPORT_MB} MB.")
    data = upload.read()
    if action not in ("dry_run", "dry_run_download") and profile is None:
        return again("Choose the profile to check against.")
    stamp = timezone.localtime().strftime("%Y%m%d-%H%M%S")

    def download(text, name):
        response = HttpResponse(text, content_type="text/plain; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{name}-{stamp}.txt"'
        return response

    try:
        if action in ("dry_run", "dry_run_download"):
            plan, text = import_service.dry_run(data, upload.name, profile)
            if action == "dry_run_download":
                return download(text, "dry-run-report")
            if profile is not None:
                state, state_messages = import_loader.check_state(plan, profile)
            else:
                state, state_messages = None, ["Choose a profile to see whether the import could run there."]
            ready = state == import_loader.STATE_FRESH
            return render(request, "diary/import.html", _import_context({
                "chosen": profile, "report": text, "report_title": "Dry run (nothing saved)",
                "state_messages": state_messages, "file_name": upload.name, "can_import": ready,
                "command": IMPORT_COMMAND.format(name=profile.name) if ready else "",
            }))
        if action in ("reconcile", "reconcile_download"):
            _, text = import_service.reconcile(data, upload.name, profile)
            if action == "reconcile_download":
                return download(text, "reconciliation-report")
            return render(request, "diary/import.html", _import_context({
                "chosen": profile, "report": text, "report_title": "Reconciliation", "file_name": upload.name,
            }))
    except (import_service.DocxError, import_service.ImportRefused) as exc:
        return again(str(exc))
    except Exception:  # never a server error page; nothing is saved by a dry run or a reconciliation
        logger.exception("Word import screen failed")
        return again("Something unexpected went wrong while reading the file. Nothing was saved. Try the Render Shell command or ask for help.")
    return again("Unknown action.")
