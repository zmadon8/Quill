"""Period statistics engine for the Fee Register (T3.8, Req #6).

Ports ``getPeriodStatistics`` from ``statisticsService.ts``. Everything is
computed month by month first (so manual overrides, extras and pro-rating apply
in one place) and quarters / financial years are then sums of those months.

* ``granularity`` ``'month'`` / ``'quarter'`` need a ``financial_year`` (12
  months / 4 quarters of it).
* ``granularity`` ``'financialYear'`` iterates every FY present on or after the
  Initial-FY cutoff.

Per-week formula (confirmed in the brief): ``count * 5 / working_days``.

Query discipline (design line 75): the 12-month accumulators are built from a
small CONSTANT number of GROUP BY queries, independent of dataset size, so
Python only ever touches at most 12 x (number of FYs) accumulator rows. The
queries are:

0. the settings read (the Initial-FY cutoff);
1. memos grouped by ``financial_year`` + ``is_draft`` + calendar month, summing
   the counts and the stored ``total_fees`` column (billing basis);
2. allocations joined to their payment, grouped by the PAYMENT date's year and
   month, summing received net and received-plus-TDS (receipt basis);
3. allocations joined to NON-DRAFT memos, grouped by the MEMO's financial year
   and calendar month, summing recovered gross (billing basis);
4. all of the profile's period adjustments (one read).

That is five queries for any dataset, which the tests lock with
``assertNumQueries``.

Guard note: this module never computes a memo line fee. Per-period billed is the
stored ``Memo.total_fees`` column summed by the ORM, so the single-fee-rule grep
guard holds.
"""
from __future__ import annotations

import datetime
import math
from calendar import monthrange
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import ExtractMonth, ExtractYear

from fees.models import Allocation, FeesSettings, Memo, PeriodAdjustment
from fees.services.financial_year import derive_financial_year
from fees.services.money import round2
from fees.services.statistics._common import FY_RE, max_fy

__all__ = ["get_period_statistics"]

_ZERO = Decimal("0")

MONTH_NAMES = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

#: FY months in order, and the months of each FY quarter.
FY_MONTH_ORDER = [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3]
QUARTERS = [
    (1, "Q1 (Apr-Jun)", [4, 5, 6]),
    (2, "Q2 (Jul-Sep)", [7, 8, 9]),
    (3, "Q3 (Oct-Dec)", [10, 11, 12]),
    (4, "Q4 (Jan-Mar)", [1, 2, 3]),
]


def _pad2(n) -> str:
    return f"{int(n):02d}"


def _js_round(value) -> int:
    """Rounds half up for positive values, matching JS ``Math.round``.

    The TS pro-rating uses ``Math.round(enteredWd * curDay / daysInMonth)``.
    JS ``Math.round`` rounds a .5 tie UP (towards positive infinity), which
    differs from Python's bankers rounding, so replicate it explicitly. Working
    days are non-negative here, so rounding towards positive infinity on a tie is
    the right rule.
    """
    return int(math.floor(value + 0.5))


def _settings_initial_fy(profile) -> str:
    """Reads ``initial_financial_year`` for ``profile`` in ONE query (a read).

    Falls back to the model default if the row does not exist yet (no
    get-or-create, so this stays a pure read and does not bump the stamp).
    """
    row = (
        FeesSettings.objects.filter(profile=profile)
        .values("initial_financial_year")
        .first()
    )
    if row and row.get("initial_financial_year"):
        return row["initial_financial_year"]
    return FeesSettings._meta.get_field("initial_financial_year").get_default()


def _blank_acc():
    return {
        "num_appearances": 0,
        "num_conferences": 0,
        "num_drafts": 0,
        "amount_billed": _ZERO,
        "amount_received": _ZERO,
        "amount_received_plus_tds": _ZERO,
        "amount_recovered": _ZERO,
    }


