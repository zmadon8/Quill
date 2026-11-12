"""Transaction pages: the list, buy / sell / awaiting / opening balance / transfer / switch forms, edit, delete, complete."""
import datetime
import json
from decimal import Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse

from . import forms
from .decorators import inv_editor, inv_reader
from .errors import InvestmentsError
from .models import (
    ORIGIN_PURCHASE, ORIGINS, SIDE_BUY, SIDE_SELL, STATUS_AWAITING, STATUS_FINAL, STATUS_PENDING_SIP, Folio, Instrument, Transaction, Transfer,
)
from .services import core, masters, transactions as tx
from .viewutil import handle_errors, page, profile_or_404, selection

PAGE_SIZE = 50


def _refused(request, err, back):
    """The 'An edit that is refused' page: what the change would break, with a link to each conflicting later entry."""
    conflicts = []
    for item in err.details.get("conflicts", []):
        if item["kind"] == "txn" and item["id"]:
            url = reverse("investments_txn_edit", args=[item["id"]])
        else:
            url = ""
        conflicts.append({**item, "url": url})
    return page(request, "investments/txn_refused.html", {
        "page_title_text": "This change is refused", "message": err.message, "conflicts": conflicts, "back": back}, status=409,
        selectors=False)


def _txn_row(t):
    t.tags = []
    if t.is_opening:
        t.tags.append(("Opening", ""))
    if t.origin != ORIGIN_PURCHASE:
        t.tags.append((t.get_origin_display(), ""))
    if t.is_estimated:
        t.tags.append(("Estimated date", "amb"))
    if t.status == STATUS_AWAITING:
        t.tags.append(("Awaiting allotment", "amb"))
    if t.status == STATUS_PENDING_SIP:
        t.tags.append(("SIP, to confirm", "amb"))
    if t.switch_id:
        t.tags.append(("Switch", ""))
    if t.status == STATUS_FINAL and t.units is not None:
        t.total = core.buy_total(t) if t.side == SIDE_BUY else core.sell_total(t)
    else:
        t.total = t.amount
    return t


@inv_reader
def transactions_list(request):
    profile = profile_or_404(request)
    portfolio, broker, asat = selection(request, profile)
    q = request.GET.get("q", "").strip()
    side = request.GET.get("side", "")
    qs = Transaction.objects.filter(profile=profile).select_related("instrument", "portfolio", "broker", "folio")
    if portfolio:
        qs = qs.filter(portfolio_id=portfolio)
    if broker:
        qs = qs.filter(broker_id=broker)
    if asat:
        qs = qs.filter(date__lte=asat)
    if q:
        qs = qs.filter(Q(instrument__name__icontains=q) | Q(instrument__code__icontains=q) | Q(reference__icontains=q) |
                       Q(folio__number__icontains=q) | Q(note__icontains=q))
    if side in (SIDE_BUY, SIDE_SELL):
        qs = qs.filter(side=side)
    if request.GET.get("export") == "xlsx":
        from .exports import response, transaction_sheets
        from .models import Dividend

        transfers = Transfer.objects.filter(profile=profile).select_related(
            "instrument", "from_broker", "to_broker", "from_portfolio", "to_portfolio", "from_folio", "to_folio")
        dividends = Dividend.objects.filter(profile=profile).select_related("instrument", "portfolio", "broker", "folio")
        # Search and the portfolio / broker selectors narrow all three sheets (a transfer matches on either side); the buy / sell
        # filter only means something for transactions.
        if q:
            transfers = transfers.filter(Q(instrument__name__icontains=q) | Q(instrument__code__icontains=q))
            dividends = dividends.filter(Q(instrument__name__icontains=q) | Q(instrument__code__icontains=q))
        if portfolio:
            transfers = transfers.filter(Q(from_portfolio_id=portfolio) | Q(to_portfolio_id=portfolio))
            dividends = dividends.filter(portfolio_id=portfolio)
        if broker:
            transfers = transfers.filter(Q(from_broker_id=broker) | Q(to_broker_id=broker))
            dividends = dividends.filter(broker_id=broker)
        if asat:
            transfers, dividends = transfers.filter(date__lte=asat), dividends.filter(date__lte=asat)
        return response("Transactions.xlsx", transaction_sheets(qs.order_by("-date", "-id"), transfers.order_by("-date", "-id"),
                                                                dividends.order_by("-date", "-id")))
    paginator = Paginator(qs.order_by("-date", "-id"), PAGE_SIZE)
    number = paginator.get_page(request.GET.get("page")).number
    rows = [_txn_row(t) for t in paginator.page(number)]
    transfers = []
    if not q and side not in (SIDE_BUY, SIDE_SELL) and number == 1:
        transfers = list(Transfer.objects.filter(profile=profile).select_related(
            "instrument", "from_broker", "to_broker", "from_portfolio", "to_portfolio")[:20])
    awaiting = tx.awaiting_for(profile).count()
    return page(request, "investments/transactions.html", {
        "page_title_text": "Transactions", "rows": rows, "page_obj": paginator.page(number), "transfers": transfers, "q": q, "side": side,
        "awaiting_count": awaiting, "total": paginator.count,
        "date_today": datetime.date.today(),
    })


