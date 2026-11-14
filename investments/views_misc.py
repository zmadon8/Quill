"""Brokers, History and Settings pages."""
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse

from . import forms, pages
from .decorators import inv_admin, inv_editor, inv_read_write, inv_reader
from .errors import InvestmentsError
from .models import CORPORATE_AUTO_KINDS, Broker, Instrument, InvestmentHistory, Portfolio, ProfileInvestment, Transaction
from .services import core, corporate, dividends, history, holdings, instrument_search, masters
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
    return page(request, "investments/brokers.html", {"page_title_text": "Brokers", "rows": rows}, selectors=False, status_line=True)


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
    history.attach_portfolio_names(profile, rows)
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
    if request.method == "POST" and request.POST.get("action") == "lookup":
        if not request.user.is_admin:
            raise PermissionDenied
        instrument_search.set_lookup_enabled(request.POST.get("lookup_enabled") == "on")
        messages.success(request, "Saved. The lookup is now " + ("on." if instrument_search.lookup_enabled() else "off."))
        return redirect(reverse("investments_settings"))
    if request.method == "POST" and request.POST.get("action") == "refresh_lists":
        if not request.user.is_admin:
            raise PermissionDenied
        if not instrument_search.lookup_enabled():
            messages.error(request, "The lookup is switched off, so the lists are not downloaded. Switch it on first.")
        else:
            for label, count, error in instrument_search.refresh_now():
                if error:
                    messages.error(request, f"The {label} list could not be refreshed: {error}.")
                else:
                    messages.success(request, f"The {label} list is refreshed ({count} entries read).")
        return redirect(reverse("investments_settings"))
    row = core.get_settings(profile, create=False)
    initial = {f: getattr(row, f) for f in ("sip_mode", "awaiting_treatment", "awaiting_reminder_days", "corporate_action_mode",
                                            "long_term_days", "sectoral_enabled", "include_dividends", "alt_treatment")}
    initial["default_index"] = row.default_index
    for key, _label in CORPORATE_AUTO_KINDS:
        initial[f"auto_{key}"] = "auto" if (row.corporate_auto or {}).get(key) else "ask"
    form = forms.GeneralSettingsForm(request.POST or None, initial=initial)
    if request.method == "POST":
        if form.is_valid():
            d = {k: v for k, v in form.cleaned_data.items() if not k.startswith("auto_")}
            d["corporate_auto"] = form.corporate_auto(row.corporate_auto)
            try:
                masters.update_settings(profile, request.user, **d)
            except InvestmentsError as err:
                form.add_error(None, err.message)
            else:
                # Switching a kind on logs what is already waiting for it. The settings are saved by now, so a failure here is a warning, not an error.
                try:
                    corporate.apply_automatic(profile)
                    dividends.auto_log(profile)
                except InvestmentsError as err:
                    messages.warning(request, f"Settings saved, but some corporate actions could not be applied automatically: {err.message}")
                else:
                    messages.success(request, "Settings saved.")
                return redirect(reverse("investments_settings"))
    return page(request, "investments/settings_general.html", {
        "page_title_text": "Settings", "form": form, "lookup_on": instrument_search.lookup_enabled(),
        "list_status": instrument_search.status() if request.user.is_admin else None, "portfolios": Portfolio.objects.filter(profile=profile),
        "portfolio_form": forms.PortfolioForm()}, selectors=False)


@inv_editor
@handle_errors(fallback="investments_settings")
def portfolio_action(request):
    profile = profile_or_404(request)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add":
            masters.add_portfolio(profile, request.user, request.POST.get("name"))
        elif action == "rename":
            masters.rename_portfolio(profile, request.user, int(request.POST["id"]), request.POST.get("name"))
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


