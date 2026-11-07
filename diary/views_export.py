"""Word export screens (Milestone 6, docs/DESIGN.md section 12).

``/caselaw/export/`` is the page with the options; ``/caselaw/export/download/`` makes the file. Everyone who
uses the profile (Admin, Editor or Reader) may make every export: Full, by Subject, a Subject, a Current View, and the
Offline copy of the whole diary or of a part (D98).
"""
import copy
import logging
import time

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_POST

from accounts.profiles import effective_export_name, export_file_name

from .forms import ExportSettingsForm, ProfileSettingsForm

from .models import Subject
from .params import safe_int
from .sorting import sort_headings
from .views import profile_required, render_settings_page, user_can_edit
from .wordexport import service

logger = logging.getLogger(__name__)

KINDS = ("subject", "topic", "subtopic")


def _scope(request, kind, pk):
    """(kind, pk, path names) for a Current View of this profile, or (None, None, []) if none was asked for. 404 if it is not there."""
    if kind not in KINDS:
        return None, None, []
    pk = safe_int(pk)
    if pk is None:
        raise Http404
    try:
        path = service.scope_path(request.profile, kind, pk)
    except service.ExportError:
        raise Http404
    return kind, pk, path


def _file_settings(request, form=None):
    """The "File name and date" part of the Export page (round 18, D97)."""
    import copy

    from .wordexport import naming

    form = form or ExportSettingsForm(user=request.user, profile=request.profile)
    shown = copy.copy(request.profile)  # an invalid POST must not change what the page says the files start with
    return {"file_form": form, "file_preview": export_file_name(shown),
            "file_replaced": naming.replacements(effective_export_name(shown))}


@profile_required
@require_POST
def export_settings(request):
    """Save the export file name (the profile's; only its Editors change it). It is a section of Case Law Diary settings >
    Data, so a save returns there. My date format is on My settings; a client that still posts it here is accepted."""
    if not user_can_edit(request):
        return render(request, "403.html", status=403)
    form = ExportSettingsForm(request.POST, user=request.user, profile=request.profile)
    if form.is_valid():
        form.save()
        messages.success(request, "Export file name saved.")
        return redirect(reverse("profile_settings") + "?tab=data")
    return render_settings_page(request, "data", True, ProfileSettingsForm(
        instance=copy.copy(request.profile), prefix="diary"), form)


@profile_required
def export_page(request):
    return _render_page(request, request.GET.get("kind", ""), request.GET.get("pk", ""))


def _render_page(request, kind, pk):
    kind, pk, path = _scope(request, kind, pk)
    subjects = Subject.objects.filter(profile=request.profile, deleted_at__isnull=True)
    main = sort_headings(subjects.filter(show_on_landing=True))
    other = sort_headings(subjects.filter(show_on_landing=False))
    return render(request, "diary/export.html", {
        "scope_kind": kind, "scope_pk": pk, "scope_path": path,
        "main_subjects": main, "other_subjects": other,
        # Flags are included unless the page is opened with review=0 (checked by default; "review" is the old name, D88).
        "include_review": request.GET.get("review") != "0",
    })


@profile_required
def export_download(request):
    which = request.GET.get("type", "")
    include_review = request.GET.get("review") == "1"
    started = time.monotonic()
    if which in (service.FULL, service.BY_SUBJECT):
        make = service.full if which == service.FULL else service.by_subject
        result = make(request.profile, request.user, include_review)
    elif which == service.OFFLINE:
        result = service.offline_copy(request.profile, request.user, include_review)
    elif which in (service.VIEW, "subject", service.OFFLINE_VIEW, service.OFFLINE_SUBJECT):
        # "subject" is the Subject picker on the Export page: the same as a Current View of that Subject.
        kind, pk = ("subject", safe_int(request.GET.get("subject_pk", ""))) if which in ("subject", service.OFFLINE_SUBJECT) else (
            request.GET.get("kind", ""), safe_int(request.GET.get("pk", "")))
        if kind not in KINDS or pk is None:
            raise Http404
        try:
            if which in (service.OFFLINE_VIEW, service.OFFLINE_SUBJECT):
                result = service.offline_copy(request.profile, request.user, include_review, kind, pk)
            else:
                result = service.current_view(request.profile, request.user, kind, pk, include_review)
        except service.ExportError:
            raise Http404
    else:
        raise Http404
    logger.info("Export %s by user %s in profile %s: %d Items, %d bytes, %.2f s", which, request.user.pk,
                request.profile.pk, result.items, result.size, time.monotonic() - started)
    response = HttpResponse(result.data, content_type=result.content_type)
    response["Content-Disposition"] = content_disposition_header(True, result.name)
    response["X-Export-Items"] = str(result.items)
    return response
