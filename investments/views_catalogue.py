"""The Admin catalogue pages (plan 21.1): the list, and one investment with its price history, symbols, holders and structural operations."""
import datetime

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

from . import forms
from .decorators import inv_admin
from .errors import InvestmentsError
from .models import CatalogueHistory, Instrument, ProfileInvestment, SourceSymbol
from .services import catalogue, fetch
from .viewutil import handle_errors, page, parse_date, profile_or_404


def _shared_or_404(pk):
    inst = Instrument.objects.filter(pk=pk, profile=None).first()
    if inst is None:
        raise Http404
    return inst


@inv_admin
def catalogue_list(request):
    profile_or_404(request)
    q, kind, source, flag = (request.GET.get(k, "") for k in ("q", "type", "source", "flag"))
    items = catalogue.listing(q=q, kind=kind, source=source, flag=flag)
    if request.GET.get("export") == "xlsx":
        return _export(items)
    return page(request, "investments/catalogue.html", {
        "page_title_text": "Investment catalogue", "items": items, "q": q, "kind": kind, "source": source, "flag": flag,
        "kinds": [("", "All types"), ("share", "Share"), ("fund", "Mutual fund"), ("foreign", "Foreign"), ("index", "Index")],
        "sources": [("", "All sources"), ("yahoo", "Yahoo"), ("amfi", "AMFI"), ("mfapi", "mfapi.in"), ("manual", "Manual"), ("upload", "Uploaded")],
        "flags": [("", "Any"), ("stale", "Stale"), ("failing", "Fetch failing"), ("split", "Split detected"), ("duplicate", "Possible duplicate")],
        "new_form": forms.CatalogueNewForm()}, selectors=False)