# ------------------------------------------------------------------ the form pages

def _default_broker_map(profile):
    settings_row = core.get_settings(profile, create=False)
    out = {}
    for inst in Instrument.objects.filter(Q(profile=None) | Q(profile=profile)).exclude(kind="index"):
        broker = settings_row.default_broker_for(inst.kind)
        if broker:
            out[inst.pk] = broker.pk
    return out


def _folio_options(profile):
    return [{"id": f.pk, "instrument": f.instrument_id, "portfolio": f.portfolio_id, "number": f.number}
            for f in Folio.objects.filter(profile=profile)]


def _form_context(profile, extra):
    base = {
        "default_brokers_json": json.dumps(_default_broker_map(profile)), "folios_json": json.dumps(_folio_options(profile)),
        "units_url": reverse("investments_available_units"),
    }
    base.update(extra)
    return base


def _apply_form_errors(form, err):
    form.add_error(None, err.message)


def _clean_data(form):
    d = dict(form.cleaned_data)
    return d


def _resolve_folio(profile, user, d):
    """The folio chosen in the list, or a new one typed on the spot (added to the investment's folios)."""
    folio = d.get("folio")
    new = (d.get("new_folio") or "").strip()
    if new and not folio:
        try:
            folio = masters.add_folio(profile, user, instrument=d["instrument"], portfolio=d["portfolio"], number=new)
        except InvestmentsError as err:
            if err.code == "DUPLICATE":
                folio = Folio.objects.get(pk=err.details["existing_id"])
            elif err.code == "SIMILAR_FOLIO":
                raise
            else:
                raise
    return folio


