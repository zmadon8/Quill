from functools import wraps

from django.core.exceptions import PermissionDenied
from django.db import connection
from django.db.models import Count, Q
from django.db.models.functions import Coalesce
from django.http import Http404, HttpResponse
from django.utils import timezone
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from accounts.models import ROLE_EDITOR
from accounts.models import Profile
from accounts.permissions import admin_required, program_role, reader_required
from accounts.profiles import export_file_name, request_profile
from accounts.suite import KEY_DIARY

from . import reading
from .forms import ProfileSettingsForm
from .importer import loader as import_loader
from .importer import service as import_service
from .importer.docx_reader import file_digest
from .models import Item, Section, Subject, Subtopic, Topic

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


def _subjects(profile, **filters):
    return Subject.objects.filter(profile=profile, deleted_at__isnull=True, **filters)


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
def subjects(request):
    """Option A index: Subjects on the landing page with item counts, then Other Subjects."""
    profile = request.profile
    counts = item_counts_by_subject(profile)
    landing = list(_subjects(profile, show_on_landing=True).order_by("landing_position", "name", "pk"))
    for subject in landing:
        subject.item_count = counts.get(subject.pk, (0, 0))[0]
    other_count = _subjects(profile, show_on_landing=False).count()
    live_ids = set(_subjects(profile).values_list("pk", flat=True))
    total_items = sum(n for pk, (n, _) in counts.items() if pk in live_ids)
    total_review = sum(r for pk, (_, r) in counts.items() if pk in live_ids)
    return render(request, "diary/subjects.html", {
        "subjects": landing,
        "other_count": other_count,
        "subject_total": len(live_ids),
        "item_total": total_items,
        "review_total": total_review,
    })


@reader_required
def home(request):
    """Suite Home: the program picker (only the case law diary today)."""
    return render(request, "diary/home.html", {"diary_profile": request_profile(request)})


@profile_required
def profile_settings(request):
    """Settings of the user's profile. Editors can change the export name; Readers only view it."""
    profile = request.profile
    can_edit = program_role(request.user, profile.program) == ROLE_EDITOR
    form = ProfileSettingsForm(request.POST or None, instance=profile)
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
    subjects = _subjects(request.profile, show_on_landing=False).order_by("other_acts_position", "name", "pk")
    return render(request, "diary/other_subjects.html", {"subjects": subjects})


@profile_required
def search(request):
    return render(request, "diary/search.html")


@profile_required
def subject_contents(request, pk):
    subject = get_object_or_404(_subjects(request.profile), pk=pk)
    context = reading.build_reading(subject, request.user)
    context.update(subject=subject, crumbs=_crumbs(subject))
    return render(request, "diary/subject_contents.html", context)


def _render_reading(request, subject, scope, target, crumbs):
    context = reading.build_reading(subject, request.user, scope, target)
    current_topic = target.pk if scope == "topic" else (target.topic_id if scope == "subtopic" else None)
    context.update(subject=subject, scope=scope, target=target, crumbs=crumbs, toc_current_topic=current_topic)
    return render(request, "diary/reader.html", context)


def _crumbs(subject):
    crumbs = []
    if not subject.show_on_landing:
        crumbs.append((None, "Other Subjects", "other_subjects"))
    crumbs.append((subject.pk, subject.name, "read_subject"))
    return crumbs


@profile_required
def read_subject(request, pk):
    subject = get_object_or_404(_subjects(request.profile), pk=pk)
    return _render_reading(request, subject, "subject", None, _crumbs(subject))


@profile_required
def read_topic(request, pk):
    topic = get_object_or_404(Topic.objects.select_related("subject"), pk=pk, profile=request.profile,
                              deleted_at__isnull=True, subject__deleted_at__isnull=True)
    crumbs = _crumbs(topic.subject) + [(topic.pk, topic.name, None)]
    return _render_reading(request, topic.subject, "topic", topic, crumbs)


