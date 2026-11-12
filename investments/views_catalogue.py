"""The investment catalogue (plan 21.1): the list, and one investment with its price history, symbols, holders and structural operations.

Owner round (2026-11): everyone in Investments can see the catalogue and each investment's price history; an Editor can correct prices, fetch
the history again from a chosen date and trim the history before the first purchase (``price_action``, also used from an investment's own
page). Shared details, symbols, other profiles' names and the structural operations stay with the Admin."""
import datetime

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse

from . import forms
from .decorators import inv_admin, inv_editor, inv_reader
from .errors import InvestmentsError
from .models import CatalogueHistory, Instrument, ProfileInvestment, SourceSymbol
from .services import catalogue, fetch
from .viewutil import handle_errors, page, parse_date, profile_or_404, safe_next


def _shared_or_404(pk):
    inst = Instrument.objects.filter(pk=pk, profile=None).first()
    if inst is None:
        raise Http404
    return inst


@inv_reader
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
        "new_form": forms.CatalogueNewForm(), "is_admin": bool(getattr(request.user, "is_admin", False))}, selectors=False)


def _export(items):
    """Excel export of the list (exact values; nothing about any profile's transactions is in it)."""
    from .exports import response

    rows = [[i.name, i.get_kind_display(), i.code, i.isin, i.price_source, i.price_basis, i.last, i.rows, i.holders, ", ".join(i.flags)] for i in items]
    return response("Investment catalogue.xlsx", [("Catalogue", ["Name", "Type", "Code", "ISIN", "Price source", "Price basis", "Last price", "Rows stored",
                                                                  "Held by (profiles)", "Flags"], rows)])


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


def price_history_context(request, inst, prefix="", profile=None):
    """The price-history block of the catalogue item page and of an investment's own page (``templates/investments/_price_history.html``).
    ``prefix`` keeps its query parameters apart from the page's own. ``profile`` is given on the investment's own page only: the catalogue
    never shows a date from any profile's records (plan 21.1), so the first purchase and the trim tool are on the investment's page."""
    start, end = parse_date(request.GET.get(prefix + "from")), parse_date(request.GET.get(prefix + "to"))
    try:
        number = int(request.GET.get(prefix + "page", 1))
    except ValueError:
        number = 1
    rows, number, pages, total = catalogue.price_rows(inst, start, end, number)
    from .models import Price

    own_first = catalogue.first_purchase_date(inst, profile=profile) if profile is not None else None
    oldest = Price.objects.filter(instrument=inst).order_by("date").values_list("date", flat=True).first()
    trim = catalogue.trim_preview(inst) if profile is not None else None
    if trim and not trim["problem"]:
        trim["own"] = own_first is not None and trim["first"] == own_first   # the earliest purchase is this profile's own
    return {"p_rows": rows, "p_page_no": number, "p_pages": pages, "p_total": total, "p_start": start, "p_end": end, "p_prefix": prefix,
            "p_first_purchase": own_first, "p_oldest": oldest, "p_fetchable": inst.price_source in ("yahoo", "amfi", "mfapi"),
            "p_trim": trim, "p_today": datetime.date.today(),
            "p_deleted": CatalogueHistory.objects.filter(instrument_id_ref=inst.pk, record_type="price_deleted")[:10]}


