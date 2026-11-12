"""Holdings pages: the Investments list, adding an investment, and the page for one investment."""
from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse

from . import forms
from .decorators import inv_editor, inv_reader
from .errors import InvestmentsError
from .models import (
    KIND_ALTERNATIVE, AltValue, Folio, Instrument, InvestmentHistory, ManualPrice, Price, ProfileInvestment, Transaction,
    Transfer,
)
from .services import fetch, holdings, holdings_page, masters, prices
from .viewutil import handle_errors, page, profile_or_404, selection

KIND_LABELS = dict((k, v) for k, v in forms.KIND_CHOICES)


def _instrument_or_404(profile, pk):
    inst = Instrument.objects.filter(pk=pk).first()
    if inst is None or inst.profile_id not in (None, profile.pk):
        raise Http404
    return inst


def _sparks(instruments, as_of=None):
    """{instrument id: sparkline} of the last 90 days of closes (owner round 2026-11). Alternatives have no price feed: none."""
    from datetime import date as _date

    from .svgchart import sparkline

    ids = [i.pk for i in instruments if i.kind != KIND_ALTERNATIVE]
    closes = prices.recent_closes(ids, as_of or _date.today())
    return {iid: sparkline(vals) for iid, vals in closes.items()}


def _first_price_date(inst):
    from django.db.models import Min

    found = [Price.objects.filter(instrument=inst).aggregate(m=Min("date"))["m"],
             ManualPrice.objects.filter(instrument=inst).aggregate(m=Min("date"))["m"]]
    found = [d for d in found if d]
    return min(found) if found else None


@inv_reader
def holdings_list(request):
    profile = profile_or_404(request)
    portfolio, broker, asat = selection(request, profile)
    kind = request.GET.get("type", "")
    status = request.GET.get("status", "held")
    all_rows, held_count, sold_count = holdings_page.load(profile, portfolio, broker, asat)
    out = []
    for h in all_rows:
        if kind and h.instrument.kind != kind:
            continue
        if status == "held" and (not h.is_held or h.is_hidden):
            continue
        if status == "sold_out" and not h.sold_out:
            continue
        if status == "not_bought" and not h.empty:
            continue
        if status == "hidden" and not h.is_hidden:
            continue
        out.append(h)
    if request.GET.get("export") == "xlsx":
        from .exports import holdings_sheet, response

        return response("Holdings.xlsx", holdings_sheet(out))
    return page(request, "investments/holdings.html", {
        "page_title_text": "Investments", "rows": out, "held_count": held_count, "sold_count": sold_count, "kind": kind, "status": status, "holdings_filters": True,
        "kinds": [("", "All types"), ("share", "Share"), ("fund", "Mutual fund"), ("alternative", "Alternative"), ("foreign", "Foreign")],
        "status_choices": [("held", "Held"), ("sold_out", "Sold out"), ("not_bought", "Not bought yet"), ("hidden", "Hidden"), ("all", "All")],
    })


# ------------------------------------------------------------------ add investment (plan 6, "Adding an investment")

@inv_editor
def add_1(request):
    masters.ensure_default_portfolio(profile_or_404(request))
    return page(request, "investments/add_1.html", {"page_title_text": "Add investment", "kinds": [
        ("share", "Share or ETF", "An exchange-listed share. Type its code (for example RELIANCE.NS)."),
        ("fund", "Mutual fund", "Pick the exact plan and option; each has its own scheme code."),
        ("alternative", "Alternative investment", "Anything without a public price: a deposit, PPF, property, gold, unlisted shares."),
        ("foreign", "Foreign investment", "Priced in another currency; the rupee value is worked out with an exchange rate."),
    ]}, selectors=False)


