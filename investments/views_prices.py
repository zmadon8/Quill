"""Prices: the Update Prices endpoint, the Price sources page and the history upload (plan 24.5, 21 and 29)."""
import os
import secrets
import tempfile
import time
from pathlib import Path

from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse

from . import forms
from .decorators import inv_admin, inv_editor
from .errors import InvestmentsError
from .models import Instrument, PriceStatus, SourceRun
from .services import fetch, locks, price_import
from .viewutil import page, profile_or_404

UPLOAD_DIR = Path(tempfile.gettempdir()) / "quill_inv_uploads"
UPLOAD_MAX_AGE = 3600
WEB_UPLOAD_MAX_BYTES = 3 * 1024 * 1024


@inv_editor
def update_prices(request):
    """One step of the chunked Update Prices (plan 24.5): each call fetches one small batch inside the one-at-a-time lock and
    returns progress, so no request runs long and no worker or queue is needed."""
    if request.method != "POST":
        raise Http404
    profile = profile_or_404(request)
    try:
        step = max(0, int(request.POST.get("step", 0)))
    except ValueError:
        step = 0
    if step == 0:
        if not fetch.start_allowed():
            return JsonResponse({"ok": False, "message": "Prices were just updated. Please wait about a minute before updating again."}, status=429)
        fetch.mark_button_used()
    plan = fetch.update_plan(profile)
    if step >= len(plan):
        return JsonResponse({"ok": True, "done": True, "step": step, "steps": len(plan), "updated": 0, "tried": 0, "failures": []})
    try:
        with locks.heavy("price_update"):
            summary = fetch.fetch_prices(ids=plan[step], profile=profile, trigger="button", max_seconds=45, spacing=1.0)
    except locks.Busy:
        return JsonResponse({"ok": False, "message": "An update is already in progress."}, status=503)
    return JsonResponse({"ok": True, "done": step + 1 >= len(plan), "step": step, "steps": len(plan), "updated": summary["updated"],
                         "tried": summary["tried"], "failures": summary["failures"][:10], "stopped": summary["stopped"]})


@inv_admin
def price_sources(request):
    last_runs = {}
    for run in SourceRun.objects.exclude(finished=None)[:200]:
        last_runs.setdefault(run.source, run)
    sources = []
    for key, label in (("yahoo", "Yahoo (shares, indices, foreign)"), ("amfi", "AMFI daily file (mutual funds)"), ("mfapi", "mfapi.in (fund history)")):
        run = last_runs.get(key)
        sources.append({"key": key, "label": label, "run": run, "failures": (run.failures if run else []),
                        "count": Instrument.objects.filter(price_source=key).count()})
    summary = fetch.status_summary()
    runs = SourceRun.objects.all()[:20]
    return page(request, "investments/price_sources.html", {
        "page_title_text": "Price sources", "sources": sources, "summary": summary, "runs": runs, "version": fetch.price_version(),
        "last_button": PriceStatus.objects.values_list("last_button_update_at", flat=True).first(),
    }, selectors=False)


def _staged_path(token):
    if not token or not token.isalnum():
        raise Http404
    for path in UPLOAD_DIR.glob(f"{token}.*"):
        return path
    raise Http404


def _clean_staged():
    if UPLOAD_DIR.exists():
        cutoff = time.time() - UPLOAD_MAX_AGE
        for path in UPLOAD_DIR.iterdir():
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)


