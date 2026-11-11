"""The suite Home page's cards (owner round 2026-11): a few live figures per program, recent activity across the programs and
quick actions.

Only the profile the user is working in per program counts (the one the Home link opens), and only when it was given to them
on the Users screen, so the page stays the same size however many profiles exist. Each program is built in its own try block:
a failure shows the card without figures and never breaks Home. Nothing here starts a heavy calculation: the Investments
figures are read from its cache only (they appear once the Overview has been opened since the last change).
"""
import logging

from django.urls import reverse

from accounts.models import ROLE_EDITOR
from accounts.profiles import request_role
from accounts.suite import KEY_DIARY, KEY_FEES, KEY_INVESTMENTS

logger = logging.getLogger(__name__)

RECENT_LIMIT = 6


def _safe(fn, *args):
    try:
        return fn(*args)
    except Exception:  # one program must never break Home
        logger.exception("Home card failed")
        return None


# ---------------------------------------------------------------- figures
#
# Each program has a catalogue of metrics keyed by id. A user picks up to MAX_METRICS per program (My settings > Display, stored in
# User.home_metrics as {"diary": [keys], ...}); nothing chosen means the program's DEFAULT_METRICS, which are the original three.

MAX_METRICS = 3
DASH = "\u2013"

DIARY_METRICS = [("subjects", "Subjects"), ("items", "Items"), ("flagged", "Flagged"), ("clean", "Items not flagged"),
                 ("per_subject", "Items per subject")]
FEES_METRICS = [("memos_fy", "Memos this year"), ("outstanding", "Outstanding"), ("drafts", "Drafts"), ("fy", "Financial year"),
                ("memos_total", "Memos issued (all time)"), ("payments", "Payments recorded")]
INVESTMENTS_METRICS = [("value", "Value"), ("xirr", "XIRR (for the period you chose)"), ("alerts", "Alerts"), ("invested", "Invested"),
                       ("gain", "Gain (for the period you chose)")]
METRIC_CATALOGUE = {KEY_DIARY: DIARY_METRICS, KEY_FEES: FEES_METRICS, KEY_INVESTMENTS: INVESTMENTS_METRICS}
DEFAULT_METRICS = {KEY_DIARY: ["subjects", "items", "flagged"], KEY_FEES: ["memos_fy", "outstanding", "drafts"],
                   KEY_INVESTMENTS: ["value", "xirr", "alerts"]}


def chosen_metrics(user, program):
    """The metric ids to show for ``program``: the user's valid choice (at most MAX_METRICS, in order), else the defaults."""
    stored = getattr(user, "home_metrics", None)
    stored = stored.get(program) if isinstance(stored, dict) else None
    valid = {k for k, _label in METRIC_CATALOGUE[program]}
    keys = []
    for k in stored if isinstance(stored, list) else []:
        if k in valid and k not in keys:
            keys.append(k)
    return keys[:MAX_METRICS] or list(DEFAULT_METRICS[program])


def _diary_figures(profile, user=None):
    from diary.models import Subject
    from diary.views import item_counts_by_subject

    counts = item_counts_by_subject(profile)
    live = set(Subject.objects.filter(profile=profile, deleted_at__isnull=True).values_list("pk", flat=True))
    items = sum(n for pk, (n, _f) in counts.items() if pk in live)
    flagged = sum(f for pk, (_n, f) in counts.items() if pk in live)
    values = {"subjects": f"{len(live):,}", "items": f"{items:,}", "flagged": f"{flagged:,}", "clean": f"{items - flagged:,}",
              "per_subject": f"{items / len(live):,.1f}" if live else DASH}
    labels = dict(DIARY_METRICS)
    return [(labels[k], values[k]) for k in chosen_metrics(user, KEY_DIARY)]


def _fees_figures(profile, user=None):
    from fees.services import dashboard_panels
    from fees.services.money import format_money

    keys = chosen_metrics(user, KEY_FEES)
    labels = dict(FEES_METRICS)
    figures = dashboard_panels.home_figures(profile)
    values = {"memos_fy": f"{figures['memos_fy']:,}", "outstanding": "\u20b9" + format_money(figures["outstanding"], unit="short"),
              "drafts": f"{figures['drafts']:,}", "fy": str(figures.get("fy", DASH))}
    if "memos_total" in keys:
        from fees.models import Memo

        values["memos_total"] = f"{Memo.objects.filter(profile=profile, is_draft=False).count():,}"
    if "payments" in keys:
        from fees.models import Payment

        values["payments"] = f"{Payment.objects.filter(profile=profile).count():,}"
    return [(labels[k], values[k]) for k in keys]


def _investments_figures(profile, user=None):
    from investments.money_auto import format_rupees
    from investments.services import alerts, dashboard

    keys = chosen_metrics(user, KEY_INVESTMENTS)
    period = getattr(user, "investments_period", "all") or "all"
    totals = dashboard.peek_totals(profile, period=period)  # the cache only, never a calculation
    suffix = "" if period == "all" else f" {period.upper()}"
    values = {"value": format_rupees(totals["value"]) if totals else DASH}
    if "invested" in keys:
        values["invested"] = format_rupees(totals["invested"]) if totals and totals.get("invested") is not None else DASH
    if "gain" in keys:
        values["gain"] = format_rupees(totals["gain"]) if totals and totals.get("gain") is not None else DASH
    values["xirr"] = f"{totals['xirr'] * 100:.1f}%" if totals and totals.get("xirr") is not None else DASH
    if "alerts" in keys:
        n_alerts = alerts.peek_count(profile)
        values["alerts"] = DASH if n_alerts is None else f"{n_alerts:,}"
    labels = {"value": "Value", "xirr": "XIRR" + suffix, "alerts": "Alerts", "invested": "Invested", "gain": "Gain" + suffix}
    return [(labels[k], values[k]) for k in keys]