@inv_editor
def txn_form(request, mode):
    """Add a purchase (buy), a sale (sell), or an entry awaiting allotment (awaiting_buy / awaiting_sell)."""
    profile = profile_or_404(request)
    titles = {"buy": "Add a purchase", "sell": "Add a sale", "awaiting_buy": "Add a purchase awaiting allotment",
              "awaiting_sell": "Add a redemption awaiting its units"}
    if mode not in titles:
        raise Http404
    masters.ensure_default_portfolio(profile)
    initial = {}
    if request.GET.get("instrument"):
        inst = Instrument.objects.filter(pk=request.GET["instrument"]).first()
        if inst and inst.profile_id in (None, profile.pk):
            initial["instrument"] = inst
            default = core.get_settings(profile, create=False).default_broker_for(inst.kind)
            if default:
                initial["broker"] = default
    from .models import Portfolio

    portfolios = list(Portfolio.objects.filter(profile=profile)[:2])
    if len(portfolios) == 1:
        initial["portfolio"] = portfolios[0]
    form = forms.TransactionForm(request.POST or None, profile=profile, mode=mode, initial=initial)
    if request.method == "POST" and form.is_valid():
        d = _clean_data(form)
        try:
            folio = _resolve_folio(profile, request.user, d)
            side = SIDE_SELL if mode in ("sell", "awaiting_sell") else SIDE_BUY
            awaiting = mode.startswith("awaiting")
            tx.add_transaction(
                profile, request.user, side=side, instrument=d["instrument"], portfolio=d["portfolio"], broker=d["broker"], date=d["date"],
                units=d.get("units"), price=d.get("price"), charges=d.get("charges") or 0, folio=folio, awaiting=awaiting,
                amount=d.get("amount"), expected_allotment_date=d.get("expected_allotment_date"), reference=d.get("reference", ""),
                note=d.get("note", ""), allotment_date=d.get("allotment_date"), origin=d.get("origin") or ORIGIN_PURCHASE,
                corporate_action=d.get("corporate_action"))
        except InvestmentsError as err:
            if err.code == "WOULD_GO_NEGATIVE":
                return _refused(request, err, request.path)
            _apply_form_errors(form, err)
        else:
            messages.success(request, "Saved.")
            return redirect(reverse("investments_transactions"))
    return page(request, "investments/txn_form.html", _form_context(profile, {
        "page_title_text": titles[mode], "form": form, "mode": mode, "is_sell": mode in ("sell", "awaiting_sell"),
        "awaiting_mode": mode.startswith("awaiting"), "submit_label": "Save",
    }))


@inv_editor
def txn_edit(request, pk):
    profile = profile_or_404(request)
    try:
        txn = tx.get_transaction(profile, pk)
    except InvestmentsError:
        raise Http404
    awaiting = txn.status == STATUS_AWAITING
    mode_for_form = "awaiting_" + txn.side if awaiting else ("edit_sell" if txn.side == SIDE_SELL else "edit")
    initial = {
        "date": txn.date, "instrument": txn.instrument, "portfolio": txn.portfolio, "broker": txn.broker, "folio": txn.folio,
        "units": txn.units, "price": txn.price, "charges": txn.charges, "allotment_date": txn.allotment_date, "amount": txn.amount,
        "expected_allotment_date": txn.expected_allotment_date, "reference": txn.reference, "note": txn.note,
        "origin": txn.origin, "corporate_action": txn.corporate_action_id,
    }
    form = forms.TransactionForm(request.POST or None, profile=profile, mode=mode_for_form, initial=initial)
    if "new_folio" in form.fields:
        del form.fields["new_folio"]
    if request.method == "POST" and form.is_valid():
        d = _clean_data(form)
        fields = dict(date=d["date"], instrument=d["instrument"], portfolio=d["portfolio"], broker=d["broker"], folio=d.get("folio"),
                      charges=d.get("charges") or 0, note=d.get("note", ""))
        if awaiting:
            fields.update(amount=d.get("amount"), expected_allotment_date=d.get("expected_allotment_date"), reference=d.get("reference", ""))
        else:
            fields.update(units=d.get("units"), price=d.get("price"))
            if "allotment_date" in form.fields:
                fields["allotment_date"] = d.get("allotment_date")
            if "origin" in form.fields:
                fields.update(origin=d.get("origin") or ORIGIN_PURCHASE, corporate_action=d.get("corporate_action"))
        try:
            tx.edit_transaction(profile, request.user, pk, expected_version=request.POST.get("version"), **fields)
        except InvestmentsError as err:
            if err.code == "WOULD_GO_NEGATIVE":
                return _refused(request, err, request.path)
            _apply_form_errors(form, err)
        else:
            messages.success(request, "Saved.")
            return redirect(reverse("investments_transactions"))
    return page(request, "investments/txn_form.html", _form_context(profile, {
        "page_title_text": "Edit transaction", "form": form, "mode": mode_for_form, "is_sell": txn.side == SIDE_SELL,
        "awaiting_mode": awaiting, "txn": txn, "submit_label": "Save changes", "version": txn.version,
        "exclude_id": txn.pk, "can_delete": True,
    }))