@inv_admin
def price_upload(request):
    """Step 1: choose a file (dry run shown, nothing written). Step 2: apply the staged file, all or nothing."""
    profile_or_404(request)
    report = token = None
    form = forms.PriceUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST":
        try:
            if request.POST.get("apply"):
                path = _staged_path(request.POST.get("token", ""))
                written = price_import.apply(path, default_basis=request.POST.get("basis", ""),
                                             instrument=Instrument.objects.filter(pk=request.POST.get("instrument") or 0).first())
                path.unlink(missing_ok=True)
                messages.success(request, f"{written} prices written.")
                return redirect(reverse("investments_admin_prices"))
            if form.is_valid():
                upload = form.cleaned_data["file"]
                if upload.size > WEB_UPLOAD_MAX_BYTES:
                    raise InvestmentsError("TOO_BIG", "This file is too big for the web page (about 100,000 rows takes longer than the 60 second limit). "
                                           "Use 'python manage.py import_prices --file ...' in the Render Shell instead.")
                ext = os.path.splitext(upload.name)[1].lower()
                if ext not in (".csv", ".xlsx"):
                    raise InvestmentsError("BAD_FILE", "Only .csv and .xlsx files can be uploaded.")
                UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
                _clean_staged()
                token = secrets.token_hex(12)
                path = UPLOAD_DIR / f"{token}{ext}"
                with open(path, "wb") as out:
                    for chunk in upload.chunks():
                        out.write(chunk)
                instrument = form.cleaned_data.get("instrument")
                report = price_import.dry_run(path, default_basis=form.cleaned_data["basis"], instrument=instrument)
        except InvestmentsError as err:
            form.add_error(None, err.message)
            if token:
                _staged_path(token).unlink(missing_ok=True)
                token = None
    return page(request, "investments/price_upload.html", {"page_title_text": "Upload price history", "form": form, "report": report, "token": token,
                                                          "basis": form.data.get("basis", "") if form.is_bound else "",
                                                          "instrument_id": form.data.get("instrument", "") if form.is_bound else ""}, selectors=False)


# ------------------------------------------------------------------ price history: pruning, archive, pins (plan 17 and 21)

@inv_admin
def price_history(request):
    from . import forms as inv_forms
    from .models import PriceMaintenanceLog
    from .services import pins, pruning

    profile_or_404(request)
    cfg = pruning.get_settings()
    form = inv_forms.PruningForm(request.POST or None, initial={"prune_live": cfg.prune_live, "prune_archive": cfg.prune_archive, "years": cfg.years_kept})
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "settings" and form.is_valid():
                d = form.cleaned_data
                pruning.configure(request.user, prune_live=d["prune_live"], prune_archive=d["prune_archive"], years=d["years"],
                                  full_archive_confirmed=d["archive_confirmed"])
                messages.success(request, "Saved. Pruning never runs outside the nightly job, after a good backup.")
            elif action == "repin":
                result = pins.pin_all()
                messages.success(request, f"{result['made']} pinned price(s) made from stored prices; {len(result['missing'])} could not be made yet. Nothing was invented.")
            return redirect(reverse("investments_admin_price_history"))
        except InvestmentsError as err:
            form.add_error(None, err.message)
    return page(request, "investments/price_history.html", {
        "page_title_text": "Price history", "form": form, "cfg": cfg, "preview": pruning.preview(), "pins": pins.summary(),
        "logs": PriceMaintenanceLog.objects.all()[:15], "rows": __import__("investments.models", fromlist=["Price"]).Price.objects.count()}, selectors=False)


@inv_admin
def price_archive(request):
    """Make the archive on request, stream it and delete it (never stored; plan 17.4). One zip, however large."""
    from django.http import FileResponse

    from .models import PriceHistorySettings, PriceMaintenanceLog
    from .services import archive

    profile_or_404(request)
    if request.method != "POST":
        raise Http404
    pruned = request.POST.get("version") == "pruned"
    try:
        with locks.heavy("price_archive"):
            paths = archive.build(pruned=pruned)
    except locks.Busy:
        messages.error(request, "Another large job is running. Try again in a minute.")
        return redirect(reverse("investments_admin_price_history"))
    path = paths[0]
    PriceHistorySettings.objects.update_or_create(pk=1, defaults={"last_archive_at": __import__("django.utils.timezone", fromlist=["now"]).now()})
    if not pruned:
        PriceHistorySettings.objects.filter(pk=1).update(full_archive_confirmed=False)       # the person still has to tick that they keep it
    PriceMaintenanceLog.objects.create(kind="archive", ok=True, size_bytes=path.stat().st_size, message=f"downloaded ({'pruned' if pruned else 'full'})")

    def stream():
        try:
            with open(path, "rb") as handle:
                while chunk := handle.read(1 << 16):
                    yield chunk
        finally:
            path.unlink(missing_ok=True)
            try:
                path.parent.rmdir()
            except OSError:
                pass

    response = FileResponse(stream(), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{path.name}"'
    return response
