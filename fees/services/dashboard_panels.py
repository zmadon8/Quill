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

from fees.models import Memo
from fees.services import outstanding, stats_cache
from fees.services.dashboard import local_iso
from fees.services.financial_year import current_financial_year
from fees.services.statistics.periods import FY_MONTH_ORDER, MONTH_NAMES

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
        Memo.objects.filter(profile=profile, is_draft=False, financial_year=fy)
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


def _owers(profile):
    rows = outstanding.list_outstanding_by_firm(profile, {}, "amount")
    total = sum((r["outstanding"] for r in rows), Decimal("0"))
    top = [{"firm_id": r["firm_id"], "firm_name": r["firm_name"], "outstanding": str(r["outstanding"]), "memo_count": r["memo_count"]}
           for r in rows[:TOP_OWERS]]
    return top, total, len(rows)


def get_panels(profile, now=None):
    """The cached Dashboard panels: {fy, months, max, owers, outstanding_total, firm_count}. Money values are strings."""
    today = _today(now)

    def compute():
        fy, months = billed_by_month(profile, today)
        top, total, firms = _owers(profile)
        biggest = max((Decimal(m["amount"]) for m in months), default=Decimal("0"))
        return {"fy": fy, "months": months, "max": str(biggest), "owers": top, "outstanding_total": str(total), "firm_count": firms}

    payload = stats_cache.get_or_compute(profile, "dashboard", {"view": "panels", "today": local_iso(today)}, compute, today_sensitive=True)
    biggest = Decimal(payload["max"]) or Decimal("1")
    for m in payload["months"]:
        amount = Decimal(m["amount"])
        m["amount"] = amount
        m["height"] = int(round(amount / biggest * 100)) if amount > 0 else 0
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
        drafts = Memo.objects.filter(profile=profile, is_draft=True).count()
        memos_fy = Memo.objects.filter(profile=profile, is_draft=False, financial_year=fy).count()
        _top, total, _firms = _owers(profile)
        return {"fy": fy, "memos_fy": memos_fy, "drafts": drafts, "outstanding": str(total)}

    payload = stats_cache.get_or_compute(profile, "dashboard", {"view": "home", "today": local_iso(today)}, compute, today_sensitive=True)
    payload["outstanding"] = Decimal(payload["outstanding"])
    return payload