@inv_editor
@handle_errors(fallback="investments_add_1")
def add_2(request):
    """Step 2 and 3: the details form, then a confirmation page showing what exists already before anything is saved."""
    profile = profile_or_404(request)
    kind = request.GET.get("kind") or request.POST.get("kind") or "share"
    if kind not in KIND_LABELS:
        kind = "share"
    initial = {"kind": kind, "asset_class": "equity" if kind != "alternative" else "other", "currency": "USD" if kind == "foreign" else "INR"}
    if request.method != "POST" and (request.GET.get("pick_code") or request.GET.get("pick_name")):
        initial.update({"name": request.GET.get("pick_name", ""), "code": request.GET.get("pick_code", ""), "isin": request.GET.get("pick_isin", "")})
    hits, search_error, query = [], "", request.GET.get("q", "").strip()
    if query and request.method != "POST":
        if kind == "fund":
            from .services import schemes

            hits = [{"code": s.code, "name": s.name, "isin": s.isin, "extra": f"NAV {s.nav} on {s.nav_date:%-d %b}" if s.nav and s.nav_date else ""}
                    for s in schemes.find(query)]
            if not hits:
                search_error = "No scheme matched. The scheme list comes from AMFI's daily file and is refreshed weekly; you can also type the scheme code."
        elif kind in ("share", "foreign"):
            from .adapters import yahoo
            from .adapters.base import FetchError

            try:
                hits = [{"code": h["symbol"], "name": h["name"], "isin": "", "extra": f"{h['exchange']} {h['type']}".strip()} for h in yahoo.search(query)]
            except FetchError as exc:
                search_error = f"The search could not be reached ({exc}). Type the code instead; the price check on the next step confirms it."
    if request.method == "POST":
        form = forms.InstrumentForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            similar = masters.find_similar(profile, data["name"], data["code"], data["kind"])
            if request.POST.get("confirmed"):
                try:
                    obj = masters.create_instrument(
                        profile, request.user, kind=data["kind"], name=data["name"], code=data["code"], isin=data["isin"],
                        currency=data["currency"], asset_class=data["asset_class"], sector=data["sector"],
                        interest_rate=data["interest_rate"], interest_type=data["interest_type"], maturity_date=data["maturity_date"],
                        allow_duplicate=bool(request.POST.get("allow_duplicate")))
                except InvestmentsError as err:
                    form.add_error(None, err.message)
                else:
                    return redirect(reverse("investments_added", args=[obj.pk]))
            else:
                check = _price_check(data)
                return page(request, "investments/add_confirm.html", {
                    "page_title_text": "Add investment: confirm", "form": form, "data": data, "similar": similar, "check": check,
                    "kind_label": KIND_LABELS.get(data["kind"]), "private": data["kind"] == KIND_ALTERNATIVE}, selectors=False)
    else:
        form = forms.InstrumentForm(initial=initial)
    return page(request, "investments/add_2.html", {"page_title_text": "Add investment: details", "form": form, "kind": kind,
                                                    "kind_label": KIND_LABELS.get(kind), "hits": hits, "search_error": search_error, "query": query}, selectors=False)


def _price_check(data):
    """Before saving, fetch the latest price so the person can confirm the name, exchange and price date (plan 6). Never required."""
    import datetime as _dt

    from .adapters.base import FetchError

    code = (data.get("code") or "").strip()
    if not code or data["kind"] == KIND_ALTERNATIVE:
        return None
    try:
        if data["kind"] == "fund":
            from .models import AmfiScheme

            s = AmfiScheme.objects.filter(code=code).first()
            if s:
                return {"ok": True, "name": s.name, "exchange": "AMFI", "price": s.nav, "date": s.nav_date}
            return {"ok": False, "message": "That scheme code is not in the AMFI list stored here yet. Check it, or save and the nightly job will try it."}
        from .adapters import yahoo

        result = yahoo.fetch(code, _dt.date.today() - _dt.timedelta(days=10))
        if not result.rows:
            return {"ok": False, "message": "No price data, check the code."}
        day, close = result.rows[-1]
        return {"ok": True, "name": result.name, "exchange": result.exchange, "price": close, "date": day, "currency": result.currency}
    except FetchError as exc:
        return {"ok": False, "message": f"No price data, check the code ({exc})."}


