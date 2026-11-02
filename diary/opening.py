"""Where the Case Law Diary opens (My settings) and the "last page I viewed" bookkeeping."""
from functools import wraps

from django.urls import Resolver404, resolve, reverse
from django.utils.http import url_has_allowed_host_and_scheme

from accounts.models import User

from .models import Subject, Subtopic, Topic

DIARY_PREFIX = "/caselaw/"
MAX_PATH = 500
#: Pages that count as "the last page I viewed" (URL names).
REMEMBERED = {"diary_home", "subject_contents", "read_subject", "read_topic", "read_subtopic", "search", "review_list"}


def record_last_page(request, response):
    """Remember this page for the "last page" option: only a plain GET that was shown (200), never Edit mode."""
    if request.method != "GET" or getattr(response, "status_code", None) != 200:
        return
    if request.GET.get("edit") == "1":
        return
    path = request.get_full_path()
    if len(path) > MAX_PATH or path == getattr(request.user, "last_diary_path", None):
        return
    User.objects.filter(pk=request.user.pk).update(last_diary_path=path)
    request.user.last_diary_path = path


def remember_page(view):
    """Put under ``profile_required``: record the page after the view has produced a good response."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        response = view(request, *args, **kwargs)
        record_last_page(request, response)
        return response

    return wrapper


def _valid_last_path(path, profile):
    """True if ``path`` is a remembered kind of diary page whose Subject, Topic or Sub-topic is still live in ``profile``."""
    if not path or not path.startswith(DIARY_PREFIX) or len(path) > MAX_PATH:
        return False
    if not url_has_allowed_host_and_scheme(path, allowed_hosts=None):
        return False
    try:
        match = resolve(path.split("?", 1)[0])
    except Resolver404:
        return False
    if match.url_name not in REMEMBERED:
        return False
    pk = match.kwargs.get("pk")
    live = {"profile": profile, "deleted_at__isnull": True}
    if match.url_name in ("subject_contents", "read_subject"):
        return Subject.objects.filter(pk=pk, **live).exists()
    if match.url_name == "read_topic":
        return Topic.objects.filter(pk=pk, subject__deleted_at__isnull=True, **live).exists()
    if match.url_name == "read_subtopic":
        sub = Subtopic.objects.filter(pk=pk, **live).select_related("subject", "topic__subject").first()
        if sub is None:
            return False
        if sub.topic_id:
            return sub.topic.deleted_at is None and sub.topic.subject.deleted_at is None
        return sub.subject.deleted_at is None
    return True


def opening_url(user, profile):
    """The diary page to open for ``user`` (after login, or on an entry visit to Home)."""
    from .views import opening_subject_for  # views import this module

    settings = getattr(user, "diary_settings", None)
    page = settings.opening_page if settings else "home"
    if page == "other_subjects":
        return reverse("diary_home") + "#other-subjects"
    if page == "search":
        return reverse("search")
    if page == "subject":
        subject = opening_subject_for(user, profile)
        if subject is not None:
            return reverse("read_subject", args=[subject.pk])
    if page == "last":
        path = getattr(user, "last_diary_path", "")
        if _valid_last_path(path, profile):
            return path
    return reverse("diary_home")
