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

def _diary_figures(profile):
    from diary.models import Subject
    from diary.views import item_counts_by_subject

    counts = item_counts_by_subject(profile)
    live = set(Subject.objects.filter(profile=profile, deleted_at__isnull=True).values_list("pk", flat=True))
    items = sum(n for pk, (n, _f) in counts.items() if pk in live)
    flagged = sum(f for pk, (_n, f) in counts.items() if pk in live)
    return [("Subjects", f"{len(live):,}"), ("Items", f"{items:,}"), ("Flagged", f"{flagged:,}")]


def _fees_figures(profile):
    from fees.services import dashboard_panels
    from fees.services.money import format_money

    figures = dashboard_panels.home_figures(profile)
    return [("Memos this year", f"{figures['memos_fy']:,}"), ("Outstanding", "\u20b9" + format_money(figures["outstanding"], unit="short")),
            ("Drafts", f"{figures['drafts']:,}")]


def _investments_figures(profile, user=None):
    from investments.money_auto import format_rupees
    from investments.services import alerts, dashboard

    period = getattr(user, "investments_period", "all") or "all"
    totals = dashboard.peek_totals(profile, period=period)
    n_alerts = alerts.peek_count(profile)
    value = format_rupees(totals["value"]) if totals else "\u2013"
    xirr = f"{totals['xirr'] * 100:.1f}%" if totals and totals.get("xirr") is not None else "\u2013"
    return [("Value", value), ("XIRR" if period == "all" else f"XIRR {period.upper()}", xirr), ("Alerts", "\u2013" if n_alerts is None else f"{n_alerts:,}")]


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
        cards[key] = {"key": key, "icon": icon, "blurb": blurb, "figures": (_safe(figures, profile, user) if figures is _investments_figures else _safe(figures, profile)) or []}
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