@inv_editor
def added(request, pk):
    profile = profile_or_404(request)
    inst = _instrument_or_404(profile, pk)
    return page(request, "investments/added.html", {"page_title_text": "Investment added", "inst": inst}, selectors=False)


# ------------------------------------------------------------------ one investment

def _links_text(links):
    return "\n".join(f"{l.get('label', '')} | {l.get('url', '')}" for l in links or [])


def _parse_links(text):
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        label, _sep, url = line.partition("|")
        if not _sep:
            label, url = line, line
        out.append({"label": label.strip(), "url": url.strip()})
    return out


@inv_reader
def investment(request, pk):
    from datetime import date as _date, timedelta as _td

    from .services import chartview, investment_page
    from .viewutil import include_dividends, parse_date

    profile = profile_or_404(request)
    inst = _instrument_or_404(profile, pk)
    portfolio, broker, asat = selection(request, profile)
    on = parse_date(request.GET.get("on"))
    if on and on > _date.today():
        on = None
    as_of = on or asat or _date.today()
    div = include_dividends(request, profile)
    rows, _t = holdings.compute(profile, portfolio=portfolio, broker=broker, as_of=as_of, instrument_ids=[inst.pk], include_dividends=div)
    range_key, range_days = chartview.choose(request, "1y")
    if range_days is None:
        chart_start = _first_price_date(inst) or (as_of - _td(days=365))
    else:
        chart_start = as_of - _td(days=range_days)
    h = rows[0] if rows else holdings.Holding(instrument=inst, empty=True)
    pi = masters.get_profile_investment(profile, inst) if request.user.is_authenticated and inst.pk else None
    txns = Transaction.objects.filter(profile=profile, instrument=inst).select_related("broker", "portfolio", "folio").order_by("-date", "-id")
    if request.GET.get("export") == "xlsx":
        from .exports import response, safe_file_name, transaction_sheets
        from .models import Dividend

        return response(safe_file_name(inst.name, "transactions"), transaction_sheets(
            txns.select_related("instrument"),
            Transfer.objects.filter(profile=profile, instrument=inst).select_related(
                "instrument", "from_broker", "to_broker", "from_portfolio", "to_portfolio", "from_folio", "to_folio").order_by("-date", "-id"),
            Dividend.objects.filter(profile=profile, instrument=inst).select_related("instrument", "portfolio", "broker", "folio").order_by("-date", "-id")))
    transfers = Transfer.objects.filter(profile=profile, instrument=inst).select_related(
        "from_broker", "to_broker", "from_portfolio", "to_portfolio", "from_folio", "to_folio")
    portfolios = {p.pk: p.name for p in profile_portfolios(profile)}
    brokers = {b.pk: b.name for b in profile_brokers(profile)}
    folios_qs = list(Folio.objects.filter(profile=profile, instrument=inst).select_related("portfolio"))
    folio_units = {}
    for (pf, br, fo), units in h.buckets.items():
        folio_units[fo] = folio_units.get(fo, Decimal(0)) + units
    bucket_rows = sorted(((portfolios.get(pf, "?"), brokers.get(br, "?"), next((f.number for f in folios_qs if f.pk == fo), ""), units)
                          for (pf, br, fo), units in h.buckets.items()), key=lambda r: (r[0], r[1], r[2]))
    counts = masters.records_of(profile, inst)
    # One chart at a time, and only that one is worked out.
    chart_kind = chartview.chart_choice(request, has_price=inst.kind != KIND_ALTERNATIVE)
    price_chart = value_chart = None
    if chart_kind == "price":
        index = pi.sectoral_index if pi and pi.sectoral_index_id else masters.default_index_for(profile)
        price_chart = investment_page.price_chart(profile, inst, chart_start, as_of, index=index if index and index.pk != inst.pk else None)
    else:
        value_chart = chartview.value_chart(
            profile, range_days, as_of, index=masters.default_index_for(profile), portfolio=portfolio, broker=broker, instrument_ids=[inst.pk],
            markers=chartview.markers_for(profile, inst, as_of - _td(days=range_days or 36500), as_of))
    # Iterating ``txns`` here loaded every transaction of the investment, and the page then queried the newest 200 again: ask for the awaiting
    # ones on their own (there are few) and let the page list read the newest 200 once.
    awaiting_rows = list(txns.filter(status="awaiting"))
    context = {
        "page_title_text": inst.name, "inst": inst, "h": h, "pi": pi, "txns": txns[:200], "transfers": transfers, "folios": folios_qs,
        "folio_units": [(f, folio_units.get(f.pk, Decimal(0))) for f in folios_qs], "no_folio_units": folio_units.get(None, Decimal(0)),
        "bucket_rows": bucket_rows, "counts": counts, "has_records": any(counts.values()),
        "price_form": forms.PriceForm(), "alt_form": forms.AltValueForm(), "folio_form": forms.FolioForm(profile=profile),
        "details_form": _details_draft(request, inst) or forms.DetailsForm(initial={"notes": pi.notes if pi else "", "links": _links_text(pi.links if pi else []),
                                                   "sectoral_index": pi.sectoral_index_id if pi else None,
                                                   "interest_rate": inst.interest_rate, "interest_type": inst.interest_type,
                                                   "maturity_date": inst.maturity_date}, with_sector=inst.kind != KIND_ALTERNATIVE),
        "manual_prices": ManualPrice.objects.filter(instrument=inst).order_by("-date")[:10],
        "alt_values": AltValue.objects.filter(profile=profile, instrument=inst).order_by("-date")[:20] if inst.kind == KIND_ALTERNATIVE else [],
        "awaiting_rows": awaiting_rows, "history": InvestmentHistory.objects.filter(profile=profile, instrument_id_ref=inst.pk)[:8],
        "kind_label": inst.get_kind_display(), "on": on, "as_of": as_of, "include_div": div,
        "chart": price_chart, "chart_kind": chart_kind, "chart_links": chartview.chart_links(request, chart_kind),
        "price_ranges": chartview.links(request, range_key, "#price"),
        "value_chart": value_chart,
        "value_ranges": chartview.links(request, range_key, "#value-chart"),
        "div_href": chartview.toggled_href(request, "div", "0" if div else "1"),
        "keep_params": [(k, request.GET[k]) for k in ("chart", "range") if request.GET.get(k)],
        "range52": investment_page.range_52w(inst, as_of) if inst.kind != KIND_ALTERNATIVE else (None, None),
        "guardrails": investment_page.guardrails(profile, inst),
        "foreign": investment_page.foreign_figures(profile, inst, h, as_of) if inst.currency != "INR" else None,
        "sips": investment_page.sip_schedules(profile, inst) if inst.kind == "fund" else [],
        "sip_form": forms.SipForm(profile=profile, initial={"start_date": _date.today(), "day_of_month": 5}) if inst.kind == "fund" else None,
        "purchase": _with_portfolio_names(investment_page.purchase_rows(profile, inst, h, as_of), portfolios),
        "is_private": inst.profile_id is not None,
        "dividends": __import__("investments.models", fromlist=["Dividend"]).Dividend.objects.filter(profile=profile, instrument=inst).select_related("broker")[:50],
        "actions": [a for a in __import__("investments.services.corporate", fromlist=["for_profile"]).for_profile(profile) if a.instrument_id == inst.pk],
        "can_refresh": inst.kind != KIND_ALTERNATIVE and bool(fetch.tracked_instruments(profile, ids=[inst.pk])),
        "can_delete": (not any(counts.values())) or getattr(request.user, "is_admin", False),
    }
    if inst.profile_id is None and inst.kind != KIND_ALTERNATIVE:
        # The shared price history with the Editor's tools (owner round 2026-11), the same block as on the catalogue page.
        from .views_catalogue import price_history_context

        context.update(price_history_context(request, inst, prefix="p", profile=profile))
    return page(request, "investments/investment.html", context)


