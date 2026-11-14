"""Dividends, corporate actions and alerts pages (plan 7, 8, 14)."""
from datetime import date, timedelta

from django.contrib import messages
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

from . import forms
from .decorators import inv_editor, inv_read_write, inv_reader
from .errors import InvestmentsError
from .models import CorporateAction, CorporateActionResponse, Dividend, Guardrail, Instrument, Portfolio
from .services import alerts, core, corporate, dividends, masters, source_formats
from .viewutil import handle_errors, page, parse_date, profile_or_404, selection


# ------------------------------------------------------------------ dividends

@inv_reader
def dividends_list(request):
    profile = profile_or_404(request)
    portfolio, broker, _asat = selection(request, profile)
    qs = Dividend.objects.filter(profile=profile).select_related("instrument", "portfolio", "broker", "folio")
    if portfolio:
        qs = qs.filter(portfolio_id=portfolio)
    if broker:
        qs = qs.filter(broker_id=broker)
    rows = list(qs[:500])
    if request.GET.get("export") == "xlsx":
        from .exports import response

        return response("Dividends.xlsx", [("Dividends", ["Date received", "Investment", "Portfolio", "Broker", "Folio", "Amount", "Tax deducted", "Note"],
                                            [[r.date, r.instrument.name, r.portfolio.name, r.broker.name, r.folio.number if r.folio else "", r.amount,
                                              r.tax_deducted, r.note] for r in qs.iterator()])])
    return page(request, "investments/dividends.html", {"page_title_text": "Dividends", "rows": rows, "years": dividends.by_year(profile, portfolio, broker),
                                                       "due": dividends.due(profile)})


@inv_editor
def dividend_form(request, pk=None):
    profile = profile_or_404(request)
    masters.ensure_default_portfolio(profile)
    obj = Dividend.objects.filter(pk=pk, profile=profile).first() if pk else None
    if pk and obj is None:
        raise Http404
    initial = {}
    if obj:
        initial = {f: getattr(obj, f) for f in ("date", "instrument", "portfolio", "broker", "folio", "amount", "tax_deducted", "note")}
    else:
        inst = Instrument.objects.filter(pk=request.GET.get("instrument") or 0).first()
        if inst:
            initial["instrument"] = inst
        if request.GET.get("date"):
            initial["date"] = parse_date(request.GET["date"])
        if request.GET.get("amount"):
            initial["amount"] = request.GET["amount"]
        portfolios = list(Portfolio.objects.filter(profile=profile)[:2])
        if len(portfolios) == 1:
            initial["portfolio"] = portfolios[0]
    form = forms.DividendForm(request.POST or None, profile=profile, initial=initial)
    suggest = None
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            if request.POST.get("delete") and obj:
                dividends.delete(profile, request.user, obj.pk)
                messages.success(request, "Deleted. You can bring it back from History.")
                return redirect(reverse("investments_dividends"))
            if obj:
                dividends.edit(profile, request.user, obj.pk, expected_version=request.POST.get("version"), **d)
            else:
                dividends.add(profile, request.user, **d)
        except InvestmentsError as err:
            form.add_error(None, err.message)
        else:
            messages.success(request, "Saved.")
            return redirect(reverse("investments_dividends"))
    elif request.method == "POST" and request.POST.get("delete") and obj:
        dividends.delete(profile, request.user, obj.pk)
        return redirect(reverse("investments_dividends"))
    inst = form["instrument"].value()
    day = parse_date(str(form["date"].value() or "")) or date.today()
    if inst and str(inst).isdigit():
        found = Instrument.objects.filter(pk=inst).first()
        if found:
            suggest = dividends.suggestion(profile, found, day)
    return page(request, "investments/dividend_form.html", {"page_title_text": "Edit dividend" if obj else "Add a dividend", "form": form, "obj": obj,
                                                           "suggest": suggest}, selectors=False)


# ------------------------------------------------------------------ corporate actions

@inv_read_write
@handle_errors(fallback="investments_corporate_actions")
def corporate_actions(request):
    profile = profile_or_404(request)
    form = forms.CorporateActionForm(request.POST or None, profile=profile)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "record" and form.is_valid():
            d = form.cleaned_data
            ca = corporate.record(profile, request.user, instrument=d["instrument"], ex_date=d["ex_date"], kind=d["kind"], ratio_old=d["ratio_old"] or 1,
                                  ratio_new=d["ratio_new"] or 1, notes=d["notes"], target_instrument=d.get("target_instrument"),
                                  cost_percent_to_target=d.get("cost_percent_to_target"))
            if d["apply_now"]:
                try:
                    corporate.respond(profile, request.user, ca.pk, "applied", choice=d.get("choice") or None, inherit_dates=d.get("inherit_dates"))
                except InvestmentsError as err:
                    if err.code == "WOULD_GO_NEGATIVE":
                        from .views_txn import _refused

                        return _refused(request, err, reverse("investments_corporate_actions"))
                    messages.error(request, f"Recorded, but not applied: {err.message}")
                    return redirect(reverse("investments_corporate_actions"))
            messages.success(request, "Recorded." + (" Applied to this profile." if d["apply_now"] else " Confirm it below to change your holdings."))
            return redirect(reverse("investments_corporate_actions"))
        if action == "change_kind":
            corporate.change_kind(profile, request.user, int(request.POST.get("id", 0)), request.POST.get("kind", ""))
            messages.success(request, "Changed. Check the ratio, then apply it.")
            return redirect(reverse("investments_corporate_actions"))
        if action in ("applied", "not_applicable", "pending"):
            try:
                corporate.respond(profile, request.user, int(request.POST.get("id", 0)), action, choice=request.POST.get("choice") or None,
                                  inherit_dates=(bool(request.POST.get("inherit_dates")) if request.POST.get("inherit_present") else None))
            except InvestmentsError as err:
                if err.code == "WOULD_GO_NEGATIVE":
                    from .views_txn import _refused

                    return _refused(request, err, reverse("investments_corporate_actions"))
                raise
            messages.success(request, "Saved.")
            return redirect(reverse("investments_corporate_actions"))
    return page(request, "investments/corporate_actions.html", {
        "page_title_text": "Corporate actions", "rows": corporate.for_profile(profile), "pending": corporate.pending(profile), "form": form,
        "moves": corporate.large_moves_without_action(profile), "mode": core.get_settings(profile, create=False).corporate_action_mode,
        "unit_choices": forms.CHOICES_FOR_UNITS}, selectors=False, status_line=True)