@inv_reader
def catalogue_item(request, pk):
    profile_or_404(request)
    inst = _shared_or_404(pk)
    is_admin = bool(getattr(request.user, "is_admin", False))
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
        "today": datetime.date.today(), "is_admin": is_admin,
        "index_choices": Instrument.objects.filter(profile=None, kind="index").order_by("name"), **price_history_context(request, inst)}, selectors=False)


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
        # First a page listing what goes (counts per profile only); the delete itself needs confirm (and the name typed
        # while any profile has anything about it).
        if request.POST.get("confirm"):
            name = inst.name
            try:
                result = catalogue.delete_instrument(user, inst, reason, confirm_name=request.POST.get("confirm_name"))
            except InvestmentsError as err:
                if err.code != "CONFIRM_NAME":
                    raise
                messages.error(request, err.message)
                return page(request, "investments/catalogue_delete.html", {"page_title_text": "Delete investment", "inst": inst,
                                                                           "preview": catalogue.delete_preview(inst), "reason": reason}, selectors=False)
            affected = result["profiles"]
            messages.success(request, f"{name} deleted" + (f", with its records in {affected} profile{'s' if affected != 1 else ''}." if affected else "."))
            return redirect(reverse("investments_admin_catalogue"))
        return page(request, "investments/catalogue_delete.html", {"page_title_text": "Delete investment", "inst": inst,
                                                                   "preview": catalogue.delete_preview(inst), "reason": reason}, selectors=False)
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


@inv_editor
@handle_errors(fallback="investments_admin_catalogue")
def price_action(request, pk):
    """The price-history actions of a shared investment, from the catalogue or from the investment's own page (``next`` says which):
    correct or add a price, delete or put one back, fetch the history from a date, trim it before the first purchase, or clear it."""
    profile_or_404(request)
    inst = _shared_or_404(pk)
    back = safe_next(request, reverse("investments_admin_catalogue_item", args=[pk]))
    if request.method != "POST":
        return redirect(back)
    action, reason, user = request.POST.get("action", ""), request.POST.get("reason", ""), request.user
    if action == "price":
        day = parse_date(request.POST.get("date"))
        if day is None:
            raise InvestmentsError("BAD_DATE", "Enter a date.")
        pins = catalogue.set_price(user, inst, day, request.POST.get("close", ""), reason)
        messages.success(request, "Price saved as a hand-entered price" + (f"; {pins} pinned price updated." if pins else "."))
    elif action == "delete_price":
        day = parse_date(request.POST.get("date"))
        if day is None:
            raise InvestmentsError("BAD_DATE", "Enter a date.")
        catalogue.delete_price(user, inst, day, reason)
        messages.success(request, "Price deleted. It can be put back from the list of deleted prices.")
    elif action == "restore_price":
        catalogue.restore_price(user, int(request.POST.get("log") or 0))
        messages.success(request, "Price put back.")
    elif action == "fetch_from":
        start = parse_date(request.POST.get("from"))
        if start is None:
            raise InvestmentsError("BAD_DATE", "Choose the date to fetch from.")
        n = catalogue.fetch_from(user, inst, start)
        messages.success(request, f"{n} price{'s' if n != 1 else ''} fetched from {start:%-d %b %Y} to today.")
    elif action == "trim":
        if request.POST.get("confirm"):
            n = catalogue.trim_before_first_purchase(user, inst, reason)
            messages.success(request, f"{n} older price{'s' if n != 1 else ''} removed. Fetch from an earlier date to bring them back.")
        else:
            profile = profile_or_404(request)
            preview = catalogue.trim_preview(inst)
            preview["own"] = bool(preview["first"]) and preview["first"] == catalogue.first_purchase_date(inst, profile=profile)
            return page(request, "investments/price_trim.html", {"page_title_text": "Remove older prices", "inst": inst,
                                                                 "preview": preview, "next": back}, selectors=False)
    elif action == "clear_prices":
        if request.POST.get("confirm"):
            n = catalogue.clear_price_history(user, inst, include_uploaded=bool(request.POST.get("include_uploaded")),
                                              include_manual=bool(request.POST.get("include_manual")), reason=reason)
            messages.success(request, f"Price history cleared: {n} price{'s' if n != 1 else ''} removed. "
                                      "Fetch the price history from a date to bring fetched prices back.")
        else:
            return page(request, "investments/price_clear.html", {"page_title_text": "Clear price history", "inst": inst,
                                                                  "preview": catalogue.clear_preview(inst), "next": back}, selectors=False)
    else:
        raise Http404
    return redirect(back)


