"""Brokers, History and Settings pages."""
from decimal import Decimal

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse

from . import forms, pages
from .decorators import inv_editor, inv_read_write, inv_reader
from .errors import InvestmentsError
from .models import Broker, InvestmentHistory, Portfolio, Transaction
from .services import core, history, holdings, masters
from .viewutil import handle_errors, page, profile_or_404, selection

# ------------------------------------------------------------------ brokers


@inv_reader
def brokers_list(request):
    profile = profile_or_404(request)
    rows = []
    for b in Broker.objects.filter(profile=profile):
        h, totals = holdings.compute(profile, broker=b.pk)
        rows.append({"broker": b, "count": totals.count, "value": totals.value, "invested": totals.invested, "xirr": totals.xirr,
                     "txns": Transaction.objects.filter(profile=profile, broker=b).count()})
    return page(request, "investments/brokers.html", {"page_title_text": "Brokers", "rows": rows})


@inv_reader
def broker_detail(request, pk):
    profile = profile_or_404(request)
    broker = Broker.objects.filter(pk=pk, profile=profile).first()
    if broker is None:
        raise Http404
    portfolio, _b, asat = selection(request, profile)
    rows, totals = holdings.compute(profile, portfolio=portfolio, broker=broker.pk, as_of=asat)
    txns = Transaction.objects.filter(profile=profile, broker=broker).select_related("instrument", "portfolio")[:50]
    return page(request, "investments/broker_detail.html", {"page_title_text": broker.name, "broker": broker, "rows": holdings.held(rows),
                                                           "totals": totals, "txns": txns}, selectors=False)


# ------------------------------------------------------------------ history


def _describe(row):
    return row.summary or f"{row.get_change_kind_display()} {history.TYPE_LABELS.get(row.record_type, row.record_type)}"


@inv_reader
def history_list(request):
    profile = profile_or_404(request)
    instrument = request.GET.get("instrument") or None
    record_type = request.GET.get("type") or None
    rows = []
    for row in history.rows_for(profile, instrument_id=instrument, record_type=record_type, limit=300):
        row.description = _describe(row)
        row.can_restore = history.can_restore(profile, row)
        older = InvestmentHistory.objects.filter(profile=profile, record_type=row.record_type, record_id=row.record_id,
                                                 version=row.version - 1).first()
        row.changes = [c for c in history.diff(older.snapshot if older else {}, row.snapshot)
                       if c[0] not in ("version", "created_at", "id")][:12] if row.change_kind in ("edit", "complete") else []
        rows.append(row)
    from .models import Instrument

    names = dict(Instrument.objects.filter(pk__in=[r.instrument_id_ref for r in rows if r.instrument_id_ref]).values_list("pk", "name"))
    for r in rows:
        r.instrument_name = names.get(r.instrument_id_ref, "")
    return page(request, "investments/history.html", {"page_title_text": "History", "rows": rows, "type_labels": history.TYPE_LABELS,
                                                      "instrument": instrument, "record_type": record_type}, selectors=False)


@inv_editor
@handle_errors(fallback="investments_history")
def history_restore(request, pk):
    profile = profile_or_404(request)
    if request.method == "POST":
        try:
            history.restore(profile, request.user, pk)
        except InvestmentsError as err:
            if err.code == "WOULD_GO_NEGATIVE":
                from .views_txn import _refused

                return _refused(request, err, reverse("investments_history"))
            raise
        messages.success(request, "Restored.")
    return redirect(reverse("investments_history"))


# ------------------------------------------------------------------ settings


@inv_read_write
def settings_general(request):
    profile = profile_or_404(request)
    row = core.get_settings(profile, create=False)
    initial = {f: getattr(row, f) for f in ("sip_mode", "awaiting_treatment", "awaiting_reminder_days", "corporate_action_mode",
                                            "long_term_days", "sectoral_enabled", "include_dividends", "alt_treatment", "money_default")}
    initial["default_index"] = row.default_index
    form = forms.GeneralSettingsForm(request.POST or None, initial=initial)
    if request.method == "POST":
        if form.is_valid():
            d = form.cleaned_data
            try:
                masters.update_settings(profile, request.user, **d)
            except InvestmentsError as err:
                form.add_error(None, err.message)
            else:
                messages.success(request, "Settings saved.")
                return redirect(reverse("investments_settings"))
    return page(request, "investments/settings_general.html", {
        "page_title_text": "Settings", "form": form, "portfolios": Portfolio.objects.filter(profile=profile),
        "portfolio_form": forms.PortfolioForm()}, selectors=False)


@inv_editor
@handle_errors(fallback="investments_settings")
def portfolio_action(request):
    profile = profile_or_404(request)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add":
            masters.add_portfolio(profile, request.user, request.POST.get("name"), request.POST.get("owner_name", ""))
        elif action == "rename":
            masters.rename_portfolio(profile, request.user, int(request.POST["id"]), request.POST.get("name"), request.POST.get("owner_name", ""))
        elif action == "delete":
            masters.delete_portfolio(profile, request.user, int(request.POST["id"]))
        messages.success(request, "Saved.")
    return redirect(reverse("investments_settings"))