@profile_required
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
    """Every live Item and Section marked For review in ``profile``, with its path (document order after import)."""
    rows = []
    items = Item.objects.filter(profile=profile, needs_review=True, deleted_at__isnull=True).select_related(
        "subject", "topic__subject", "subtopic__subject", "subtopic__topic__subject"
    )
    sections = Section.objects.filter(profile=profile, needs_review=True, deleted_at__isnull=True).select_related(
        "subject", "topic__subject", "subtopic__subject", "subtopic__topic__subject"
    )
    for kind, queryset in (("Item", items), ("Section", sections)):
        for obj in queryset.order_by("pk"):
            subtopic = obj.subtopic
            topic = obj.topic or (subtopic.topic if subtopic else None)
            subject = obj.subject or (topic.subject if topic else None) or (subtopic.subject if subtopic else None)
            chain = [x for x in (subject, topic, subtopic) if x is not None]
            if subject is None or any(x.deleted_at is not None for x in chain):
                continue  # an Item inside a Nested Item or a deleted parent is not listed here
            link = ("read_subtopic", subtopic.pk) if subtopic else (
                ("read_topic", topic.pk) if topic else ("read_subject", subject.pk))
            text = obj.text_plain if kind == "Item" else obj.name
            rows.append({
                "kind": kind,
                "path": " > ".join(x.name for x in chain),
                "text": text if len(text) <= 160 else text[:157] + "...",
                "note": obj.review_note,
                "url": reverse(link[0], args=[link[1]]),
                "order": (subject.show_on_landing is False, subject.landing_position or subject.other_acts_position,
                          subject.pk, obj.pk),
            })
    rows.sort(key=lambda r: r["order"])
    return rows


@profile_required
def review_list(request):
    """Docs/DESIGN.md section 5.12: everything marked For review, with path and note."""
    rows = _review_rows(request.profile)
    return render(request, "diary/review_list.html", {"rows": rows, "total": len(rows)})


MAX_IMPORT_MB = 25


def _import_context(extra=None):
    context = {
        "profiles": Profile.objects.filter(program=KEY_DIARY, deleted_at__isnull=True).order_by("name"),
        "max_mb": MAX_IMPORT_MB,
    }
    context.update(extra or {})
    return context


@admin_required
def import_word(request):
    """Admin only: dry run, import and reconciliation of the Word file into a chosen profile (Milestone 2).

    Nothing is kept between requests: each button sends the file again. The import only runs with the
    SHA-256 of the file that was shown in a dry run, so what is imported is what was approved.
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

    if upload is None:
        return again("Choose the Word file first.")
    if upload.size > MAX_IMPORT_MB * 1024 * 1024:
        return again(f"That file is larger than {MAX_IMPORT_MB} MB.")
    data = upload.read()
    if action != "dry_run" and action != "dry_run_download" and profile is None:
        return again("Choose the profile to import into.")
    stamp = timezone.now().strftime("%Y%m%d-%H%M%S")

    def download(text, name):
        response = HttpResponse(text, content_type="text/plain; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{name}-{stamp}.txt"'
        return response

    try:
        if action in ("dry_run", "dry_run_download"):
            plan, text = import_service.dry_run(data, upload.name)
            if action == "dry_run_download":
                return download(text, "dry-run-report")
            state = None
            if profile is not None:
                state, state_messages = import_loader.check_state(plan, profile)
            else:
                state_messages = ["Choose a profile to see whether the import could run there."]
            ready = state == import_loader.STATE_FRESH
            return render(request, "diary/import.html", _import_context({
                "chosen": profile, "report": text, "report_title": "Dry run (nothing saved)",
                "sha256": file_digest(data) if ready else "",
                "state_messages": state_messages, "file_name": upload.name, "can_import": ready,
            }))
        if action in ("reconcile", "reconcile_download"):
            _, text = import_service.reconcile(data, upload.name, profile)
            if action == "reconcile_download":
                return download(text, "reconciliation-report")
            return render(request, "diary/import.html", _import_context({
                "chosen": profile, "report": text, "report_title": "Reconciliation", "file_name": upload.name,
            }))
        if action == "import":
            if request.POST.get("confirm_word", "").strip() != "IMPORT":
                return again('Type IMPORT in the box to confirm.')
            if not request.POST.get("sha256"):
                return again("Run the dry run first and import from its page.")
            text, notes = import_service.run_import(
                data, upload.name, profile, request.user, expected_sha256=request.POST["sha256"]
            )
            for note in notes:
                messages.info(request, note)
            return render(request, "diary/import.html", _import_context({
                "chosen": profile, "report": text, "report_title": "Reconciliation after the import",
                "file_name": upload.name,
            }))
    except (import_service.DocxError, import_service.ImportRefused) as exc:
        return again(str(exc))
    return again("Unknown action.")