@inv_editor
def txn_delete(request, pk):
    profile = profile_or_404(request)
    if request.method != "POST":
        return redirect(reverse("investments_txn_edit", args=[pk]))
    try:
        tx.delete_transaction(profile, request.user, pk)
    except InvestmentsError as err:
        if err.code == "WOULD_GO_NEGATIVE":
            return _refused(request, err, reverse("investments_txn_edit", args=[pk]))
        if err.status == 404:
            raise Http404
        messages.error(request, err.message)
        return redirect(reverse("investments_txn_edit", args=[pk]))
    messages.success(request, "Deleted. You can bring it back from History.")
    return redirect(reverse("investments_transactions"))


@inv_editor
@handle_errors(fallback="investments_txn_to_confirm")
def txn_cancel(request, pk):
    profile = profile_or_404(request)
    if request.method == "POST":
        tx.cancel_awaiting(profile, request.user, pk)
        messages.success(request, "Cancelled. You can bring it back from History.")
    return redirect(reverse("investments_txn_to_confirm"))


@inv_editor
def txn_complete(request, pk):
    profile = profile_or_404(request)
    try:
        txn = tx.get_transaction(profile, pk)
    except InvestmentsError:
        raise Http404
    if txn.status != STATUS_AWAITING:
        messages.info(request, "That entry is not waiting for allotment.")
        return redirect(reverse("investments_txn_to_confirm"))
    form = forms.CompleteForm(request.POST or None, initial={"allotment_date": txn.expected_allotment_date or datetime.date.today(),
                                                             "charges": txn.charges})
    needs_confirm = False
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            tx.complete_transaction(profile, request.user, pk, allotment_date=d["allotment_date"], units=d["units"], nav=d["nav"],
                                    charges=d["charges"], confirm_difference=d["confirm_difference"], expected_version=request.POST.get("version"))
        except InvestmentsError as err:
            if err.code == "WOULD_GO_NEGATIVE":
                return _refused(request, err, request.path)
            if err.code == "DIFFERENCE":
                needs_confirm = True
            form.add_error(None, err.message)
        else:
            messages.success(request, "Completed. It is now an ordinary entry.")
            return redirect(reverse("investments_transactions"))
    return page(request, "investments/txn_complete.html", {
        "page_title_text": "Complete a purchase awaiting allotment" if txn.side == SIDE_BUY else "Complete a redemption", "txn": txn, "form": form,
        "suggestions": tx.nav_suggestions(profile, txn), "needs_confirm": needs_confirm, "version": txn.version,
        "tolerance": tx.tolerance_for(txn.amount)}, selectors=False)


@inv_editor
@handle_errors(fallback="investments_txn_to_confirm")
def txn_confirm(request, pk):
    profile = profile_or_404(request)
    if request.method == "POST":
        tx.confirm_pending(profile, request.user, pk, units=request.POST.get("units") or None, price=request.POST.get("price") or None)
        messages.success(request, "Confirmed.")
    return redirect(reverse("investments_txn_to_confirm"))


@inv_reader
def to_complete(request):
    profile = profile_or_404(request)
    settings_row = core.get_settings(profile, create=False)
    rows = []
    for t in tx.to_complete(profile):
        t.overdue = tx.overdue(t, settings_row.awaiting_reminder_days)
        t.waiting_days = (datetime.date.today() - t.date).days
        t.suggest = tx.nav_suggestions(profile, t, limit=1)[0] if t.status == STATUS_AWAITING and tx.nav_suggestions(profile, t, limit=1) else None
        rows.append(t)
    return page(request, "investments/to_complete.html", {"page_title_text": "To complete", "rows": rows,
                                                           "reminder_days": settings_row.awaiting_reminder_days})


# ------------------------------------------------------------------ opening balance, transfer, switch

