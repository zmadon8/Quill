"""Fee Register landing, Dashboard and the dashboard KPI endpoint (design section 5).

Thin views: they read through ``fees.services`` and hand the result to a template. No view bumps
``data_version``; the services do that when they write.
"""
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST, require_safe

from fees import scope
from fees.services import dashboard_panels
from fees.decorators import fees_editor, fees_reader, handle_fees_errors
from fees.pages import TAB_URL_NAMES, dashboard_on, json_ok, render_page
from fees.services import dashboard, memo_lists, prefs
from fees.services import settings as settings_service


def selected_kpis(config):
    """The KPI ids to show, in the saved order; every KPI when none is saved."""
    return dashboard.selected_kpi_ids(config)


def _kpi_rows(values, chosen):
    rows = []
    for kpi in chosen:
        value = values.get(kpi, 0)
        rows.append(
            {
                "id": kpi,
                "label": dashboard.KPI_LABELS[kpi],
                "value": value,
                "money": isinstance(value, str),
            }
        )
    return rows


@fees_reader
@require_safe
def landing(request):
    """``/fees/``: open the user's chosen first page (the ``default_tab`` setting)."""
    profile, settings = scope.context(request)
    tab = prefs.personal_default_tab(profile, request.user, settings) if profile is not None else ""
    if tab == "dashboard" and not dashboard_on(settings):
        tab = "memos"  # the Dashboard is switched off: open Memos instead of a page that is not there
    name = TAB_URL_NAMES.get(tab, "fees_memos")
    return redirect(name)


def _dashboard_off(request):
    """With the Dashboard switched off its address opens the person's first page instead (never a loop: the landing
    page does not send anyone to a switched-off Dashboard)."""
    _profile, settings = scope.context(request)
    return None if dashboard_on(settings) else redirect("fees_landing")


@fees_reader
@handle_fees_errors()
@require_safe
def dashboard_page(request):
    off = _dashboard_off(request)
    if off is not None:
        return off
    profile, _settings = scope.context(request)
    config = settings_service.get_settings(profile)
    kpis = dashboard.get_dashboard_kpis(profile, settings=config)
    chosen = selected_kpis(config)
    return render_page(
        request,
        "fees/dashboard.html",
        {
            "kpi_rows": _kpi_rows(kpis, chosen),
            "kpis_enabled": bool(config.get("dashboard_kpis_enabled", True)),
            "kpi_groups": [
                {
                    "title": title,
                    "items": [{"id": kpi, "label": dashboard.KPI_LABELS[kpi], "on": _tick_state(request, kpi, chosen)} for kpi in ids],
                }
                for title, ids in dashboard.KPI_DISPLAY_GROUPS
            ],
            "kpi_order": [
                {"id": kpi, "label": dashboard.KPI_LABELS[kpi], "first": i == 0, "last": i == len(chosen) - 1}
                for i, kpi in enumerate(chosen)
            ],
            "kpi_order_value": ",".join(chosen),
            "customise_open": request.GET.get("customise") == "1",
            "recent_matters": memo_lists.list_recent_matters(profile),
            "panels": dashboard_panels.get_panels(profile),
            "money_unit": config.get("money_unit", "full"),
        },
    )


def _tick_state(request, kpi, chosen):
    """Whether the Customise box for ``kpi`` is ticked: as saved, or all / none after the All and None buttons."""
    tick = request.GET.get("tick") if request.GET.get("customise") == "1" else None
    if tick in ("all", "none"):
        return tick == "all"
    return kpi in chosen


@fees_editor
@handle_fees_errors()
@require_POST
def save_kpis(request):
    """Save which boxes the Dashboard shows and in what order. Nothing ticked means all of them.

    The arrow buttons work without JavaScript: they submit the form with ``move=<id>:up|down``.
    """
    profile, _settings = scope.context(request)
    tick = request.POST.get("select")
    if tick in ("all", "none"):  # the All and None buttons: show the boxes again all ticked or all clear, save nothing
        return redirect(reverse("fees_dashboard") + "?customise=1&tick=" + tick + "#kpis")
    chosen = dashboard.order_kpis(
        request.POST.getlist("kpi"),
        [k for k in request.POST.get("order", "").split(",") if k],
        request.POST.get("move", ""),
    )
    settings_service.update_settings(profile, {"dashboard_kpis": ",".join(chosen)})
    if request.POST.get("move"):
        return redirect(reverse("fees_dashboard") + "?customise=1#kpis")
    messages.success(request, "Dashboard boxes saved.")
    return redirect("fees_dashboard")


@fees_reader
@handle_fees_errors(json=True)
@require_safe
def kpi_json(request):
    """JSON: every KPI and the saved selection."""
    profile, _settings = scope.context(request)
    config = settings_service.get_settings(profile)
    values = dashboard.get_dashboard_kpis(profile, settings=config)
    return json_ok({"kpis": values, "selected": selected_kpis(config), "enabled": bool(config["dashboard_kpis_enabled"])})


def kpis(request):
    """``dashboard/kpis/``: GET is the JSON for any role, POST saves the selection (Editor)."""
    if request.method == "POST":
        return save_kpis(request)
    return kpi_json(request)
