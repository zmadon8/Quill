"""The Dashboard panels beside the KPI boxes (owner round 2026-11): billed by month this financial year and who owes the most,
plus the three figures the suite Home page shows for the Fee Register.

Billed by month is one GROUP BY over the stored ``Memo.total_fees`` (the single fee rule: nothing is recomputed here). Who owes
the most reuses ``outstanding.list_outstanding_by_firm``. Both are cached in ``StatsCache`` until the data changes or the day
turns, like the KPI boxes, so a warm Dashboard costs a cache read.
"""
import datetime
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import ExtractMonth

from fees.services import outstanding, stats_cache, stats_scope
from fees.services.dashboard import local_iso
from fees.services.financial_year import current_financial_year
from fees.services.money import round2
from fees.services.statistics.periods import FY_MONTH_ORDER, MONTH_NAMES, month_working_days
from fees.services.statistics.projection import project_months

TOP_OWERS = 5


def _today(now):
    if now is None:
        return datetime.date.today()
    return now.date() if isinstance(now, datetime.datetime) else now


def billed_by_month(profile, now=None):
    """[{label, month, amount (str), is_current, is_future}] for April to March of the current financial year."""
    today = _today(now)
    fy = current_financial_year(today)
    rows = (
        stats_scope.memos(profile).filter(is_draft=False, financial_year=fy)
        .annotate(cal_month=ExtractMonth("date")).values("cal_month").annotate(billed=Sum("total_fees")).order_by()
    )
    by_month = {r["cal_month"]: r["billed"] or Decimal("0") for r in rows}
    start_year = int(fy[:4])
    out = []
    for month in FY_MONTH_ORDER:
        year = start_year if month >= 4 else start_year + 1
        is_current = (year, month) == (today.year, today.month)
        out.append({
            "label": MONTH_NAMES[month - 1], "month": month, "amount": str(by_month.get(month, Decimal("0"))),
            "is_current": is_current, "is_future": (year, month) > (today.year, today.month),
        })
    return fy, out


def project_billed(profile, fy, months, now=None):
    """Adds the projected part to each month of ``billed_by_month`` (Projected Totals): ``extra`` (str) is what is still to
    come in that month at the pace so far (the rest of the current month, all of a future month, 0 for a month already over),
    and returns the projected total for the year (str), or None when no working day is completed yet."""
    days = month_working_days(profile, fy, now)
    plan = project_months([Decimal(m["amount"]) for m in months], days)
    for i, m in enumerate(months):
        m["extra"] = str(round2(plan["months"][i]["extra"])) if plan else "0"
    return str(plan["projected"]) if plan else None


#: The Dashboard's month chart (owner round 2026-11): (id, label, the period key, is money). Billed reads the memos directly; the rest
#: come from the Statistics period engine, so they match the Statistics page (Received by payment date, Appearances with the extras).
PANEL_CHARTS = (
    ("billed", "Billed", "amount_billed", True),
    ("received", "Received", "amount_received", True),
    ("received_tds", "Received + TDS", "amount_received_plus_tds", True),
    ("appearances", "Appearances", "num_appearances", False),
)
PANEL_CHART_IDS = tuple(c[0] for c in PANEL_CHARTS)


def by_month(profile, chart, now=None):
    """``(fy, months, projected)`` for a chart other than Billed: the months as ``billed_by_month`` gives them (``amount`` the figure,
    a string) with the projected part (``extra``) and the projected year (a string, or None before a working day is completed)."""
    from fees.services.statistics import get_period_statistics

    today = _today(now)
    fy = current_financial_year(today)
    _id, _label, key, money = next(c for c in PANEL_CHARTS if c[0] == chart)
    periods = get_period_statistics(profile, "month", fy, {"exclude_future_months": True, "pro_rate_current_month": True}, today)["periods"]
    values = [Decimal(str(p[key] or 0)) for p in periods]
    plan = project_months(values, [(p["working_days"], p["days_completed"]) for p in periods], money)
    months = []
    for i, p in enumerate(periods):
        extra = plan["months"][i]["extra"] if plan else Decimal("0")
        months.append({"label": p["label"], "month": p["month"], "amount": str(values[i]),
                       "extra": str(round2(extra) if money else extra.quantize(Decimal("0.1"))),
                       "is_current": bool(p.get("is_current_month")), "is_future": bool(p.get("is_future"))})
    return fy, months, (str(plan["projected"]) if plan else None)


