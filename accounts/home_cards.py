"""The suite Home page's cards (owner round 2026-11): a few live figures per program, recent activity across the programs and
quick actions.

Only the profile the user is working in per program counts (the one the Home link opens), and only when it was given to them
on the Users screen, so the page stays the same size however many profiles exist. Each program is built in its own try block:
a failure shows the card without figures and never breaks Home. Nothing here starts a heavy calculation: the Investments
figures are read from its cache only (they appear once the Overview has been opened since the last change). The extra Investments
items below the cards follow the same rule; the extra Fee Register items do not: its Dashboard figures are worked out (and cached) on
Home when chosen, and its panels and recent matters are small live queries.
"""
import logging
from decimal import Decimal

from django.urls import reverse

from accounts.models import ROLE_EDITOR
from accounts.profiles import request_role
from accounts.suite import KEY_DIARY, KEY_FEES, KEY_INVESTMENTS
from investments.money_auto import format_indian

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
    values = {"subjects": format_indian(len(live), 0), "items": format_indian(items, 0), "flagged": format_indian(flagged, 0), "clean": format_indian(items - flagged, 0),
              "per_subject": format_indian(items / len(live), 1) if live else DASH}
    labels = dict(DIARY_METRICS)
    return [(labels[k], values[k]) for k in chosen_metrics(user, KEY_DIARY)]


def _fees_figures(profile, user=None):
    from fees.services import dashboard_panels
    from fees.services.money import format_money

    keys = chosen_metrics(user, KEY_FEES)
    labels = dict(FEES_METRICS)
    figures = dashboard_panels.home_figures(profile)
    values = {"memos_fy": format_indian(figures['memos_fy'], 0), "outstanding": "\u20b9" + format_money(figures["outstanding"], unit="short"),
              "drafts": format_indian(figures['drafts'], 0), "fy": str(figures.get("fy", DASH))}
    if "memos_total" in keys:
        from fees.models import Memo

        values["memos_total"] = format_indian(Memo.objects.filter(profile=profile, is_draft=False).count(), 0)
    if "payments" in keys:
        from fees.models import Payment

        values["payments"] = format_indian(Payment.objects.filter(profile=profile).count(), 0)
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
        values["alerts"] = DASH if n_alerts is None else format_indian(n_alerts, 0)
    labels = {"value": "Value", "xirr": "XIRR" + suffix, "alerts": "Alerts", "invested": "Invested", "gain": "Gain" + suffix}
    return [(labels[k], values[k]) for k in keys]


# ---------------------------------------------------------------- details below the cards
#
# Besides the card figures a user may add, per program, any item of the Fee Register Dashboard or the Investments Overview to the area
# below the cards (My settings > Display, stored in User.home_details as {"fees": [ids], "investments": [ids]}). Nothing chosen means
# nothing extra. The chosen ids are kept in catalogue order. Each section is plain data (kind, title, rows) drawn by
# templates/diary/_home_details.html. Not offered: the Overview's value chart and its insights (they are not kept in the cache the
# Home page may read, and working them out would start a calculation).

FEES_EXTRA_DETAILS = [("billed_by_month", "Billed by month (this financial year)"), ("who_owes", "Who owes the most"),
                      ("recent_matters", "Recently billed matters")]
INVESTMENTS_EXTRA_DETAILS = [("over_time", "Over time (the period table)"), ("allocation", "Allocation by asset class")]
DETAIL_PROGRAMS = (KEY_FEES, KEY_INVESTMENTS)
NOT_READY = "Open the Overview once to fill this in."


def details_catalogue(program):
    """``[(id, label)]`` of the items offered for ``program`` (the Fee Register or Investments), in the order shown."""
    if program == KEY_FEES:
        from fees.services.dashboard import KPI_LABELS

        return list(KPI_LABELS.items()) + FEES_EXTRA_DETAILS
    if program == KEY_INVESTMENTS:
        from investments.services.overview import BOXES

        return [(b, label.replace("{index}", "Index")) for b, label, _h in BOXES] + INVESTMENTS_EXTRA_DETAILS
    return []


def chosen_details(user, program):
    """The ids of the extra items to show for ``program``: the user's valid choice, unknown and repeated ids dropped, in catalogue order."""
    stored = getattr(user, "home_details", None)
    stored = stored.get(program) if isinstance(stored, dict) else None
    if not isinstance(stored, list):
        return []
    picked = {k for k in stored if isinstance(k, str)}
    return [k for k, _label in details_catalogue(program) if k in picked]


