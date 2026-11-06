"""Fee Register landing, Dashboard and the dashboard KPI endpoint (design section 5).

Thin views: they read through ``fees.services`` and hand the result to a template. No view bumps
``data_version``; the services do that when they write.
"""
from django.contrib import messages
from django.shortcuts import redirect
from django.views.decorators.http import require_POST, require_safe

from fees import scope
from fees.decorators import fees_editor, fees_reader, handle_fees_errors
from fees.pages import TAB_URL_NAMES, json_ok, render_page
from fees.services import dashboard, memo_lists
from fees.services import settings as settings_service


def selected_kpis(config):
    """The KPI ids to show, in the saved order; every KPI when none is saved."""
    return dashboard.selected_kpi_ids(config)


def kpi_label(kpi):
    """A KPI id in words: ``billed_last30`` -> ``Billed, last 30 days``."""
    words = kpi.replace("_last30", ", last 30 days").replace("_this_month", ", this month").replace("_this_year", ", this year")
    words = words.replace("_", " ")
    return words[:1].upper() + words[1:]


def _kpi_rows(values, chosen):
    rows = []
    for kpi in chosen:
        value = values.get(kpi, 0)
        rows.append(
            {
                "id": kpi,
                "label": kpi_label(kpi),
                "value": value,
                "money": isinstance(value, str),
            }
        )
    return rows


@fees_reader
@require_safe
def landing(request):
    """``/fees/``: open the user's chosen first page (the ``default_tab`` setting)."""
    _profile, settings = scope.context(request)
    name = TAB_URL_NAMES.get(getattr(settings, "default_tab", ""), "fees_memos")
    return redirect(name)


@fees_reader
@handle_fees_errors()
@require_safe
def dashboard_page(request):
    profile, _settings = scope.context(request)
    config = settings_service.get_settings(profile)
    summary = dashboard.get_dashboard_summary(profile, settings=config)
    kpis = dashboard.get_dashboard_kpis(profile, settings=config)
    chosen = selected_kpis(config)
    return render_page(
        request,
        "fees/dashboard.html",
        {
            "summary": summary,
            "kpi_rows": _kpi_rows(kpis, chosen),
            "kpis_enabled": bool(config.get("dashboard_kpis_enabled", True)),
            "kpi_choices": [
                {"id": kpi, "label": kpi_label(kpi), "on": kpi in chosen}
                for kpi in dashboard.KPI_IDS
            ],
            "recent_matters": memo_lists.list_recent_matters(profile),
            "money_unit": config.get("money_unit", "full"),
        },
    )


@fees_editor
@handle_fees_errors()
@require_POST
def save_kpis(request):
    """Save which Overview figures the Dashboard shows. Nothing ticked means all of them."""
    profile, _settings = scope.context(request)
    ticked = set(request.POST.getlist("kpi"))
    chosen = [kpi for kpi in dashboard.KPI_IDS if kpi in ticked]
    settings_service.update_settings(profile, {"dashboard_kpis": ",".join(chosen)})
    messages.success(request, "Dashboard figures saved.")
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