def _owers(profile):
    rows = outstanding.list_outstanding_by_firm(profile, {"stats_only": True}, "amount")
    total = sum((r["outstanding"] for r in rows), Decimal("0"))
    top = [{"firm_id": r["firm_id"], "firm_name": r["firm_name"], "outstanding": str(r["outstanding"]), "memo_count": r["memo_count"]}
           for r in rows[:TOP_OWERS]]
    return top, total, len(rows)


def get_panels(profile, now=None, chart="billed"):
    """The cached Dashboard panels: {fy, months, max, owers, outstanding_total, firm_count, chart, chart_label, money}. Money values are
    strings. ``chart`` picks the month chart (``PANEL_CHARTS``; Billed when unknown)."""
    today = _today(now)
    chart = chart if chart in PANEL_CHART_IDS else "billed"
    _id, chart_label, _key, money = next(c for c in PANEL_CHARTS if c[0] == chart)

    def compute():
        if chart == "billed":
            fy, months = billed_by_month(profile, today)
            projected = project_billed(profile, fy, months, today)
        else:
            fy, months, projected = by_month(profile, chart, today)
        top, total, firms = _owers(profile)
        biggest = max((Decimal(m["amount"]) + Decimal(m["extra"]) for m in months), default=Decimal("0"))
        return {"fy": fy, "months": months, "max": str(biggest), "projected": projected, "owers": top,
                "outstanding_total": str(total), "firm_count": firms}

    params = {"view": "panels", "today": local_iso(today)}
    if chart != "billed":
        params["chart"] = chart
    payload = stats_cache.get_or_compute(profile, "dashboard", params, compute, today_sensitive=True)
    payload.update(chart=chart, chart_label=chart_label, money=money,
                   charts=[(c[0], c[1]) for c in PANEL_CHARTS])
    biggest = Decimal(payload["max"]) or Decimal("1")
    for m in payload["months"]:
        amount = Decimal(m["amount"])
        extra = Decimal(m.get("extra") or "0")
        m["amount"] = amount
        m["extra"] = extra
        m["height"] = int(round(amount / biggest * 100)) if amount > 0 else 0
        # The projected part sits on top of the actual one (hatched); the two heights add up to at most 100.
        m["extra_height"] = min(int(round((amount + extra) / biggest * 100)) - m["height"], 100 - m["height"]) if extra > 0 else 0
        m["projected"] = amount + extra
    payload["projected"] = Decimal(payload["projected"]) if payload.get("projected") else None
    for row in payload["owers"]:
        row["outstanding"] = Decimal(row["outstanding"])
    total = Decimal(payload["outstanding_total"])
    payload["outstanding_total"] = total
    for row in payload["owers"]:
        row["share"] = int(round(row["outstanding"] / total * 100)) if total > 0 else 0
    return payload


def home_figures(profile, now=None):
    """The suite Home card: memos this financial year, total outstanding, draft memos. Cached like the panels."""
    today = _today(now)

    def compute():
        fy = current_financial_year(today)
        drafts = stats_scope.memos(profile).filter(is_draft=True).count()
        memos_fy = stats_scope.memos(profile).filter(is_draft=False, financial_year=fy).count()
        _top, total, _firms = _owers(profile)
        return {"fy": fy, "memos_fy": memos_fy, "drafts": drafts, "outstanding": str(total)}

    payload = stats_cache.get_or_compute(profile, "dashboard", {"view": "home", "today": local_iso(today)}, compute, today_sensitive=True)
    payload["outstanding"] = Decimal(payload["outstanding"])
    return payload