def _export(items):
    """Excel export of the list (exact values, write-only workbook; no transaction data exists in it)."""
    import tempfile

    from openpyxl import Workbook

    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Catalogue")
    ws.append(["Name", "Type", "Code", "ISIN", "Price source", "Price basis", "Last price", "Rows stored", "Held by (profiles)", "Flags"])
    for i in items:
        ws.append([_safe(i.name), i.get_kind_display(), _safe(i.code), i.isin, i.price_source, i.price_basis, i.last.isoformat() if i.last else "", i.rows,
                   i.holders, ", ".join(i.flags)])
    with tempfile.SpooledTemporaryFile(max_size=2 * 1024 * 1024) as spool:
        wb.save(spool)
        spool.seek(0)
        data = spool.read()
    response = HttpResponse(data, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="investment-catalogue.xlsx"'
    return response


def _safe(text):
    """Formula-injection guard for spreadsheet cells."""
    text = str(text or "")
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


@inv_admin
@handle_errors(fallback="investments_admin_catalogue")
def catalogue_new(request):
    profile_or_404(request)
    if request.method == "POST":
        form = forms.CatalogueNewForm(request.POST)
        if form.is_valid():
            inst = catalogue.create_instrument(request.user, **form.cleaned_data)
            return redirect(reverse("investments_admin_catalogue_item", args=[inst.pk]))
        messages.error(request, "Check the details and try again.")
    return redirect(reverse("investments_admin_catalogue"))


@inv_admin
def catalogue_item(request, pk):
    profile_or_404(request)
    inst = _shared_or_404(pk)
    start, end = parse_date(request.GET.get("from")), parse_date(request.GET.get("to"))
    try:
        number = int(request.GET.get("page", 1))
    except ValueError:
        number = 1
    rows, number, pages, total = catalogue.price_rows(inst, start, end, number)
    details = forms.CatalogueDetailsForm(initial={f: getattr(inst, f) for f in catalogue.EDITABLE})
    symbols = {s.source: s.symbol for s in SourceSymbol.objects.filter(instrument=inst)}
    return page(request, "investments/catalogue_item.html", {
        "page_title_text": inst.name, "inst": inst, "rows": rows, "page_no": number, "pages": pages, "total": total, "start": start, "end": end,
        "details_form": details, "holders": catalogue.holder_profiles(inst), "affected": catalogue.affected_profiles(inst),
        "symbols": [(key, symbols.get(key, "")) for key in ("yahoo", "amfi", "mfapi")], "log": CatalogueHistory.objects.filter(instrument_id_ref=inst.pk)[:30],
        "profile_details": ProfileInvestment.objects.filter(instrument=inst).select_related("profile", "sectoral_index"),
        "basis": catalogue.basis_preview(inst), "others": Instrument.objects.filter(profile=None, kind=inst.kind).exclude(pk=inst.pk).order_by("name"),
        "moves": fetch.one_day_moves(inst), "stale_days": fetch.stale_days(inst),
        "deleted_prices": CatalogueHistory.objects.filter(instrument_id_ref=inst.pk, record_type="price_deleted")[:10],
        "today": datetime.date.today()}, selectors=False)


@inv_admin
@handle_errors()
def catalogue_action(request, pk):
    """All POST actions of the item page, chosen by ``action``."""
    profile_or_404(request)
    inst = _shared_or_404(pk)
    if request.method != "POST":
        return redirect(reverse("investments_admin_catalogue_item", args=[pk]))
    action, reason, user = request.POST.get("action", ""), request.POST.get("reason", ""), request.user
    back = reverse("investments_admin_catalogue_item", args=[pk])
    if action == "details":
        form = forms.CatalogueDetailsForm(request.POST)
        if form.is_valid():
            n = catalogue.update_details(user, inst, reason, **form.cleaned_data)
            messages.success(request, f"{n} detail{'s' if n != 1 else ''} changed.")
        else:
            messages.error(request, "Check the details and try again.")
    elif action == "symbol":
        catalogue.set_source_symbol(user, inst, request.POST.get("source", ""), request.POST.get("symbol", ""), reason)
        messages.success(request, "Symbol saved.")
    elif action == "price":
        day = parse_date(request.POST.get("date"))
        if day is None:
            raise InvestmentsError("BAD_DATE", "Enter a date.")
        pins = catalogue.set_price(user, inst, day, request.POST.get("close", ""), reason)
        messages.success(request, "Price saved as a hand-entered price" + (f"; {pins} pinned price updated." if pins else "."))
    elif action == "delete_price":
        day = parse_date(request.POST.get("date"))
        catalogue.delete_price(user, inst, day, reason)
        messages.success(request, "Price deleted. It can be put back from the change log.")
    elif action == "restore_price":
        catalogue.restore_price(user, int(request.POST.get("log", 0)))
        messages.success(request, "Price put back.")
    elif action == "refetch":
        start, end = parse_date(request.POST.get("from")), parse_date(request.POST.get("to"))
        if not start or not end or start > end:
            raise InvestmentsError("BAD_DATE", "Enter a from and a to date.")
        n = catalogue.refetch_range(user, inst, start, end)
        messages.success(request, f"{n} prices fetched again.")
    elif action == "merge":
        drop = _shared_or_404(int(request.POST.get("other", 0)))
        if request.POST.get("confirm"):
            catalogue.merge(user, inst, drop, reason)
            messages.success(request, f"{drop.name} was merged into {inst.name}.")
        else:
            return page(request, "investments/catalogue_merge.html", {"page_title_text": "Merge", "keep": inst, "drop": drop,
                                                                       "preview": catalogue.merge_preview(inst, drop), "reason": reason}, selectors=False)
    elif action == "basis":
        if request.POST.get("confirm"):
            result = catalogue.change_basis(user, inst, request.POST.get("new_basis", ""), reason)
            messages.success(request, f"Price basis changed. {result['uploaded']} uploaded row(s) need re-uploading on the new basis.")
        else:
            return page(request, "investments/catalogue_basis.html", {"page_title_text": "Change price basis", "inst": inst, "new_basis": request.POST.get("new_basis", ""),
                                                                       "preview": catalogue.basis_preview(inst), "reason": reason}, selectors=False)
    elif action == "delete":
        catalogue.delete_instrument(user, inst, reason)
        messages.success(request, "Deleted.")
        return redirect(reverse("investments_admin_catalogue"))
    elif action == "profile_detail":
        pi = ProfileInvestment.objects.filter(pk=request.POST.get("pi", 0), instrument=inst).first()
        if pi is None:
            raise Http404
        sect = Instrument.objects.filter(pk=request.POST.get("sectoral") or 0, kind="index").first()
        hidden = bool(request.POST.get("hidden"))
        catalogue.log(user, inst, "profile_detail", pi.pk, "sectoral/hidden", f"{pi.sectoral_index_id}/{pi.hidden}", f"{getattr(sect, 'pk', None)}/{hidden}", reason)
        pi.sectoral_index, pi.hidden = sect, hidden
        pi.save(update_fields=["sectoral_index", "hidden"])
        messages.success(request, "Saved.")
    else:
        raise Http404
    return redirect(back)