@inv_editor
def txn_opening(request):
    profile = profile_or_404(request)
    masters.ensure_default_portfolio(profile)
    initial = {}
    if request.GET.get("instrument", "").isdigit():
        inst = Instrument.objects.filter(pk=request.GET["instrument"]).first()
        if inst and inst.profile_id in (None, profile.pk):
            initial["instrument"] = inst
            default = core.get_settings(profile, create=False).default_broker_for(inst.kind)
            if default:
                initial["broker"] = default
    form = forms.OpeningForm(request.POST or None, profile=profile, initial=initial)
    lines, line_errors = [], []
    rows = max(5, int(request.POST.get("rows", 5) or 5)) if request.method == "POST" else 5
    if request.method == "POST":
        for i in range(rows):
            raw = {k: request.POST.get(f"{k}_{i}", "").strip() for k in ("date", "units", "cost", "estimated")}
            if not (raw["date"] or raw["units"] or raw["cost"]):
                continue
            try:
                lines.append({"date": datetime.date.fromisoformat(raw["date"]), "units": Decimal(raw["units"].replace(",", "")),
                              "cost_per_unit": Decimal(raw["cost"].replace(",", "")), "estimated": bool(raw["estimated"])})
            except Exception:
                line_errors.append(f"Row {i + 1}: enter a date, units and cost per unit.")
    if request.method == "POST" and form.is_valid() and not line_errors:
        d = form.cleaned_data
        try:
            tx.add_opening_balances(profile, request.user, instrument=d["instrument"], portfolio=d["portfolio"], broker=d["broker"],
                                    folio=d["folio"], lines=lines)
        except InvestmentsError as err:
            if err.code == "WOULD_GO_NEGATIVE":
                return _refused(request, err, request.path)
            form.add_error(None, err.message)
        else:
            messages.success(request, f"{len(lines)} lot(s) saved.")
            return redirect(reverse("investments_transactions"))
    for message in line_errors:
        form.add_error(None, message)
    return page(request, "investments/txn_opening.html", _form_context(profile, {
        "page_title_text": "Opening balance", "form": form, "row_numbers": range(rows),
        "posted": request.POST if request.method == "POST" else {}}))


@inv_editor
def txn_transfer(request):
    profile = profile_or_404(request)
    masters.ensure_default_portfolio(profile)
    form = forms.TransferForm(request.POST or None, profile=profile)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            tx.add_transfer(profile, request.user, instrument=d["instrument"], date=d["date"], units=d["units"],
                            from_portfolio=d["from_portfolio"], from_broker=d["from_broker"], from_folio=d["from_folio"],
                            to_portfolio=d["to_portfolio"], to_broker=d["to_broker"], to_folio=d["to_folio"], note=d["note"])
        except InvestmentsError as err:
            if err.code == "WOULD_GO_NEGATIVE":
                return _refused(request, err, request.path)
            form.add_error(None, err.message)
        else:
            messages.success(request, "Transfer saved.")
            return redirect(reverse("investments_transactions"))
    return page(request, "investments/txn_simple_form.html", _form_context(profile, {
        "page_title_text": "Transfer", "form": form, "intro": "Move units from one portfolio, broker or folio to another. The original purchase dates and cost are kept."}))


@inv_editor
def txn_switch(request):
    profile = profile_or_404(request)
    form = forms.SwitchForm(request.POST or None, profile=profile)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            tx.add_switch(profile, request.user, date=d["date"], portfolio=d["portfolio"], broker=d["broker"], from_instrument=d["from_instrument"],
                          units_out=d["units_out"], price_out=d["price_out"], to_instrument=d["to_instrument"], units_in=d["units_in"],
                          price_in=d["price_in"], charges=d["charges"] or 0, note=d["note"])
        except InvestmentsError as err:
            if err.code == "WOULD_GO_NEGATIVE":
                return _refused(request, err, request.path)
            form.add_error(None, err.message)
        else:
            messages.success(request, "Switch saved as a linked sale and purchase.")
            return redirect(reverse("investments_transactions"))
    return page(request, "investments/txn_simple_form.html", _form_context(profile, {
        "page_title_text": "Fund switch", "form": form, "intro": "A switch is a sale of one fund and a purchase of another on the same day, linked."}))


