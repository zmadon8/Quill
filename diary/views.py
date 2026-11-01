from django.db import connection
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render

from accounts.permissions import reader_required

from . import reading
from .models import Subject, Subtopic, Topic


def _subjects(**filters):
    return Subject.objects.filter(deleted_at__isnull=True, **filters)


@reader_required
def home(request):
    tiles = _subjects(show_on_landing=True).order_by("landing_position", "name", "pk")
    return render(request, "diary/home.html", {"subjects": tiles})


@reader_required
def other_subjects(request):
    subjects = _subjects(show_on_landing=False).order_by("other_acts_position", "name", "pk")
    return render(request, "diary/other_subjects.html", {"subjects": subjects})


@reader_required
def search(request):
    return render(request, "diary/search.html")


@reader_required
def subject_contents(request, pk):
    subject = get_object_or_404(_subjects(), pk=pk)
    context = reading.build_reading(subject, request.user)
    context.update(subject=subject, crumbs=_crumbs(subject))
    return render(request, "diary/subject_contents.html", context)


def _render_reading(request, subject, scope, target, crumbs):
    context = reading.build_reading(subject, request.user, scope, target)
    context.update(subject=subject, scope=scope, target=target, crumbs=crumbs)
    return render(request, "diary/reader.html", context)


def _crumbs(subject):
    crumbs = []
    if not subject.show_on_landing:
        crumbs.append((None, "Other Subjects", "other_subjects"))
    crumbs.append((subject.pk, subject.name, "subject_contents"))
    return crumbs


@reader_required
def read_subject(request, pk):
    subject = get_object_or_404(_subjects(), pk=pk)
    return _render_reading(request, subject, "subject", None, _crumbs(subject))


@reader_required
def read_topic(request, pk):
    topic = get_object_or_404(Topic.objects.select_related("subject"), pk=pk, deleted_at__isnull=True,
                              subject__deleted_at__isnull=True)
    crumbs = _crumbs(topic.subject) + [(topic.pk, topic.name, None)]
    return _render_reading(request, topic.subject, "topic", topic, crumbs)


@reader_required
def read_subtopic(request, pk):
    subtopic = get_object_or_404(Subtopic.objects.select_related("subject", "topic__subject"), pk=pk,
                                 deleted_at__isnull=True)
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