def _with_portfolio_names(purchase, portfolios):
    """Each held lot and sold portion gets its portfolio's name (a bucket is ``(portfolio, broker, folio)``), blank when unknown."""
    held, sold = purchase
    for row in held:
        row["portfolio"] = portfolios.get(row["lot"].bucket[0], "") if row["lot"].bucket else ""
    for row in sold:
        row["portfolio"] = portfolios.get(row["m"].bucket[0], "") if row["m"].bucket else ""
    return held, sold


def profile_portfolios(profile):
    from .models import Portfolio

    return Portfolio.objects.filter(profile=profile)


def profile_brokers(profile):
    from .models import Broker

    return Broker.objects.filter(profile=profile)


def _details_draft(request, inst):
    """The Your details form re-shown with the values that were typed, after the last save was refused (kept in the session for one page)."""
    draft = request.session.pop("details_draft", None)
    if not draft or draft.get("pk") != inst.pk:
        return None
    form = forms.DetailsForm(draft["data"], with_sector=inst.kind != KIND_ALTERNATIVE)
    form.is_valid()
    return form


def _form_errors(request, form):
    for field, errs in form.errors.items():
        for e in errs:
            messages.error(request, e if field == "__all__" else f"{form.fields[field].label or field}: {e}")


@inv_editor
@handle_errors()
def investment_price(request, pk):
    profile = profile_or_404(request)
    inst = _instrument_or_404(profile, pk)
    form = forms.PriceForm(request.POST)
    if form.is_valid():
        prices.set_manual_price(profile, request.user, inst, form.cleaned_data["date"], form.cleaned_data["close"], form.cleaned_data["note"])
        messages.success(request, "Price saved.")
    else:
        _form_errors(request, form)
    return redirect(reverse("investments_investment", args=[pk]))