@inv_reader
def search_page(request):
    from django.http import JsonResponse

    from .services import search as search_service

    profile = profile_or_404(request)
    q = request.GET.get("q", "")
    results = search_service.search(profile, q)
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
                                                                 "column_picker": row.column_picker,
                                                                 "units_decimals": "" if row.units_decimals is None else str(row.units_decimals),
                                                                 "rupee_decimals": "" if row.rupee_decimals is None else str(row.rupee_decimals),
                                                                 "default_exchange": row.default_exchange,
                                                                 "my_money": masters.money_preference(request.user, profile)})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        masters.update_settings(profile, request.user, money_default=d["money_default"], compact_tables=d["compact_tables"], default_exchange=d["default_exchange"],
                              column_picker=d["column_picker"], units_decimals=d["units_decimals"], rupee_decimals=d["rupee_decimals"])
        masters.set_money_preference(request.user, d["my_money"])
        messages.success(request, "Saved.")
        return redirect(reverse("investments_settings_display"))
    from accounts.forms import MyInvestmentsForm

    return page(request, "investments/settings_simple.html", {"page_title_text": "Display", "form": form,
                                                             "period_form": MyInvestmentsForm(instance=request.user),
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


# ------------------------------------------------------------------ indices (owner round 2026-11)

@inv_reader
def settings_indices(request):
    from .services import indices

    profile = profile_or_404(request)
    settings_row = core.get_settings(profile, create=False)
    choices = list(Instrument.objects.filter(profile=None, kind="index").order_by("name"))
    mine = list(ProfileInvestment.objects.filter(profile=profile, instrument__kind__in=("share", "fund", "foreign"), hidden=False)
                .select_related("instrument", "sectoral_index").order_by("instrument__name"))
    return page(request, "investments/settings_indices.html", {
        "page_title_text": "Indices", "rows": indices.listing(profile), "suggested": [s for s in indices.SUGGESTED
                                                                                    if not Instrument.objects.filter(profile=None, code__iexact=s[1]).exists()],
        "choices": choices, "mine": mine, "sectoral_on": bool(settings_row and settings_row.sectoral_enabled)}, selectors=False)


@inv_editor
@handle_errors(fallback="investments_settings_indices")
def indices_action(request):
    from .services import indices

    profile = profile_or_404(request)
    back = reverse("investments_settings_indices")
    if request.method != "POST":
        return redirect(back)
    action = request.POST.get("action", "")
    if action == "add":
        inst, n = indices.add_index(request.user, request.POST.get("name"), request.POST.get("code"), request.POST.get("currency") or "INR")
        messages.success(request, f"{inst.name} added with {n} days of prices.")
    elif action == "delete":
        inst = Instrument.objects.filter(pk=request.POST.get("id") or 0, profile=None, kind="index").first()
        if inst is None:
            raise Http404
        if request.POST.get("confirm"):
            n = indices.delete_index(request.user, inst, request.POST.get("confirm_name"))
            messages.success(request, f"{inst.name} deleted" + (f"; {n} profile{'s' if n != 1 else ''} now use{'' if n != 1 else 's'} the standard choice instead." if n else "."))
        else:
            return page(request, "investments/index_delete.html", {"page_title_text": f"Delete {inst.name}", "inst": inst,
                                                                    "preview": indices.delete_preview(inst)}, selectors=False)
    elif action == "sectors":
        # One select per investment: the sector index each one is compared with.
        by_id = {i.pk: i for i in Instrument.objects.filter(profile=None, kind="index")}
        changed = 0
        for pi in ProfileInvestment.objects.filter(profile=profile).select_related("instrument"):
            key = f"sector_{pi.instrument_id}"
            if key not in request.POST:
                continue
            raw = request.POST.get(key) or ""
            index = by_id.get(int(raw)) if raw.isdigit() else None
            if (index.pk if index else None) != pi.sectoral_index_id:
                indices.set_sector_index(profile, request.user, pi.instrument, index)
                changed += 1
        messages.success(request, f"{changed} sector ind{'ex' if changed == 1 else 'ices'} changed.")
    else:
        raise Http404
    return redirect(back)


# ------------------------------------------------------------------ clear the transaction history (owner round 2026-11)

@inv_admin
def clear_history(request):
    """Settings > General > Clear transaction history (Admin): a preview, then the profile's name typed to confirm."""
    from .services import clear as clear_service

    profile = profile_or_404(request)
    rows, history_count = clear_service.preview(profile)
    if request.method == "POST":
        try:
            counts = clear_service.clear(profile, request.user, request.POST.get("confirm_name"), include_history=bool(request.POST.get("history")))
        except InvestmentsError as err:
            messages.error(request, err.message)
            return redirect(reverse("investments_clear_history"))
        messages.success(request, f"The transaction history of {profile.name} was cleared ({sum(counts.values())} records). "
                                  "A backup was taken first (kind: Before clearing profile).")
        return redirect(reverse("investments_settings"))
    return page(request, "investments/clear_history.html", {"page_title_text": "Clear transaction history", "rows": rows,
                                                            "total": sum(n for _l, n in rows), "history_count": history_count}, selectors=False)