@inv_editor
@handle_errors(fallback="investments_corporate_actions")
def corporate_action_edit(request, pk):
    """Change a recorded corporate action (date, ratio, and for a demerger the new company and cost split), also after it was applied."""
    profile = profile_or_404(request)
    action = CorporateAction.objects.filter(pk=pk, instrument_id__in=corporate.held_instrument_ids(profile)).select_related("instrument", "target_instrument").first()
    if action is None:
        raise Http404
    initial = {"ex_date": action.ex_date, "ratio_old": action.ratio_old.normalize(), "ratio_new": action.ratio_new.normalize(), "notes": action.notes,
               "target_instrument": action.target_instrument, "cost_percent_to_target": action.cost_percent_to_target}
    form = forms.CorporateActionEditForm(request.POST or None, profile=profile, action=action, initial=initial)
    rows = []
    if action.kind == "demerger" and CorporateActionResponse.objects.filter(profile=profile, action=action, status=corporate.STATUS_APPLIED).exists():
        rows = corporate.bucket_allotments(profile, action)
    if rows and request.method == "POST":
        for r in rows:   # show what was typed again when the save is refused
            r["override"] = request.POST.get(r["field"], r["override"]).strip()
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            with transaction.atomic():
                if rows:
                    corporate.set_units_overrides(profile, request.user, action.pk, {r["key"]: request.POST.get(r["field"], r["override"]) for r in rows})
                corporate.update(profile, request.user, action.pk, ex_date=d["ex_date"], ratio_old=d.get("ratio_old") or action.ratio_old,
                                 ratio_new=d.get("ratio_new") or action.ratio_new, notes=d["notes"], target_instrument=d.get("target_instrument"),
                                 cost_percent_to_target=d.get("cost_percent_to_target"))
        except InvestmentsError as err:
            if err.code == "WOULD_GO_NEGATIVE":
                from .views_txn import _refused

                return _refused(request, err, reverse("investments_corporate_actions"))
            form.add_error(None, err.message)
        else:
            messages.success(request, "Saved. Shares of the new company that the program made were made again from the new terms.")
            return redirect(reverse("investments_corporate_actions"))
    return page(request, "investments/corporate_action_form.html", {"page_title_text": "Edit corporate action", "form": form, "action": action, "allotments": rows},
                selectors=False)


# ------------------------------------------------------------------ alerts

@inv_read_write
@handle_errors(fallback="investments_alerts")
def alerts_page(request):
    profile = profile_or_404(request)
    posted = request.method == "POST"
    what = request.POST.get("action") if posted else None
    gform = forms.GuardrailForm(request.POST if what == "guardrail" else None, profile=profile)
    srow = core.get_settings(profile, create=False)
    sform = forms.AlertSettingsForm(request.POST if what == "settings" else None, initial={f: getattr(srow, f) for f in forms.AlertSettingsForm.base_fields})
    if posted and what == "settings" and sform.is_valid():
        masters.update_settings(profile, request.user, **sform.cleaned_data)
        messages.success(request, "Saved.")
        return redirect(reverse("investments_alerts") + "#alert-settings")
    if posted:
        if what in ("dismiss", "snooze", "rearm", "reset"):
            alerts.act(profile, request.POST.get("key", ""), what, until=parse_date(request.POST.get("until")), level=request.POST.get("level"))
            core.touch(profile)
        elif what == "guardrail" and gform.is_valid():
            d = gform.cleaned_data
            if d["instrument"].profile_id not in (None, profile.pk):
                raise Http404
            Guardrail.objects.create(profile=profile, **d)
            core.touch(profile)
            messages.success(request, "Guardrail added.")
        elif what == "delete_guardrail":
            Guardrail.objects.filter(pk=request.POST.get("id"), profile=profile).delete()
            core.touch(profile)
        return redirect(reverse("investments_alerts"))
    return page(request, "investments/alerts.html", {
        "sform": sform, "page_title_text": "Alerts and guardrails", "alerts": alerts.visible(profile), "guardrails": Guardrail.objects.filter(profile=profile).select_related("instrument", "portfolio"),
        "gform": gform, "settings_row": core.get_settings(profile, create=False), "next_week": date.today() + timedelta(days=7),
        "format_problems": source_formats.problems() if core.get_settings(profile, create=False).source_problems_enabled else [], "is_admin": bool(getattr(request.user, "is_admin", False))}, selectors=False, status_line=True)


def settings_alerts(request):
    """The old Settings > Alerts address: the options now sit on the Alerts page (302 for a GET, 308 keeps a POST)."""
    response = HttpResponse(status=308 if request.method == "POST" else 302)
    response["Location"] = reverse("investments_alerts") + ("" if request.method == "POST" else "#alert-settings")
    return response