@inv_editor
@handle_errors()
def investment_price_delete(request, pk, price_id):
    profile = profile_or_404(request)
    _instrument_or_404(profile, pk)
    prices.delete_manual_price(profile, request.user, price_id)
    messages.success(request, "Price deleted.")
    return redirect(reverse("investments_investment", args=[pk]))


@inv_editor
@handle_errors()
def investment_altvalue(request, pk):
    profile = profile_or_404(request)
    inst = _instrument_or_404(profile, pk)
    if request.POST.get("delete"):
        prices.delete_alt_value(profile, request.user, int(request.POST["delete"]))
        messages.success(request, "Value deleted.")
    else:
        form = forms.AltValueForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            prices.set_alt_value(profile, request.user, inst, d["date"], d["total_value"], d["nav"], d["note"])
            messages.success(request, "Value saved.")
        else:
            _form_errors(request, form)
    return redirect(reverse("investments_investment", args=[pk]))


@inv_editor
@handle_errors()
def investment_folio(request, pk):
    profile = profile_or_404(request)
    inst = _instrument_or_404(profile, pk)
    if request.POST.get("delete"):
        masters.delete_folio(profile, request.user, int(request.POST["delete"]))
        messages.success(request, "Folio deleted.")
        return redirect(reverse("investments_investment", args=[pk]))
    form = forms.FolioForm(request.POST, profile=profile)
    if form.is_valid():
        d = form.cleaned_data
        try:
            masters.add_folio(profile, request.user, instrument=inst, portfolio=d["portfolio"], number=d["number"], notes=d["notes"],
                              confirm_new=d["confirm_new"])
            messages.success(request, "Folio added.")
        except InvestmentsError as err:
            if err.code == "SIMILAR_FOLIO":
                messages.warning(request, err.message + " If it is a different folio, tick 'Yes, it is different' and save again.")
                return page(request, "investments/folio_confirm.html", {"page_title_text": "Folio number", "inst": inst, "form": form, "err": err},
                            selectors=False)
            raise
    else:
        _form_errors(request, form)
    return redirect(reverse("investments_investment", args=[pk]))


