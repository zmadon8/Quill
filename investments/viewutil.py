"""Small helpers shared by the Investments views: the page renderer, the portfolio / broker / as-at selection and error mapping."""
import datetime
from functools import wraps

from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from investments import pages, scope
from investments.errors import InvestmentsError
from investments.models import Broker, Portfolio
from investments.services import core

try:
    from fees.services.heavy import Busy
except Exception:  # pragma: no cover
    Busy = None


def profile_or_404(request):
    profile = scope.for_profile(request)
    if profile is None:
        raise Http404("No Investments profile.")
    return profile


def selection(request, profile):
    """The chosen portfolio id, broker id and as-at date: from the query string, else remembered in the session (per profile)."""
    key = f"inv_sel_{profile.pk}"
    saved = request.session.get(key, {})
    params = request.GET
    if params.get("sel") == "1":
        saved = {"portfolio": params.get("portfolio") or "", "broker": params.get("broker") or "", "asat": params.get("asat") or ""}
        request.session[key] = saved

    def as_id(raw, model):
        try:
            pk = int(raw)
        except (TypeError, ValueError):
            return None
        return pk if model.objects.filter(pk=pk, profile=profile).exists() else None

    portfolio = as_id(saved.get("portfolio"), Portfolio)
    broker = as_id(saved.get("broker"), Broker)
    try:
        asat = datetime.date.fromisoformat(saved.get("asat") or "")
    except ValueError:
        asat = None
    if asat and asat >= datetime.date.today():
        asat = None
    return portfolio, broker, asat


def page(request, template, context=None, status=200, selectors=True):
    """Render an Investments page with the header entries, role flag, selectors and number-display choice added."""
    profile = scope.for_profile(request)
    extra = dict(context or {})
    if profile is not None and selectors:
        portfolio, broker, asat = selection(request, profile)
        extra.setdefault("sel_portfolio", portfolio)
        extra.setdefault("sel_broker", broker)
        extra.setdefault("sel_asat", asat)
        extra.setdefault("inv_portfolios", Portfolio.objects.filter(profile=profile))
        extra.setdefault("inv_brokers", Broker.objects.filter(profile=profile, hidden=False))
        extra.setdefault("inv_status", None)
    extra["inv_selectors"] = bool(selectors and profile is not None)
    if profile is not None:
        extra.update(price_status_line(profile))
    ctx = pages.render_context(request, profile, extra)
    return render(request, template, ctx, status=status)


def safe_next(request, fallback):
    target = request.POST.get("next") or request.GET.get("next") or request.META.get("HTTP_REFERER", "")
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return target
    return fallback


def handle_errors(fallback=None, json=False):
    """Map ``InvestmentsError`` to a flash message and redirect (HTML) or a JSON body. A 404 code is a real 404."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            try:
                return view(request, *args, **kwargs)
            except InvestmentsError as err:
                if json:
                    return JsonResponse({"ok": False, "error": err.code, "message": err.message}, status=err.status)
                if err.status == 404:
                    raise Http404(err.message) from err
                messages.error(request, err.message)
                return redirect(safe_next(request, reverse(fallback) if fallback else reverse("investments_dashboard")))
            except Exception as exc:
                if Busy is not None and isinstance(exc, Busy):
                    return render(request, "investments/busy.html", status=503)
                raise

        return wrapper

    return decorator


def parse_date(value, default=None):
    try:
        return datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        return default


def touch_profile(profile):
    core.touch(profile)


def price_status_line(profile):
    """The text beside Update Prices (plan 24.5) and whether there is anything to update."""
    from django.utils import timezone

    from investments.services import fetch

    info = fetch.status_summary(profile)
    if not info["tracked"]:
        return {"inv_status": None, "inv_can_update": False}
    if not info["newest"]:
        return {"inv_status": "No prices yet. Update Prices, or ask an Admin to upload history.", "inv_can_update": True}
    parts = []
    if info["last_run"]:
        parts.append(f"Updated {timezone.localtime(info['last_run']):%-d %b %Y, %-I:%M %p}")
    if info["newest"]:
        parts.append(f"prices as of close {info['newest']:%-d %b}")
    behind = len(info["stale"]) + len(info["never"])
    if behind:
        parts.append(f"{behind} not updated")
    return {"inv_status": " \u00b7 ".join(parts) or "No prices yet. Update Prices, or ask an Admin to upload history.", "inv_can_update": True}
