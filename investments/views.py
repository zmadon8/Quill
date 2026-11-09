"""Investments views: landing, the empty shells for pages not built yet, the Dashboard, Getting started and small JSON helpers."""
import datetime
from decimal import Decimal

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.permissions import program_role
from accounts.suite import KEY_INVESTMENTS

from . import pages, scope
from .decorators import inv_admin, inv_editor, inv_reader
from .errors import InvestmentsError
from .services import core, fetch, masters, transactions as tx
from .services import dashboard as dashboard_service
from .viewutil import handle_errors, page, profile_or_404, selection


def landing(request):
    """/investments/ opens the Dashboard (or the first visible page if the Dashboard is hidden)."""
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    if program_role(request.user, KEY_INVESTMENTS) is None:
        raise PermissionDenied
    profile = scope.for_profile(request)
    hidden = pages.hidden_slugs(core.get_settings(profile, create=False)) if profile else set()
    for slug in ("dashboard", "holdings", "transactions", "settings"):
        if slug not in hidden:
            return redirect(reverse(pages.url_name(slug)))
    return redirect(reverse("investments_settings"))


def _shell(request, slug):
    spec = pages.BY_SLUG.get(slug)
    if spec is None:
        raise Http404
    scope.for_profile(request)
    return page(request, "investments/shell.html", {"page": spec, "page_title_text": spec.title})


def _make_shell(slug):
    spec = pages.BY_SLUG[slug]
    view = (lambda request: _shell(request, slug))
    view = inv_admin(inv_reader(view)) if spec.admin else inv_reader(view)
    view.__name__ = f"shell_{slug}"
    return view


SHELL_VIEWS = {spec.slug: _make_shell(spec.slug) for spec in pages.PAGES}


@inv_reader
def dashboard(request):
    profile = profile_or_404(request)
    portfolio, broker, asat = selection(request, profile)
    settings_row = core.get_settings(profile, create=False)
    from .viewutil import include_dividends

    div = include_dividends(request, profile)
    data = dashboard_service.load(profile, portfolio, broker, asat, div)
    awaiting = list(tx.awaiting_for(profile))
    overdue = [t for t in awaiting if tx.overdue(t, settings_row.awaiting_reminder_days)]
    chart = None
    if data["chart"]:
        from datetime import date as _date

        from .svgchart import line_chart

        chart = line_chart([_date.fromisoformat(d) for d in data["chart"]["days"]], data["chart"]["lines"], height=240)
    rows = data["rows"]
    stale = fetch.stale_ids([_Inst(r) for r in rows if r["price_source"] not in ("manual", "upload")])
    for r in rows:
        r["stale"] = r["id"] in stale
    return page(request, "investments/dashboard.html", {
        "page_title_text": "Dashboard", "rows": rows, "totals": data["totals"], "allocation": data["allocation"], "chart": chart, "notes": data["notes"],
        "awaiting": awaiting, "awaiting_total": sum((t.amount or Decimal(0) for t in awaiting if t.side == "buy"), Decimal(0)),
        "overdue": overdue, "unpriced": [r for r in rows if r["unpriced"]], "has_any": data["has_any"],
        "default_index": masters.default_index_for(profile), "sectoral": settings_row.sectoral_enabled, "include_div": div,
        "insights": _insights(profile), "all_insights": request.GET.get("insights") == "all",
        "pending_actions": __import__("investments.services.corporate", fromlist=["pending"]).pending(profile),
    })


class _Inst:
    """Just enough of an Instrument for ``fetch.stale_ids``."""

    def __init__(self, row):
        self.pk = row["id"]


@inv_reader
def start(request):
    profile = profile_or_404(request)
    from .models import Broker, Instrument, Transaction

    steps = [
        ("Add a broker or platform", Broker.objects.filter(profile=profile).exists(), reverse("investments_settings_brokers"),
         "Every purchase and sale records the broker it went through, such as a stockbroker, a fund platform, or 'Direct'."),
        ("Add an investment", Instrument.objects.filter(profile=profile).exists() or Transaction.objects.filter(profile=profile).exists()
         or _has_profile_investments(profile), reverse("investments_add_1"), "A share, a mutual fund, an alternative or a foreign investment. Importing a statement (Holdings > Transactions) can add them for you."),
        ("Record a purchase", Transaction.objects.filter(profile=profile).exists(), reverse("investments_txn_new_buy"),
         "Or import a statement from your broker or fund house (Holdings > Transactions > Import a statement), or enter an opening balance."),
        ("Enter a price", _has_prices(profile), reverse("investments_holdings"),
         "Prices are fetched every night and with Update Prices. For an investment without a price source, open it and type today's price."),
    ]
    return page(request, "investments/start.html", {"page_title_text": "Getting started", "steps": steps,
                                                    "all_done": all(done for _l, done, _u, _h in steps)})


def _has_profile_investments(profile):
    from .models import ProfileInvestment

    return ProfileInvestment.objects.filter(profile=profile).exists()


def _has_prices(profile):
    from .models import ManualPrice, ProfileInvestment

    ids = ProfileInvestment.objects.filter(profile=profile).values_list("instrument_id", flat=True)
    return ManualPrice.objects.filter(instrument_id__in=list(ids)).exists()


@inv_reader
@require_POST
def set_selection(request):
    """The portfolio / broker / as-at selectors (a plain GET form posts here so the choice is remembered)."""
    profile = profile_or_404(request)
    request.session[f"inv_sel_{profile.pk}"] = {
        "portfolio": request.POST.get("portfolio", ""), "broker": request.POST.get("broker", ""), "asat": request.POST.get("asat", "")}
    from .viewutil import safe_next

    return redirect(safe_next(request, reverse("investments_dashboard")))


@inv_reader
@require_POST
def set_money_mode(request):
    mode = request.POST.get("mode", "")
    try:
        masters.set_money_preference(request.user, mode)
    except InvestmentsError as err:
        return JsonResponse({"ok": False, "message": err.message}, status=400)
    return JsonResponse({"ok": True, "mode": mode})


@inv_editor
@handle_errors(json=True)
def available_units(request):
    """JSON for the sale form: the units held in each portfolio / broker / folio for an investment on a date."""
    from .models import Instrument

    profile = profile_or_404(request)
    inst = Instrument.objects.filter(pk=request.GET.get("instrument") or 0).first()
    if inst is None or inst.profile_id not in (None, profile.pk):
        return JsonResponse({"ok": True, "buckets": []})
    try:
        day = datetime.date.fromisoformat(request.GET.get("date", ""))
    except ValueError:
        day = datetime.date.today()
    exclude = request.GET.get("exclude")
    rows = tx.available_by_bucket(profile, inst, day, exclude_txn=int(exclude) if exclude and exclude.isdigit() else None)
    awaiting = sum((t.amount or Decimal(0) for t in tx.awaiting_for(profile) if t.instrument_id == inst.pk and t.side == "buy"), Decimal(0))
    return JsonResponse({"ok": True, "awaiting": str(awaiting), "buckets": [
        {"portfolio": p.pk if p else None, "portfolio_name": p.name if p else "", "broker": b.pk if b else None,
         "broker_name": b.name if b else "", "folio": f.pk if f else None, "folio_name": f.number if f else "", "units": str(u)}
        for p, b, f, u in rows]})


def _insights(profile):
    from .services import insights

    try:
        return insights.compute(profile)
    except Exception:  # an insight must never break the Dashboard
        import logging

        logging.getLogger(__name__).exception("Insights failed")
        return []
