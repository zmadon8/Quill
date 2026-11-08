import copy
import logging
from functools import wraps
from urllib.parse import urlencode, urlsplit

from django.db import connection
from django.db.models import Count, Q
from django.db.models.functions import Coalesce
from django.http import Http404, HttpResponse
from django.utils import timezone
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from accounts import landing as account_landing
from accounts import activity, programs
from accounts.models import ROLE_EDITOR
from accounts.models import Profile
from accounts.permissions import admin_required, reader_required
from accounts.profiles import request_memberships, request_profile, request_role
from accounts.suite import KEY_DIARY, KEY_FEES, get_names

from . import reading, searchtext, undo_session
from .opening import remember_page
from .params import safe_int
from . import search as search_module
from .importer import loader as import_loader
from .importer import service as import_service
from .models import FLAG_CHOICES, FLAG_NONE, Item, Section, Subject, Subtopic, Topic
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


def open_whole_subject(profile):
    """Whether clicking a Subject should open the whole Subject (round 19, user item 4).

    True only when the profile's ``reading_all_mode`` is ``always_on``: the Display tab's Yes/No toggle. Otherwise
    (``always_off`` or ``remember``) a Subject link opens the scoped Contents page with its "Read Whole Subject"
    button, as before. The Table of Contents links are handled separately by ``_in_context``."""
    return profile.reading_all_mode == Profile.READING_ALL_ALWAYS_ON


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
    """One aggregate query: {subject_id: (items, flagged items)} for live Items.

    An Item belongs to a Subject through its Topic or Sub-topic, or directly, so the owning
    Subject is the first non-null of those paths. Items whose own Topic or Sub-topic is deleted are not counted.
    """
    owner = Coalesce(
        "subject_id",
        "topic__subject_id",
        "subtopic__subject_id",
        "subtopic__topic__subject_id",
    )
    rows = (
        Item.objects.filter(profile=profile, deleted_at__isnull=True)
        .exclude(
            Q(topic__deleted_at__isnull=False)
            | Q(subtopic__deleted_at__isnull=False)
            | Q(subtopic__topic__deleted_at__isnull=False)
        )
        .annotate(owner=owner)
        .values("owner")
        .annotate(items=Count("pk"), flagged=Count("pk", filter=~Q(flag="none")))
        .order_by()
    )
    return {r["owner"]: (r["items"], r["flagged"]) for r in rows}


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
    return render(request, "diary/subjects.html", {
        **edit_context(request),
        "subjects": landing,
        "other_subjects": other,
        "subject_total": len(live_ids),
        "item_total": total_items,
        "subject_opens_whole": open_whole_subject(profile),
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
    context = {"diary_profile": request_profile(request)}
    fees_profile = request_profile(request, KEY_FEES)
    if fees_profile is not None and programs.fees_enabled():
        # A Fee Register user gets a button for it; a user without one sees exactly the page they saw before.
        context["fees_profile"] = fees_profile
        context["fees_name"] = get_names()[KEY_FEES]
        # Someone with several Fee Register profiles opens any of them from here, as with the Case Law Diary.
        context["fees_other_profiles"] = [m.profile for m in request_memberships(request, KEY_FEES)[1:]]
        own = (fees_profile.display_name or "").strip()
        if own:
            context["fees_label"] = own
        elif context["fees_other_profiles"]:
            context["fees_label"] = f"{context['fees_name']} \u00b7 {fees_profile.name}"
        else:
            context["fees_label"] = context["fees_name"]
    if activity.can_see_active(request.user):
        context.update(activity.active_panel())
    return render(request, "diary/home.html", context)


@reader_required
def help_page(request):
    """The Help page: plain-language instructions for everyday tasks. Any signed-in user may read it."""
    return render(request, "diary/help.html")


#: The sections of the Case Law Diary Settings tab, in order.
SETTINGS_SECTIONS = ("reading", "data")


@profile_required
def profile_settings(request):
    """The Case Law Diary Settings tab: what everyone using this profile shares, in left-hand sections with a Save each.

    Reading (Home Page Name and Header Name, whether a click on a Subject opens the whole Subject: per profile) and Data (Word import for
    the Admin, the Word export file name, the Offline link for the Admin). Editors and Admins change them; Readers see
    the values with no Save buttons and a POST from a Reader is refused (403). Personal choices (opening page, number
    formats, date in file names) are on My settings.
    """
    from .forms import ExportSettingsForm, ProfileSettingsForm  # lazy: keeps this module's import light

    can_change = user_can_edit(request)
    tab = request.POST.get("tab") or request.GET.get("tab") or "reading"
    if tab not in SETTINGS_SECTIONS:
        tab = "reading"
    reading_form = None
    export_form = None
    if request.method == "POST":
        if not can_change:
            return render(request, "403.html", status=403)
        # A copy, so an invalid POST does not change the header of the page shown with the errors. (The export file
        # name has its own Save, which posts to ``export_settings``.)
        tab = "reading"
        reading_form = ProfileSettingsForm(request.POST, instance=copy.copy(request.profile), prefix="diary")
        if reading_form.is_valid():
            reading_form.save()
            messages.success(request, "Settings saved.")
            return redirect(reverse("profile_settings") + "?tab=reading")
    if can_change:
        reading_form = reading_form or ProfileSettingsForm(instance=copy.copy(request.profile), prefix="diary")
        export_form = ExportSettingsForm(user=request.user, profile=request.profile)
    return render_settings_page(request, tab, can_change, reading_form, export_form)


def render_settings_page(request, tab, can_change, reading_form, export_form):
    """The page shared by the Settings tab and an invalid export file name save."""
    from .views_export import _file_settings  # lazy: views_export imports this module

    profile = request.profile
    mode = profile.reading_all_mode
    whole = mode == Profile.READING_ALL_ALWAYS_ON or (
        mode not in (Profile.READING_ALL_ALWAYS_ON, Profile.READING_ALL_ALWAYS_OFF) and profile.reading_all_default
    )
    return render(request, "diary/settings.html", {
        "tab": tab, "can_change": can_change, "reading_form": reading_form, "whole_subject": whole,
        "sections": SETTINGS_SECTIONS, **_file_settings(request, export_form),
    })


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
        "subject_opens_whole": open_whole_subject(profile),
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
    # The breadcrumb is the same for every Subject: no "Other Subjects" step (D82).
    crumbs = [(subject.pk, subject.name, "read_subject")]
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


@profile_required
def review_list(request):
    """The old Review list (everything marked For review) became the Flags page (D88, D89): its address forwards there."""
    return redirect(reverse("flags") + ("?" + request.GET.urlencode() if request.GET else ""))


SEARCH_PAGE = 50
SEARCH_MAX = 1000
#: The kinds of flag the Flags page can show (D89): every flag, or one kind.
FLAG_FILTERS = [("", "All flags")] + [(key, name) for key, name in FLAG_CHOICES if key != "none"]


def _grouped(request, results, panel, base_params, limit):
    """The "Grouped by Subject" view of ``results`` (shared by Search, Flags and Hyperlinks): a list of the Subjects that
    have results, with counts, and the results of the chosen Subject (``?s=``; the first one when none is chosen)."""
    counts = {}
    for r in results:
        counts[r.subject_id] = counts.get(r.subject_id, 0) + 1
    groups = [{"subject": s, "count": counts[s.pk]} for s in panel["panel_main"] + panel["panel_other"] if s.pk in counts]
    picked = safe_int(request.GET.get("s"))
    pick_group = next((g for g in groups if g["subject"].pk == picked), None)
    chosen_group = pick_group or (groups[0] if groups else None)
    for g in groups:
        g["url"] = "?" + urlencode(dict(base_params, s=g["subject"].pk))
    shown = [r for r in results if chosen_group and r.subject_id == chosen_group["subject"].pk]
    more = dict(base_params, limit=min(limit + SEARCH_PAGE, SEARCH_MAX))
    if chosen_group:
        more["s"] = chosen_group["subject"].pk
    return {
        "groups": groups, "chosen_group": chosen_group, "picked_valid": pick_group is not None,
        "results": shown[:limit], "shown_total": len(shown), "total": len(results),
        "has_more": len(shown) > limit and limit < SEARCH_MAX,
        "more_url": request.path + "?" + urlencode(more),
        "back_url": "?" + urlencode(base_params),
    }


def _limit(request):
    return min(safe_int(request.GET.get("limit", "")) or SEARCH_PAGE, SEARCH_MAX)


@profile_required
@remember_page
def search(request):
    """Global Search (docs/DESIGN.md section 10). Everything is in the address, so Back and bookmarks work.

    The ticks (D90): Group by Subject (a way of showing the results, not a search filter), Citations, Flags (look only in
    the text beside flags; an older address's ``review=1`` means the same) and Headers.
    """
    profile = request.profile
    query = request.GET.get("q", "").strip()[:500]
    panel = _panel_subjects(profile)
    live = {s.pk for s in panel["panel_main"] + panel["panel_other"]}
    raw = request.GET.get("subject", "")
    subject_id = safe_int(raw) if safe_int(raw) in live else None
    citations_only = request.GET.get("citations") == "1"
    flags_only = request.GET.get("flags") == "1" or request.GET.get("review") == "1"
    limit = _limit(request)
    headers_only = request.GET.get("headers") == "1"
    searched = bool(query) or citations_only or flags_only
    results = search_module.run_search(
        profile, query, subject_id=subject_id, citations_only=citations_only, flags_only=flags_only,
        headers_only=headers_only,
    ) if searched else []
    # Grouped by Subject: only when the whole database is searched (a Subject filter always uses the plain cards).
    want_subjects = request.GET.get("view") == "subjects"
    by_subject = bool(results) and subject_id is None and want_subjects
    base_params = {"q": query}
    if subject_id:
        base_params["subject"] = subject_id
    if citations_only:
        base_params["citations"] = 1
    if flags_only:
        base_params["flags"] = 1
    if headers_only:
        base_params["headers"] = 1
    context = {
        "q": query, "searched": searched, "total": len(results),
        "main_subjects": panel["panel_main"], "other_subjects": panel["panel_other"],
        "chosen_subject": subject_id, "citations_only": citations_only, "flags_only": flags_only,
        "headers_only": headers_only, "want_subjects": want_subjects, "by_subject": by_subject,
        "notice": searchtext.parse_search(query).notice,
        "cards_url": "?" + urlencode(base_params),
        "subjects_url": "?" + urlencode(dict(base_params, view="subjects")),
    }
    if by_subject:
        context.update(_grouped(request, results, panel, dict(base_params, view="subjects"), limit))
    else:
        more = dict(base_params, limit=min(limit + SEARCH_PAGE, SEARCH_MAX))
        context.update(results=results[:limit], shown_total=len(results),
                       has_more=len(results) > limit and limit < SEARCH_MAX,
                       more_url=request.path + "?" + urlencode(more))
    return render(request, "diary/search.html", context)


def _flag_filters_present(profile, chosen):
    """``FLAG_FILTERS`` cut to "All flags" and the kinds of flag some live Item or Section carries now, plus the
    kind chosen. Two small queries (Sections, Items), no per-row work."""
    present = set()
    for model in (Section, Item):
        present.update(model.objects.filter(profile=profile, deleted_at__isnull=True).exclude(flag=FLAG_NONE)
                       .order_by().values_list("flag", flat=True).distinct())
    return [(key, name) for key, name in FLAG_FILTERS if key == "" or key in present or key == chosen]


@profile_required
@remember_page
def flags_page(request):
    """The Flags tab, Flags page (D89): every flagged Item and Section, or one kind of flag, grouped by Subject like
    Search; the search box looks ONLY in the text beside the flags."""
    profile = request.profile
    query = request.GET.get("q", "").strip()[:500]
    kind = request.GET.get("flag", "")
    if kind not in dict(FLAG_FILTERS):
        kind = ""
    results = search_module.run_search(profile, query, flags_only=True, flag_kind=kind or None)
    base_params = {k: v for k, v in (("q", query), ("flag", kind)) if v}
    context = {"q": query, "flag": kind, "flag_filters": _flag_filters_present(profile, kind), "tab": "flags",
               "notice": searchtext.parse_search(query).notice}
    context.update(_grouped(request, results, _panel_subjects(profile), base_params, _limit(request)))
    return render(request, "diary/flags.html", context)


@profile_required
@remember_page
def flag_links(request):
    """The Flags tab, Hyperlinks page (D89): the citations WITH a web address (the search box looks in the address) or
    WITHOUT one (it looks in the citation), grouped by Subject like Search."""
    profile = request.profile
    query = request.GET.get("q", "").strip()[:500]
    which = "without" if request.GET.get("links") == "without" else "with"
    results = search_module.run_links(profile, query, with_links=which == "with")
    base_params = {k: v for k, v in (("q", query), ("links", "without" if which == "without" else "")) if v}
    context = {"q": query, "which": which, "tab": "links", "notice": searchtext.parse_search(query).notice}
    context.update(_grouped(request, results, _panel_subjects(profile), base_params, _limit(request)))
    return render(request, "diary/flag_links.html", context)


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
