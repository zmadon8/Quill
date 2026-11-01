from functools import wraps

from django.db import connection
from django.db.models import Count, Q
from django.db.models.functions import Coalesce
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render

from accounts.permissions import reader_required
from accounts.profiles import request_profile

from . import reading
from .models import Item, Subject, Subtopic, Topic

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
