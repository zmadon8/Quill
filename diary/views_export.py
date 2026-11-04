"""Word export screens (Milestone 6, docs/DESIGN.md section 12).

``/caselaw/export/`` is the page with the options; ``/caselaw/export/download/`` makes the file. Readers may export
the Current View only; the two Full exports are for Editors of the profile and the Admin (section 9.6).
"""
import logging
import time

from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_POST

from accounts.profiles import effective_export_name, export_file_name

from .forms import ExportSettingsForm

from .models import Subject
from .params import safe_int
from .sorting import sort_headings
from .views import profile_required, user_can_edit
from .wordexport import service

logger = logging.getLogger(__name__)

KINDS = ("subject", "topic", "subtopic")


def can_export_full(request):
    """Editors of the profile, and the Admin, may export the whole diary."""
    return user_can_edit(request) or bool(getattr(request.user, "is_admin", False))


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


def _back_to_export(request):
    keep = {key: request.POST[key] for key in ("kind", "pk") if request.POST.get(key)}
    return reverse("export") + ("?" + urlencode(keep) if keep else "")


@profile_required
@require_POST
def export_settings(request):
    """Save the export file name (the profile's; any member may change it) and my date format."""
    form = ExportSettingsForm(request.POST, user=request.user, profile=request.profile)
    if form.is_valid():
        form.save()
        messages.success(request, "Export settings saved.")
        return redirect(_back_to_export(request))
    return _render_page(request, request.POST.get("kind", ""), request.POST.get("pk", ""), form)


@profile_required
def export_page(request):
    return _render_page(request, request.GET.get("kind", ""), request.GET.get("pk", ""))


def _render_page(request, kind, pk, file_form=None):
    kind, pk, path = _scope(request, kind, pk)
    subjects = Subject.objects.filter(profile=request.profile, deleted_at__isnull=True)
    main = sort_headings(subjects.filter(show_on_landing=True))
    other = sort_headings(subjects.filter(show_on_landing=False))
    return render(request, "diary/export.html", {
        "can_full": can_export_full(request),
        "scope_kind": kind, "scope_pk": pk, "scope_path": path,
        "main_subjects": main, "other_subjects": other,
        # Flags are included unless the page is opened with review=0 (checked by default; "review" is the old name, D88).
        "include_review": request.GET.get("review") != "0",
        **_file_settings(request, file_form),
    })


@profile_required
def export_download(request):
    which = request.GET.get("type", "")
    include_review = request.GET.get("review") == "1"
    started = time.monotonic()
    if which in (service.FULL, service.BY_SUBJECT):
        if not can_export_full(request):
            raise PermissionDenied  # a Reader may export the Current View only
        make = service.full if which == service.FULL else service.by_subject
        result = make(request.profile, request.user, include_review)
    elif which in (service.VIEW, "subject"):
        # "subject" is the Subject picker on the Export page: the same as a Current View of that Subject.
        kind, pk = ("subject", safe_int(request.GET.get("subject_pk", ""))) if which == "subject" else (
            request.GET.get("kind", ""), safe_int(request.GET.get("pk", "")))
        if kind not in KINDS or pk is None:
            raise Http404
        try:
            result = service.current_view(request.profile, request.user, kind, pk, include_review)
        except service.ExportError:
            raise Http404
    else:
        raise Http404
    logger.info("Word export %s by user %s in profile %s: %d Items, %d bytes, %.2f s", which, request.user.pk,
                request.profile.pk, result.items, result.size, time.monotonic() - started)
    response = HttpResponse(result.data, content_type=result.content_type)
    response["Content-Disposition"] = content_disposition_header(True, result.name)
    response["X-Export-Items"] = str(result.items)
    return response