# ---------------------------------------------------------------- recent activity

_KIND_WORDS = {"create": "Added", "edit": "Edited", "delete": "Deleted", "restore": "Restored", "move": "Moved", "reorder": "Reordered",
               "convert": "Converted", "import": "Imported"}


def _diary_recent(profile):
    from diary.models import VersionHistory

    rows = (VersionHistory.objects.filter(profile=profile).order_by("-changed_at", "-id")
            .values("record_type", "change_kind", "changed_at", "group", "changed_by__first_name", "changed_by__username")[:30])
    out, seen = [], set()
    for r in rows:
        if r["group"] and r["group"] in seen:
            continue
        seen.add(r["group"])
        who = r["changed_by__first_name"] or r["changed_by__username"] or ""
        what = f"{_KIND_WORDS.get(r['change_kind'], 'Changed')} {str(r['record_type']).replace('_', ' ').lower()}"
        out.append({"when": r["changed_at"], "what": what, "detail": who, "url": reverse("diary_history")})
        if len(out) >= RECENT_LIMIT:
            break
    return out


def _fees_recent(profile):
    from fees.models import Memo, Payment
    from fees.services.money import format_currency

    out = []
    for m in (Memo.objects.filter(profile=profile).order_by("-updated_at")
              .values("pk", "memo_number", "is_draft", "updated_at", "firm__name")[:RECENT_LIMIT]):
        label = f"Memo {m['memo_number']}" if m["memo_number"] else "Draft memo"
        out.append({"when": m["updated_at"], "what": f"{label} saved", "detail": m["firm__name"] or "",
                    "url": reverse("fees_memo_detail", args=[m["pk"]])})
    for p in Payment.objects.filter(profile=profile).order_by("-created_at").values("amount", "payee", "created_at")[:RECENT_LIMIT]:
        out.append({"when": p["created_at"], "what": f"Payment \u20b9{format_currency(p['amount'])} recorded", "detail": p["payee"] or "",
                    "url": reverse("fees_feebook")})
    return out


def _investments_recent(profile):
    from investments.models import InvestmentHistory

    out = []
    seen = set()
    for r in (InvestmentHistory.objects.filter(profile=profile).order_by("-changed_at", "-id")
              .values("summary", "changed_at", "group", "changed_by__first_name", "changed_by__username")[:20]):
        if r["group"] and r["group"] in seen:
            continue
        seen.add(r["group"])
        out.append({"when": r["changed_at"], "what": r["summary"] or "Changed a record",
                    "detail": r["changed_by__first_name"] or r["changed_by__username"] or "", "url": reverse("investments_history")})
        if len(out) >= RECENT_LIMIT:
            break
    return out


def _backups_recent():
    from backups.models import BackupLog

    out = []
    for r in BackupLog.objects.order_by("-started_at").values("kind", "success", "started_at")[:3]:
        word = "Backup" if "restore" not in r["kind"] else "Restore"
        out.append({"when": r["started_at"], "what": f"{word} {'done' if r['success'] else 'FAILED'}", "detail": r["kind"].replace("_", " "),
                    "url": reverse("backup_list")})
    return out


# ---------------------------------------------------------------- the whole Home context

def build(request, diary_profile, fees_profile, investments_profile, names):
    """``{"cards", "recent", "quick_actions"}`` for ``diary/home.html``. ``*_profile`` are the given profiles in use (or None)."""
    user = request.user
    cards, recent, actions = {}, [], []
    programs = (
        (KEY_DIARY, diary_profile, _diary_figures, _diary_recent, "book",
         "Your subjects, topics and the judgments that matter."),
        (KEY_FEES, fees_profile, _fees_figures, _fees_recent, "receipt",
         "Memos, payments and what each firm still owes."),
        (KEY_INVESTMENTS, investments_profile, _investments_figures, _investments_recent, "chart",
         "Holdings, returns against the index, and alerts."),
    )
    for key, profile, figures, recent_fn, icon, blurb in programs:
        if profile is None:
            continue
        cards[key] = {"key": key, "icon": icon, "blurb": blurb, "figures": _safe(figures, profile, user) or []}
        tag = {KEY_DIARY: "CL", KEY_FEES: "FR", KEY_INVESTMENTS: "IN"}[key]
        for row in _safe(recent_fn, profile) or []:
            row.update(program=key, tag=tag, program_name=names.get(key, ""))
            recent.append(row)
    if user.is_admin:
        for row in _safe(_backups_recent) or []:
            row.update(program="backups", tag="BK", program_name="Backups")
            recent.append(row)
    recent.sort(key=lambda r: r["when"].timestamp() if r["when"] else 0, reverse=True)
    recent = recent[:RECENT_LIMIT]

    if fees_profile is not None and request_role(request, KEY_FEES) == ROLE_EDITOR:
        actions.append({"label": "New memo", "url": reverse("fees_memo_new"), "icon": "plus"})
        actions.append({"label": "Record a payment", "url": reverse("fees_payment_new"), "icon": "plus"})
    if diary_profile is not None and request_role(request, KEY_DIARY) == ROLE_EDITOR:
        actions.append({"label": "Add to the diary", "url": reverse("diary_home") + "?edit=1", "icon": "edit"})
    if investments_profile is not None and request_role(request, KEY_INVESTMENTS) == ROLE_EDITOR:
        actions.append({"label": "Update prices", "url": reverse("investments_dashboard"), "icon": "refresh"})
    if cards:
        actions.append({"label": "Search everything", "url": reverse("suite_search"), "icon": "search"})
    return {"cards": cards, "recent": recent, "quick_actions": actions, "backup_action": bool(user.is_admin)}