def _fees_details(profile, user):
    from fees.pages import overdue_on
    from fees.services import dashboard, dashboard_panels, memo_lists
    from fees.services import settings as settings_service
    from fees.services.money import format_money

    keys = chosen_details(user, KEY_FEES)
    if not keys:
        return []
    config = settings_service.get_settings(profile)
    unit = config.get("money_unit", "full")

    def money(value):
        return "\u20b9" + format_money(Decimal(str(value)), unit=unit)

    sections = []
    ids = [k for k in keys if k in dashboard.KPI_LABELS and (k != "amount_overdue" or overdue_on(config))]
    chosen_kpis = [k for k in keys if k in dashboard.KPI_LABELS]
    notes = []
    if chosen_kpis and not config.get("statistics_enabled", True):
        notes.append("The Dashboard figures are switched off in the Fee Register settings.")
    elif "amount_overdue" in chosen_kpis and "amount_overdue" not in ids:
        notes.append("Amount overdue is not shown because overdue is switched off in the Fee Register settings.")
    if notes:
        sections.append({"kind": "note", "title": "Fee Register: Dashboard", "text": " ".join(notes), "url": reverse("fees_dashboard")})
    if ids and config.get("statistics_enabled", True):
        values = dashboard.get_dashboard_kpis(profile, settings={**config, "dashboard_kpis": ",".join(ids)})
        items = [(dashboard.KPI_LABELS[k], money(values[k]) if isinstance(values[k], str) else format_indian(values[k], 0)) for k in ids]
        sections.append({"kind": "kpis", "title": "Fee Register: Dashboard", "items": items, "url": reverse("fees_dashboard")})
    if "billed_by_month" in keys or "who_owes" in keys:
        panels = dashboard_panels.get_panels(profile)
        if "billed_by_month" in keys:
            bars = [{"label": m["label"], "height": m["height"], "current": m["is_current"], "future": m["is_future"],
                     "amount": money(m["amount"])} for m in panels["months"]]
            sections.append({"kind": "bars", "title": f"Billed by month, {panels['fy']}", "bars": bars, "url": reverse("fees_dashboard")})
        if "who_owes" in keys:
            rows = [{"name": o["firm_name"], "detail": f"{o['memo_count']} memo{'' if o['memo_count'] == 1 else 's'}",
                     "amount": money(o["outstanding"]), "url": reverse("fees_outstanding_detail") + f"?firm={o['firm_id']}"}
                    for o in panels["owers"]]
            sections.append({"kind": "list", "title": "Who owes the most", "rows": rows, "empty": "Nothing is outstanding.",
                             "url": reverse("fees_outstanding")})
    if "recent_matters" in keys:
        rows = [{"name": r["matter_name"], "detail": f"{r['firm_name']} \u00b7 {r['memo_count']} memo{'' if r['memo_count'] == 1 else 's'}",
                 "amount": str(r.get("last_memo_number") or ""), "url": reverse("fees_matter_detail", args=[r["matter_id"]])}
                for r in memo_lists.list_recent_matters(profile, limit=5)]
        sections.append({"kind": "list", "title": "Recently billed matters", "rows": rows, "empty": "No memos yet.",
                         "url": reverse("fees_dashboard")})
    return sections


def _investments_details(profile, user):
    from investments.money_auto import format_rupees
    from investments.services import dashboard, overview

    keys = chosen_details(user, KEY_INVESTMENTS)
    if not keys:
        return []
    url = reverse("investments_dashboard")
    period = getattr(user, "investments_period", "all") or "all"
    payload = dashboard.peek_payload(profile, period=period)  # the cache only, never a calculation
    if payload is None:
        return [{"kind": "note", "title": "Investments: Overview", "text": NOT_READY, "url": url}]
    totals = payload["totals"]
    suffix = "" if period == "all" else f" ({period.upper()})"

    def pct(value, signed=False):
        if value is None:
            return DASH
        text = f"{abs(value) * 100:.2f}%"
        return ("+" if value > 0 else "\u2212" if value < 0 else "") + text if signed else ("\u2212" if value < 0 else "") + text

    def rupees(value, signed=False):
        return DASH if value is None else format_rupees(value, signed=signed)

    figures = {"value": rupees(totals["value"]), "invested": rupees(totals["invested"]),
               "gain": rupees(totals["gain"], True) + (f" ({pct(totals.get('gain_pct'), True)})" if totals.get("gain_pct") is not None else ""),
               "xirr": pct(totals.get("xirr")), "index_xirr": pct(totals.get("index_xirr")), "alpha": pct(totals.get("alpha"), True),
               "dividends": rupees(totals["dividends"]), "count": format_indian(totals.get('count', 0), 0)}
    labels = {b: label.replace("{index}", "Index") for b, label, _h in overview.BOXES}
    with_period = {"gain", "xirr", "index_xirr", "alpha"}
    items = [(labels[k] + (suffix if k in with_period else ""), figures[k]) for k in keys if k in figures]
    sections = []
    if items:
        sections.append({"kind": "kpis", "title": "Investments: Overview", "items": items, "url": url})
    if "over_time" in keys:
        table = payload["overview"]
        formats = {"pct": lambda v: pct(v), "pct_signed": lambda v: pct(v, True), "money": lambda v: rupees(v),
                   "money_signed": lambda v: rupees(v, True)}
        rows = [[r["label"].replace("{index}", "Index")] + [DASH if v is None else formats.get(r["fmt"], pct)(v) for v in r["values"]]
                for r in table.get("rows", [])]
        if rows:
            sections.append({"kind": "table", "title": "Investments over time", "head": ["Figure"] + [p["label"] for p in table["periods"]],
                             "rows": rows, "url": url})
        else:
            sections.append({"kind": "note", "title": "Investments over time", "text": NOT_READY, "url": url})
    if "allocation" in keys:
        rows = [{"name": label, "detail": "", "amount": pct(share), "url": ""} for label, _value, share in payload["allocation"]]
        sections.append({"kind": "list", "title": "Allocation by asset class", "rows": rows, "empty": "Nothing is held.", "url": url})
    return sections


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
    """``{"cards", "recent", "quick_actions", "details"}`` for ``diary/home.html``. ``*_profile`` are the given profiles in use (or None)."""
    user = request.user
    cards, recent, actions, details = {}, [], [], []
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
        if key in DETAIL_PROGRAMS:
            sections = _safe(_fees_details if key == KEY_FEES else _investments_details, profile, user) or []
            if sections:
                details.append({"program": key, "program_name": names.get(key, ""), "sections": sections})
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
    return {"cards": cards, "recent": recent, "quick_actions": actions, "details": details, "backup_action": bool(user.is_admin)}
