"""Fee Register landing, Dashboard and the dashboard KPI endpoint (design section 5).

Thin views: they read through ``fees.services`` and hand the result to a template. No view bumps
``data_version``; the services do that when they write.
"""
from django.shortcuts import redirect

from fees import scope
from fees.decorators import fees_reader, handle_fees_errors
from fees.pages import TAB_URL_NAMES, json_ok, render_page
from fees.services import dashboard, memo_lists
from fees.services import settings as settings_service


def selected_kpis(config):
    """The KPI ids to show, in the saved order; every KPI when none is saved."""
    chosen = [k.strip() for k in str(config.get("dashboard_kpis") or "").split(",")]
    chosen = [k for k in chosen if k in dashboard.KPI_IDS]
    return chosen or list(dashboard.KPI_IDS)


def _kpi_rows(values, chosen):
    rows = []
    for kpi in chosen:
        value = values.get(kpi, 0)
        rows.append(
            {
                "id": kpi,
                "label": kpi.replace("_", " ").capitalize(),
                "value": value,
                "money": isinstance(value, str),
            }
        )
    return rows


@fees_reader
def landing(request):
    """``/fees/``: open the user's chosen first page (the ``default_tab`` setting)."""
    _profile, settings = scope.context(request)
    name = TAB_URL_NAMES.get(getattr(settings, "default_tab", ""), "fees_memos")
    return redirect(name)


@fees_reader
@handle_fees_errors()
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
            "kpi_ids": dashboard.KPI_IDS,
            "chosen_kpis": chosen,
            "recent_matters": memo_lists.list_recent_matters(profile),
            "money_unit": config.get("money_unit", "full"),
        },
    )


@fees_reader
@handle_fees_errors(json=True)
def kpis(request):
    """JSON: every KPI and the saved selection. (Saving the selection is a POST, added with the write views.)"""
    profile, _settings = scope.context(request)
    config = settings_service.get_settings(profile)
    values = dashboard.get_dashboard_kpis(profile, settings=config)
    return json_ok({"kpis": values, "selected": selected_kpis(config), "enabled": bool(config["dashboard_kpis_enabled"])})