# ------------------------------------------------------------------ data source formats (Admin)

KIND_HELP = {
    "url": "An http(s) address. Placeholders are filled in when it is used.",
    "list": "Comma-separated; the first one found in the file's header wins. Case, spaces and underscores do not matter.",
    "path": "Dotted steps into the answer, a number for a list position (for example indicators.quote.0.close).",
    "int": "A whole number (a negative one counts from the end of the line).",
    "text": "Short text.",
}


def _format_fields(key, merged, posted=None):
    """The rows of the edit table: name, kind, the value to show (what was posted, else the current one), the built-in value and whether they differ."""
    from .services import source_formats as sf

    builtin = {name: sf.show(value, kind) for name, kind, value in sf.fields(key, sf.merge(key, {}))}
    rows = []
    for name, kind, value in sf.fields(key, merged):
        shown = posted.get("f_" + name, "") if posted is not None else sf.show(value, kind)
        rows.append({"name": name, "kind": kind, "value": shown, "builtin": builtin[name], "changed": shown.strip() != builtin[name], "help": KIND_HELP[kind],
                     "placeholders": ", ".join("{" + p + "}" for p in sorted(sf.PLACEHOLDERS.get(key, ()))) if kind == "url" else ""})
    return rows


@inv_admin
def source_formats_page(request, key=None):
    """Admin: how each external file is read. The list of sources, and for one source its editable format with Save, Reset to default and
    Test this format (a sample is read with the format as typed; nothing is saved by a test)."""
    from .services import source_format_test
    from .services import source_formats as sf

    profile_or_404(request)
    if key is not None and key not in sf.DEFAULTS:
        raise Http404
    runs = sf.last_runs()
    problems = {}
    for item in sf.problems():
        problems.setdefault(item["key"], item["error"])
    context = {"page_title_text": "Data source formats", "key": key, "problems": problems}
    if key is None:
        stored = set(sf.customised())
        context["sources"] = [{"key": k, "label": sf.LABELS[k][0], "run": runs.get(k), "problem": problems.get(k), "custom": k in stored,
                               "kind": "Upload" if k in sf.UPLOAD_ONLY else "File or answer"} for k in sf.KEYS]
        return page(request, "investments/source_formats.html", context, selectors=False)
    posted = request.POST if request.method == "POST" else None
    result, errors = None, []
    merged = sf.get(key)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "reset":
            sf.reset(key)
            messages.success(request, "Back to the built-in format.")
            return redirect(reverse("investments_admin_source_format", args=[key]))
        submitted, errors = sf.parse_form(key, request.POST)
        cleaned = {}
        if not errors:
            cleaned, errors = sf.validate(key, submitted)
        if not errors and action == "save":
            sf.save(key, cleaned, request.user)
            messages.success(request, "Saved. The next fetch or import reads files this way.")
            return redirect(reverse("investments_admin_source_format", args=[key]))
        if not errors and action == "test":
            upload = request.FILES.get("sample")
            if upload is not None and upload.size > source_format_test.SAMPLE_CAP:
                errors = ["The sample file is too big (the limit is 8 MB)."]
            else:
                result = source_format_test.run(key, sf.merge(key, cleaned), upload=upload.read() if upload is not None else None,
                                                day=parse_date(request.POST.get("sample_day")), sample=request.POST.get("sample_value", ""))
        if errors:
            messages.error(request, "Not saved or tested: " + " ".join(errors))
    context.update({
        "label": sf.LABELS[key][0], "fields": _format_fields(key, merged, posted), "result": result, "custom": bool(sf.stored_config(key)),
        "upload_only": key in sf.UPLOAD_ONLY, "needs_value": key in source_format_test.SAMPLE_VALUES, "sample_value": (posted or {}).get("sample_value", ""),
        "sample_day": (posted or {}).get("sample_day", ""), "problem": problems.get(key), "run": runs.get(key), "errors": errors})
    return page(request, "investments/source_formats.html", context, selectors=False)