@inv_reader
def settings_brokers(request):
    profile = profile_or_404(request)
    row = core.get_settings(profile, create=False)
    defaults = forms.DefaultBrokersForm(profile=profile, initial={f"default_broker_{k}": getattr(row, f"default_broker_{k}")
                                                                   for k in ("share", "fund", "alternative", "foreign")})
    brokers = list(Broker.objects.filter(profile=profile))
    used = {b.pk: Transaction.objects.filter(broker=b).exists() for b in brokers}
    for b in brokers:
        b.in_use = used[b.pk]
    return page(request, "investments/settings_brokers.html", {"page_title_text": "Brokers", "brokers": brokers, "defaults": defaults},
                selectors=False)


@inv_editor
@handle_errors(fallback="investments_settings_brokers")
def broker_action(request):
    profile = profile_or_404(request)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add":
            masters.add_broker(profile, request.user, request.POST.get("name"))
        elif action == "rename":
            masters.rename_broker(profile, request.user, int(request.POST["id"]), request.POST.get("name"))
        elif action in ("hide", "show"):
            masters.set_broker_hidden(profile, request.user, int(request.POST["id"]), action == "hide")
        elif action == "delete":
            masters.delete_broker(profile, request.user, int(request.POST["id"]))
        elif action == "defaults":
            form = forms.DefaultBrokersForm(request.POST, profile=profile)
            if form.is_valid():
                masters.update_settings(profile, request.user, **form.cleaned_data)
        messages.success(request, "Saved.")
    return redirect(reverse("investments_settings_brokers"))


@inv_read_write
def settings_pages(request):
    profile = profile_or_404(request)
    row = core.get_settings(profile, create=False)
    hideable = [p for p in pages.PAGES if p.hideable and not p.admin]
    if request.method == "POST":
        shown = set(request.POST.getlist("shown"))
        hidden = [p.slug for p in hideable if p.slug not in shown]
        masters.update_settings(profile, request.user, hidden_pages=hidden)
        messages.success(request, "Menu saved. Hidden pages are still recorded, calculated and backed up.")
        return redirect(reverse("investments_settings_pages"))
    hidden = set(row.hidden_pages or [])
    # Only top-level pages (the first of each menu entry or second-row link) are offered; steps and shells of those are not.
    top_slugs = [first for _l, first in sum((list(v) for v in pages.SUB_ROWS.values()), [])] + ["dashboard", "alerts"]
    choices = [(p, p.slug not in hidden) for p in hideable if p.slug in top_slugs]
    return page(request, "investments/settings_pages.html", {"page_title_text": "Pages", "choices": choices}, selectors=False)


@inv_reader
def search_page(request):
    from django.http import JsonResponse

    from .services import search as search_service

    profile = profile_or_404(request)
    q = request.GET.get("q", "")
    hidden = pages.hidden_slugs(core.get_settings(profile, create=False))
    results = search_service.search(profile, q, hidden=hidden)
    for r in results:
        name, arg = r["url"]
        if name == "page":
            r["href"] = reverse(pages.url_name(arg))
        elif name == "transactions":
            r["href"] = reverse("investments_transactions") + f"?highlight={arg}#txn-{arg}"
        else:
            r["href"] = reverse(f"investments_{name}", args=[arg])
        del r["url"]
    if request.GET.get("format") == "json":
        return JsonResponse({"results": results})
    groups = {}
    for r in results:
        groups.setdefault(r["kind"], []).append(r)
    return page(request, "investments/search.html", {"page_title_text": "Search", "query": q, "groups": groups, "too_short": 0 < len(q.strip()) < 2},
                selectors=False)


@inv_read_write
def settings_display(request):
    profile = profile_or_404(request)
    row = core.get_settings(profile, create=False)
    from . import forms as f

    form = f.DisplaySettingsForm(request.POST or None, initial={"money_default": row.money_default, "compact_tables": row.compact_tables,
                                                                 "default_exchange": row.default_exchange,
                                                                 "my_money": masters.money_preference(request.user, profile)})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        masters.update_settings(profile, request.user, money_default=d["money_default"], compact_tables=d["compact_tables"], default_exchange=d["default_exchange"])
        masters.set_money_preference(request.user, d["my_money"])
        messages.success(request, "Saved.")
        return redirect(reverse("investments_settings_display"))
    return page(request, "investments/settings_simple.html", {"page_title_text": "Display", "form": form,
                                                             "intro": "How amounts are shown. Excel exports always contain the exact figures."}, selectors=False)


@inv_read_write
def settings_insights(request):
    from .services import insights

    profile = profile_or_404(request)
    row = core.get_settings(profile, create=False)
    if request.method == "POST":
        on = set(request.POST.getlist("on"))
        try:
            limit = Decimal(request.POST.get("limit", row.concentration_limit))
        except Exception:
            limit = row.concentration_limit
        masters.update_settings(profile, request.user, insights_off=[k for k, _l in insights.KINDS if k not in on], concentration_limit=limit)
        from .models import AlertState

        if request.POST.get("reset"):
            AlertState.objects.filter(profile=profile, key__startswith=insights.DISMISS_PREFIX).delete()
        messages.success(request, "Saved.")
        return redirect(reverse("investments_settings_insights"))
    off = set(row.insights_off or [])
    return page(request, "investments/settings_insights.html", {"page_title_text": "Insights", "kinds": [(k, l, k not in off) for k, l in insights.KINDS],
                                                               "limit": row.concentration_limit}, selectors=False)