@inv_editor
def transfer_delete(request, pk):
    profile = profile_or_404(request)
    if request.method == "POST":
        try:
            tx.delete_transfer(profile, request.user, pk)
        except InvestmentsError as err:
            if err.code == "WOULD_GO_NEGATIVE":
                return _refused(request, err, reverse("investments_transactions"))
            messages.error(request, err.message)
        else:
            messages.success(request, "Transfer deleted. You can bring it back from History.")
    return redirect(reverse("investments_transactions"))


@inv_editor
def switch_delete(request, pk):
    profile = profile_or_404(request)
    if request.method == "POST":
        try:
            tx.delete_switch(profile, request.user, pk)
        except InvestmentsError as err:
            if err.code == "WOULD_GO_NEGATIVE":
                return _refused(request, err, reverse("investments_transactions"))
            messages.error(request, err.message)
        else:
            messages.success(request, "Switch deleted.")
    return redirect(reverse("investments_transactions"))


# ------------------------------------------------------------------ statement import (plan 6)

@inv_editor
def import_statement(request):
    import json
    import os
    import secrets
    import tempfile
    from pathlib import Path

    from .models import Broker, Portfolio
    from .services import statement_import

    profile = profile_or_404(request)
    staging = Path(tempfile.gettempdir()) / "quill_inv_statements"
    review = token = None
    error = ""
    portfolios = Portfolio.objects.filter(profile=profile)
    brokers = Broker.objects.filter(profile=profile, hidden=False)
    chosen = {"portfolio": request.POST.get("portfolio", ""), "broker": request.POST.get("broker", "")}
    if request.GET.get("sample"):
        return _import_sample()
    # The page's portfolio and broker are only for rows that leave their own cells blank (owner round 2026-11).
    page_portfolio = portfolios.filter(pk=chosen["portfolio"]).first() if chosen["portfolio"].isdigit() else None
    page_broker = brokers.filter(pk=chosen["broker"]).first() if chosen["broker"].isdigit() else None

    def staged():
        """The staged file of this review and the investments added for it (``<token>-aliases.json`` beside it)."""
        token = request.POST.get("token", "")
        if not token.isalnum():
            raise Http404
        path = next(staging.glob(f"{token}.*"), None)
        if path is None:
            raise InvestmentsError("EXPIRED", "The file has expired. Choose it again.")
        alias_file = staging / f"{token}-aliases.json"
        aliases = json.loads(alias_file.read_text()) if alias_file.exists() else {}
        return token, path, alias_file, aliases

    def load_origins(token):
        """The origin the person chose for some lines on the review page (``<token>-origins.json``: line number -> origin)."""
        origin_file = staging / f"{token}-origins.json"
        try:
            return json.loads(origin_file.read_text()) if origin_file.exists() else {}
        except ValueError:
            return {}

    try:
        if request.method == "POST" and request.POST.get("set_origins"):
            # Keep the "Treated as" choices for the lines, then show the review again with them applied.
            token, path, alias_file, aliases = staged()
            valid = {value for value, _label in ORIGINS}
            chosen_origins = {key[len("origin_"):]: value for key, value in request.POST.items()
                              if key.startswith("origin_") and key[len("origin_"):].isdigit() and value in valid}
            (staging / f"{token}-origins.json").write_text(json.dumps(chosen_origins))
            review = statement_import.review(profile, path, aliases, portfolio=page_portfolio, broker=page_broker, origins=chosen_origins)
        elif request.method == "POST" and request.POST.get("create"):
            # Add the missing investments the person ticked (and corrected), then show the review again.
            token, path, alias_file, aliases = staged()
            specs = []
            for i in range(min(int(request.POST.get("missing_count") or 0), 500)):
                if request.POST.get(f"add_{i}"):
                    specs.append({k: request.POST.get(f"{k}_{i}", "") for k in ("text", "kind", "name", "code", "isin", "currency")})
            try:
                if not specs:
                    raise InvestmentsError("REQUIRED", "Tick the investments to add.")
                aliases.update(statement_import.create_missing(profile, request.user, specs))
            except InvestmentsError as err:
                error = err.message
            else:
                alias_file.write_text(json.dumps(aliases))
                messages.success(request, f"{len(specs)} investment{'s' if len(specs) != 1 else ''} added. Check the lines again, then save.")
            review = statement_import.review(profile, path, aliases, portfolio=page_portfolio, broker=page_broker, origins=load_origins(token))
        elif request.method == "POST" and request.POST.get("apply"):
            token, path, alias_file, aliases = staged()
            try:
                made, completed, skipped = statement_import.apply(profile, request.user, path, portfolio=page_portfolio, broker=page_broker,
                                                                  aliases=aliases, origins=load_origins(token))
            except InvestmentsError as err:
                if err.code == "WOULD_GO_NEGATIVE":
                    return _refused(request, err, reverse("investments_import_statement"))
                raise
            path.unlink(missing_ok=True)
            alias_file.unlink(missing_ok=True)
            (staging / f"{token}-origins.json").unlink(missing_ok=True)
            messages.success(request, f"{made} entr{'y' if made == 1 else 'ies'} saved, {completed} awaiting entr{'y' if completed == 1 else 'ies'} completed, "
                                      f"{skipped} duplicate{'s' if skipped != 1 else ''} skipped.")
            return redirect(reverse("investments_transactions"))
        if request.method == "POST" and request.FILES.get("file"):
            upload = request.FILES["file"]
            ext = os.path.splitext(upload.name)[1].lower()
            if ext not in (".csv", ".xlsx"):
                raise InvestmentsError("BAD_FILE", "Only .csv and .xlsx files can be imported.")
            staging.mkdir(parents=True, exist_ok=True)
            token = secrets.token_hex(12)
            path = staging / f"{token}{ext}"
            with open(path, "wb") as out:
                for chunk in upload.chunks():
                    out.write(chunk)
            review = statement_import.review(profile, path, portfolio=page_portfolio, broker=page_broker)
    except InvestmentsError as err:
        error = err.message
        review = None
    return page(request, "investments/import_statement.html", {"page_title_text": "Import a statement", "review": review, "token": token, "error": error,
                                                              "portfolios": portfolios, "brokers": brokers, "chosen": chosen,
                                                              "addable_kinds": statement_import.ADDABLE_KINDS, "origins": ORIGINS,
                                                              "origin_help": statement_import.origin_help()}, selectors=False)


def _import_sample():
    """An Excel sheet with the holdings-import headings and two example rows (owner round 2026-11)."""
    from datetime import date as _date

    from .exports import response

    header = ["Date of transaction", "Name of investment", "Investment code", "Type", "Folio", "Portfolio", "Broker", "Transaction type",
              "Transaction price", "Transaction quantity", "Origin"]
    # Origin is optional (blank means a purchase). Bonus shares, split units and shares received on a demerger need no price.
    rows = [[_date(2019, 5, 2), "Reliance Industries", "RELIANCE.NS", "Share", "", "Main", "Zerodha", "Buy", 1350.25, 10, "Purchase"],
            [_date(2021, 3, 15), "Parag Parikh Flexi Cap Fund - Direct Growth", "122639", "Mutual Fund", "1234567/89", "Main", "Direct", "Buy", 41.2, 242.718, "Purchase"],
            [_date(2024, 10, 28), "Reliance Industries", "RELIANCE.NS", "Share", "", "Main", "Zerodha", "Buy", None, 10, "Bonus"]]
    return response("Holdings import sample.xlsx", [("Holdings", header, rows)])