def _build_accumulators(profile, include_drafts, cur_key):
    """Builds the ``key -> accumulator`` map from the three GROUP BY queries.

    ``key`` is ``"<financial_year>-<MM>"``. Draft memos (when ``include_drafts``)
    are attributed to ``cur_key`` (the current month), matching the TS rule that
    a draft counts as issued in the current month. Returns ``(acc, adj_rows)``.
    """
    acc = {}

    def acc_for(key):
        a = acc.get(key)
        if a is None:
            a = _blank_acc()
            acc[key] = a
        return a

    # (1) Memos: counts and billed (stored total_fees) by FY + month. Group by
    # is_draft too so drafts can be routed to the current month in Python.
    memo_qs = Memo.objects.filter(profile=profile)
    if not include_drafts:
        memo_qs = memo_qs.filter(is_draft=False)
    memo_rows = (
        memo_qs.annotate(cal_month=ExtractMonth("date"))
        .values("financial_year", "is_draft", "cal_month")
        .annotate(
            apps=Sum("num_appearances"),
            confs=Sum("num_conferences"),
            drafts=Sum("num_drafts"),
            billed=Sum("total_fees"),
        )
    )
    for r in memo_rows:
        if r["is_draft"]:
            key = cur_key
        else:
            key = f"{r['financial_year']}-{_pad2(r['cal_month'])}"
        a = acc_for(key)
        a["num_appearances"] += r["apps"] or 0
        a["num_conferences"] += r["confs"] or 0
        a["num_drafts"] += r["drafts"] or 0
        a["amount_billed"] = round2(a["amount_billed"] + (r["billed"] or _ZERO))

    # (2) Received (receipt basis): by the PAYMENT date's FY + month.
    recv_rows = (
        Allocation.objects.filter(profile=profile)
        .annotate(
            pay_year=ExtractYear("payment__date_of_payment"),
            pay_month=ExtractMonth("payment__date_of_payment"),
        )
        .values("pay_year", "pay_month")
        .annotate(
            received=Sum("amount"),
            received_plus_tds=Sum("amount") + Sum("tds_amount"),
        )
    )
    for r in recv_rows:
        key = _payment_period_key(r["pay_year"], r["pay_month"])
        a = acc_for(key)
        a["amount_received"] = round2(a["amount_received"] + (r["received"] or _ZERO))
        a["amount_received_plus_tds"] = round2(
            a["amount_received_plus_tds"] + (r["received_plus_tds"] or _ZERO)
        )

    # (3) Recovered: gross paid against NON-DRAFT memos ISSUED in the period
    # (billing basis), attributed to the memo's FY + calendar month.
    recovered_rows = (
        Allocation.objects.filter(profile=profile, memo__is_draft=False)
        .annotate(cal_month=ExtractMonth("memo__date"))
        .values("memo__financial_year", "cal_month")
        .annotate(recovered=Sum("amount") + Sum("tds_amount"))
    )
    for r in recovered_rows:
        key = f"{r['memo__financial_year']}-{_pad2(r['cal_month'])}"
        a = acc_for(key)
        a["amount_recovered"] = round2(
            a["amount_recovered"] + (r["recovered"] or _ZERO)
        )

    adj_rows = list(PeriodAdjustment.objects.filter(profile=profile))
    return acc, adj_rows


def _payment_period_key(year, month) -> str:
    """The ``"<fy>-<MM>"`` period key for a payment's calendar year and month.

    The FY is derived in Python from the payment's calendar year and month (the
    rows are already grouped, so this runs on at most a few dozen rows).
    """
    start_year = year if month >= 4 else year - 1
    fy = f"{start_year}-{(start_year + 1) % 100:02d}"
    return f"{fy}-{_pad2(month)}"


def _per_week(count, working_days) -> Decimal:
    """``round2(count * 5 / working_days)`` or 0 when working days are not positive."""
    if working_days > 0:
        return round2((Decimal(str(count)) * 5) / Decimal(str(working_days)))
    return _ZERO