@inv_editor
@handle_errors()
def investment_details(request, pk):
    profile = profile_or_404(request)
    inst = _instrument_or_404(profile, pk)
    action = request.POST.get("action", "save")
    if action == "hide":
        masters.update_profile_details(profile, request.user, inst, hidden=True)
        messages.success(request, "Hidden. It stays in reports and history; show it again from Investments > Status > Hidden.")
    elif action == "show":
        masters.update_profile_details(profile, request.user, inst, hidden=False)
    else:
        form = forms.DetailsForm(request.POST, with_sector=inst.kind != KIND_ALTERNATIVE)
        if form.is_valid():
            with transaction.atomic():
                if "interest_type" in form.fields:  # checked first, so a refused rate saves nothing
                    masters.update_alt_interest(profile, request.user, inst, interest_rate=form.cleaned_data["interest_rate"],
                                                interest_type=form.cleaned_data["interest_type"], maturity_date=form.cleaned_data["maturity_date"])
                masters.update_profile_details(profile, request.user, inst, notes=form.cleaned_data["notes"],
                                               links=_parse_links(form.cleaned_data["links"]))
                if "sectoral_index" in form.fields:
                    from .services import indices

                    chosen = form.cleaned_data.get("sectoral_index")
                    pi = masters.get_profile_investment(profile, inst)
                    if (chosen.pk if chosen else None) != pi.sectoral_index_id:
                        indices.set_sector_index(profile, request.user, inst, chosen)
            messages.success(request, "Details saved.")
        else:
            _form_errors(request, form)
            request.session["details_draft"] = {"pk": inst.pk, "data": {k: v for k, v in request.POST.items() if k != "csrfmiddlewaretoken"}}
            return redirect(reverse("investments_investment", args=[pk]))
    return redirect(reverse("investments_investment", args=[pk]))


@inv_editor
@handle_errors()
def investment_shared(request, pk):
    """Admin only: change the shared details of an investment."""
    profile = profile_or_404(request)
    inst = _instrument_or_404(profile, pk)
    allowed = {k: request.POST.get(k, "").strip() for k in ("name", "code", "isin", "sector", "currency") if k in request.POST}
    if "name" in allowed and not allowed["name"]:
        raise InvestmentsError("REQUIRED", "Name is required.")
    masters.update_shared_details(profile, request.user, inst, **allowed)
    messages.success(request, "Shared details saved.")
    return redirect(reverse("investments_investment", args=[pk]))


@inv_editor
@handle_errors()
def inv_delete(request, pk):
    profile = profile_or_404(request)
    inst = _instrument_or_404(profile, pk)
    counts = masters.records_of(profile, inst)
    form = forms.DeleteInstrumentForm(request.POST or None)
    other_profiles = (ProfileInvestment.objects.filter(instrument=inst).exclude(profile=profile).exists() if inst.profile_id is None else False)
    if request.method == "POST":
        try:
            masters.delete_instrument(profile, request.user, inst, confirm_name=request.POST.get("confirm_name"))
        except InvestmentsError as err:
            if err.code in ("CONFIRM_NAME", "FORBIDDEN"):
                messages.error(request, err.message)
            else:
                raise
        else:
            messages.success(request, f"{inst.name} deleted.")
            return redirect(reverse("investments_holdings"))
    return page(request, "investments/inv_delete.html", {
        "page_title_text": "Delete investment", "inst": inst, "counts": counts, "has_records": any(counts.values()), "form": form,
        "other_profiles": other_profiles, "is_admin": getattr(request.user, "is_admin", False)}, selectors=False)


@inv_editor
@handle_errors()
def investment_sip(request, pk):
    from .services import sip

    profile = profile_or_404(request)
    inst = _instrument_or_404(profile, pk)
    if request.method == "POST":
        if request.POST.get("toggle"):
            sip.set_active(profile, int(request.POST["toggle"]), request.POST.get("active") == "1")
        else:
            form = forms.SipForm(request.POST, profile=profile)
            if form.is_valid():
                sip.add(profile, request.user, instrument=inst, **form.cleaned_data)
                messages.success(request, "SIP saved. Each month's entry is made by the nightly job once that day's NAV is stored.")
            else:
                _form_errors(request, form)
    return redirect(reverse("investments_investment", args=[pk]))