def get_period_statistics(profile, granularity, financial_year, options=None, now=None):
    """Period metrics by month, quarter or financial year (ports ``getPeriodStatistics``).

    ``options`` (all snake_case, all optional):

    * ``pro_rate_current_month`` (default True): pro-rate the current month's
      working days to the elapsed fraction.
    * ``exclude_future_months`` (default True): future months contribute 0
      effective working days.
    * ``exclude_current_month`` (default False): drop the current month from a
      ``'month'`` listing.
    * ``include_drafts`` (default False): count draft memos in the current month.
    * ``min_financial_year``: a lower FY bound; the effective cutoff is the later
      of this and the settings Initial FY (``maxFy``).

    ``now`` defaults to ``datetime.date.today()`` and is injectable for tests.

    Returns ``{"granularity", "financial_year", "periods": [...]}`` where each
    period carries the same keys as the TS ``StatPeriod`` (snake_case).
    """
    options = options or {}
    pro_rate = options.get("pro_rate_current_month", True)
    exclude_future = options.get("exclude_future_months", True)
    exclude_current = options.get("exclude_current_month", False)
    include_drafts = options.get("include_drafts", False)

    initial_fy = _settings_initial_fy(profile)
    min_financial_year = max_fy(options.get("min_financial_year"), initial_fy)

    if granularity != "financialYear" and not financial_year:
        raise ValueError(
            "financial_year is required for month / quarter granularity"
        )

    if now is None:
        now = datetime.date.today()
    if isinstance(now, datetime.datetime):
        now = now.date()
    cur_year = now.year
    cur_month = now.month
    cur_day = now.day
    cur_fy = derive_financial_year(now)
    cur_key = f"{cur_fy}-{_pad2(cur_month)}"

    acc, adj_rows = _build_accumulators(profile, include_drafts, cur_key)
    adj_by_key = {
        f"{r.financial_year}-{_pad2(r.month)}": r for r in adj_rows
    }

    def resolve_working_days(cal_month, cal_year, entered_wd):
        """Working days for per-week math: future 0, current pro-rated, past as entered."""
        is_current = cal_year == cur_year and cal_month == cur_month
        is_future = cal_year > cur_year or (
            cal_year == cur_year and cal_month > cur_month
        )
        if is_future:
            eff = entered_wd if not exclude_future else 0
            return eff, is_current, is_future, 0
        if is_current and pro_rate:
            dim = monthrange(cal_year, cal_month)[1]
            done = _js_round(entered_wd * (cur_day / dim))
            return done, is_current, is_future, done
        return entered_wd, is_current, is_future, entered_wd

    def cal_year_for_fy_month(fy, cal_month):
        first = int(fy[:4])
        return first if cal_month >= 4 else first + 1

    def with_ratios(period, eff_wd):
        """Fills the derived ratios once a period's base figures are final."""
        days_completed = period.get("days_completed") or 0
        billed = period["amount_billed"]
        recovered = period["amount_recovered"]
        period["appearances_per_week"] = _per_week(period["num_appearances"], eff_wd)
        period["conferences_per_week"] = _per_week(period["num_conferences"], eff_wd)
        period["drafts_per_week"] = _per_week(period["num_drafts"], eff_wd)
        period["fees_per_week"] = _per_week(billed, eff_wd)
        period["percent_recovered"] = (
            round2((recovered / billed) * 100) if billed > 0 else _ZERO
        )
        period["fees_per_day"] = (
            round2(billed / Decimal(str(days_completed))) if days_completed > 0 else _ZERO
        )
        return period

    def month_part(fy, month):
        """One month's final period dict (overrides, extras, pro-rating applied)."""
        key = f"{fy}-{_pad2(month)}"
        a = acc.get(key) or _blank_acc()
        adj = adj_by_key.get(key)
        entered = (adj.working_days if adj else 0) or 0
        eff_wd, is_current, is_future, days_completed = resolve_working_days(
            month, cal_year_for_fy_month(fy, month), entered
        )
        overridden = []

        def pick(computed, ov, name):
            if ov is not None:
                overridden.append(name)
                return ov
            return computed

        extra_app = (adj.extra_appearances if adj else 0) or 0
        extra_conf = (adj.extra_conferences if adj else 0) or 0
        extra_draft = (adj.extra_drafts if adj else 0) or 0
        period = {
            "key": key,
            "label": MONTH_NAMES[month - 1],
            "financial_year": fy,
            "month": month,
            "is_current_month": is_current,
            "is_future": is_future,
            "days_completed": days_completed,
            "num_appearances": pick(
                a["num_appearances"] + extra_app,
                adj.ov_appearances if adj else None,
                "num_appearances",
            ),
            "num_conferences": pick(
                a["num_conferences"] + extra_conf,
                adj.ov_conferences if adj else None,
                "num_conferences",
            ),
            "num_drafts": pick(
                a["num_drafts"] + extra_draft,
                adj.ov_drafts if adj else None,
                "num_drafts",
            ),
            "extra_appearances": extra_app,
            "extra_conferences": extra_conf,
            "extra_drafts": extra_draft,
            "amount_billed": pick(
                a["amount_billed"], adj.ov_billed if adj else None, "amount_billed"
            ),
            "amount_received": pick(
                a["amount_received"],
                adj.ov_received if adj else None,
                "amount_received",
            ),
            "amount_received_plus_tds": pick(
                a["amount_received_plus_tds"],
                adj.ov_received_plus_tds if adj else None,
                "amount_received_plus_tds",
            ),
            "amount_recovered": a["amount_recovered"],
            # The ENTERED working days are reported; rates use the effective ones.
            "working_days": entered,
        }
        if overridden:
            period["overridden"] = overridden
        with_ratios(period, eff_wd)
        return {"period": period, "eff_wd": eff_wd}

    def months_of(fy):
        return [month_part(fy, month) for month in FY_MONTH_ORDER]

    def aggregate(parts, key, label, fy):
        """Sums month parts into one quarter / year period."""
        overridden = []
        seen = set()
        for part in parts:
            for name in part["period"].get("overridden", []):
                if name not in seen:
                    seen.add(name)
                    overridden.append(name)
        eff_wd = sum(part["eff_wd"] for part in parts)

        def s(field):
            return sum(part["period"][field] for part in parts)

        period = {
            "key": key,
            "label": label,
            "financial_year": fy,
            "month": None,
            "days_completed": eff_wd,
            "num_appearances": s("num_appearances"),
            "num_conferences": s("num_conferences"),
            "num_drafts": s("num_drafts"),
            "extra_appearances": s("extra_appearances"),
            "extra_conferences": s("extra_conferences"),
            "extra_drafts": s("extra_drafts"),
            "amount_billed": round2(s("amount_billed")),
            "amount_received": round2(s("amount_received")),
            "amount_received_plus_tds": round2(s("amount_received_plus_tds")),
            "amount_recovered": round2(s("amount_recovered")),
            # For a rolled-up period "working days" is the effective (elapsed) total.
            "working_days": eff_wd,
        }
        if overridden:
            period["overridden"] = overridden
        with_ratios(period, eff_wd)
        return period

    if granularity == "month":
        periods = [
            part["period"]
            for part in months_of(financial_year)
            if not (exclude_current and part["period"]["is_current_month"])
        ]
    elif granularity == "quarter":
        fy = financial_year
        parts = months_of(fy)
        periods = []
        for q, label, months in QUARTERS:
            q_parts = [p for p in parts if p["period"]["month"] in months]
            periods.append(aggregate(q_parts, f"{fy}-Q{q}", label, fy))
    else:
        fy_set = set()
        for k in acc.keys():
            fy_set.add(k[:-3])
        for r in adj_rows:
            fy_set.add(r.financial_year)
        fys = [
            fy
            for fy in fy_set
            if FY_RE.match(fy) and (not min_financial_year or fy >= min_financial_year)
        ]
        # FY labels sort chronologically; we want descending (newest first).
        fys.sort(reverse=True)
        periods = [aggregate(months_of(fy), fy, fy, fy) for fy in fys]

    return {
        "granularity": granularity,
        "financial_year": financial_year,
        "periods": periods,
    }
