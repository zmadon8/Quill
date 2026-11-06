"""Dashboard KPI and headline-summary service for the Fee Register (T3.7, R-RD-1).

Ports ``dashboardService.ts`` (``getDashboardSummary``, ``getDashboardKpis``,
``localIso`` and the internal ``statsAppearances`` helper) to the Django ORM,
profile-scoped. The dashboard shows at-a-glance figures for the Overview landing
page; every money result goes through ``fees.services.money.round2`` and nothing
here re-derives a memo line fee (the single fee rule lives in
``fees.services.memo_fees``; per-memo totals come from the stored
``Memo.total_fees`` column or ``memo_fees.effective_total_fees``), so the
single-fee-rule grep guard in ``test_memo_fees`` holds.

Appearances are NOT taken from the raw memo ``num_appearances`` sum. They come
from the statistics period engine (``fees.services.statistics.get_period_statistics``)
via :func:`stats_appearances`, so the dashboard's "appearances this month / year"
ALWAYS agree with the Statistics page (which includes the manual extras entered
in Edit Statistics). This mirrors the TypeScript source, which sourced the
dashboard appearances from ``getPeriodStatistics`` for the same reason.

Local calendar date (TIME_ZONE is Asia/Kolkata): all figures use the LOCAL date
so a late-evening entry near a month or financial-year boundary is attributed to
the right period. ``now`` defaults to ``datetime.date.today()`` (matching the
sibling fee services) and is injectable for deterministic tests.
``local_iso(now)`` returns the ``YYYY-MM-DD`` local calendar date.

THE DASHBOARD-KPIS SWITCH (acceptance test, zero queries when off)
------------------------------------------------------------------
``get_dashboard_kpis(profile, now=None, settings=None)`` must perform ZERO
database queries when ``dashboard_kpis_enabled`` is False. Because
``settings.get_settings`` itself issues a query (it get-or-creates the row), the
contract is: the caller MAY pass an already-read ``settings`` dict as the
``settings`` keyword. When ``settings`` is provided the function does NOT read it
from the database, so with ``settings={'dashboard_kpis_enabled': False}`` the
switch short-circuits and returns the empty catalogue (:data:`EMPTY_KPIS`)
BEFORE any query, including before any ``stats_cache.get_or_compute`` call. The
acceptance test therefore does::

    with self.assertNumQueries(0):
        result = get_dashboard_kpis(profile, now, settings={"dashboard_kpis_enabled": False})

and ``result`` is ``EMPTY_KPIS`` (every KPI id mapped to 0). When ``settings`` is
None the function reads it with ``get_settings`` (one query) and then applies the
same switch, so a caller that does not pre-read still gets the gated behaviour,
just not at zero queries (the get-or-create read is unavoidable there).

``statistics_enabled`` is honoured the same way: the appearances figures come
from the statistics engine, so when ``statistics_enabled`` is False the
appearances KPIs are reported as 0 and the engine is not called. The switch is
read from the same ``settings`` dict (pre-read or fetched) and checked before the
appearances lookup.

CACHING
-------
``get_dashboard_kpis`` memoises its result in the ``StatsCache`` table via
``stats_cache.get_or_compute(profile, kind="dashboard", params=..., compute,
today_sensitive=True)``. It is ``today_sensitive`` because every figure depends
on the current local date (this month, this FY and the rolling last-30-days
window). The switch short-circuit happens BEFORE ``get_or_compute`` so the
zero-query path never touches the cache. ``params`` is
``{"view": "kpis", "today": local_iso(now)}`` so a new day is a fresh key as well
as a fresh ``valid_on`` stamp.

JSON money representation: ``get_or_compute`` JSON-serialises the payload, so the
cached KPI catalogue stores every money value as a STRING (``str(Decimal)``) and
every count as an int. On a hit the stored strings are returned verbatim; callers
that need a ``Decimal`` reconstruct it with ``Decimal(value)``. Strings (not
floats) are used so the two-decimal money value round-trips exactly without
binary-float drift. ``get_dashboard_summary`` is a pure computation and is not
itself cached (it is cheap relative to the KPI catalogue and is also called
directly by callers that want ``Decimal`` figures); the KPI catalogue is the one
cached payload.
"""
from __future__ import annotations

import calendar
import datetime
from decimal import Decimal

from django.db.models import DecimalField, Sum, Value
from django.db.models.functions import Coalesce

from fees.models import Allocation, Memo
from fees.services import memo_fees, stats_cache
from fees.services.financial_year import derive_financial_year
from fees.services.money import round2
from fees.services.settings import get_settings
from fees.services.statistics import get_period_statistics

__all__ = [
    "EMPTY_KPIS",
    "KPI_IDS",
    "local_iso",
    "get_dashboard_summary",
    "get_dashboard_kpis",
    "selected_kpi_ids",
    "KPI_GROUPS",
    "KPI_DISPLAY_GROUPS",
    "KPI_LABELS",
    "order_kpis",
]

_ZERO = Decimal("0")

#: The status passed to ``compute_is_overdue`` for an unpaid memo (every memo
#: reaching that check is unpaid: gross paid strictly below the total).
_UNPAID = "Unpaid"

#: Every KPI id in the catalogue, in the TypeScript ``getDashboardKpis`` order.
#: Money ids are serialised as strings, count ids as ints, both in the result.
KPI_IDS = (
    "billed_this_month",
    "billed_this_year",
    "billed_last30",
    "received_this_month",
    "received_this_year",
    "received_last30",
    "memos_this_month",
    "memos_this_year",
    "memos_last30",
    "appearances_this_month",
    "appearances_this_year",
    "appearances_last30",
    "conferences_this_month",
    "conferences_this_year",
    "conferences_last30",
    "drafts_this_year",
    "drafts_last30",
    "total_outstanding",
    "amount_overdue",
    "memos_awaiting_payment",
    "written_off_total",
    "draft_memos_count",
    "draft_memos_total",
)

#: Which computation produces each KPI id. ``get_dashboard_kpis`` runs only the groups that the
#: selected ids need, so an unselected group issues no queries (owner items 2.4 and 2.12):
#: ``summary`` is the one pass over non-draft memos (``get_dashboard_summary``), ``activity`` the
#: pass over all memos for counts and last-30-day billing, ``received30`` one allocation
#: aggregate, ``appearances`` the statistics engine.
KPI_GROUPS = {
    "billed_this_month": "summary",
    "billed_this_year": "summary",
    "received_this_month": "summary",
    "received_this_year": "summary",
    "total_outstanding": "summary",
    "amount_overdue": "summary",
    "memos_awaiting_payment": "summary",
    "written_off_total": "summary",
    "billed_last30": "activity",
    "memos_this_month": "activity",
    "memos_this_year": "activity",
    "memos_last30": "activity",
    "appearances_last30": "activity",
    "conferences_this_month": "activity",
    "conferences_this_year": "activity",
    "conferences_last30": "activity",
    "drafts_this_year": "activity",
    "drafts_last30": "activity",
    "draft_memos_count": "activity",
    "draft_memos_total": "activity",
    "received_last30": "received30",
    "appearances_this_month": "appearances",
    "appearances_this_year": "appearances",
}

#: The Customise panel's groups, in display order: (group title, KPI ids). Every id in ``KPI_IDS``
#: sits in exactly one group (a test holds that).
KPI_DISPLAY_GROUPS = (
    ("Billing", ("billed_this_month", "billed_this_year", "billed_last30")),
    ("Receipts", ("received_this_month", "received_this_year", "received_last30")),
    ("Memos", ("memos_this_month", "memos_this_year", "memos_last30")),
    (
        "Appearances & work",
        (
            "appearances_this_month",
            "appearances_this_year",
            "appearances_last30",
            "conferences_this_month",
            "conferences_this_year",
            "conferences_last30",
            "drafts_this_year",
            "drafts_last30",
        ),
    ),
    (
        "Outstanding",
        (
            "total_outstanding",
            "amount_overdue",
            "memos_awaiting_payment",
            "written_off_total",
            "draft_memos_count",
            "draft_memos_total",
        ),
    ),
)

#: The words shown for each KPI id, in the boxes and in the Customise panel.
KPI_LABELS = {
    "billed_this_month": "Billed This Month",
    "billed_this_year": "Billed This Year",
    "billed_last30": "Billed (Last 30 Days)",
    "received_this_month": "Received This Month",
    "received_this_year": "Received This Year",
    "received_last30": "Received (Last 30 Days)",
    "memos_this_month": "Memos This Month",
    "memos_this_year": "Memos This Year",
    "memos_last30": "Memos (Last 30 Days)",
    "appearances_this_month": "Appearances This Month",
    "appearances_this_year": "Appearances This Year",
    "appearances_last30": "Appearances (Last 30 Days)",
    "conferences_this_month": "Conferences This Month",
    "conferences_this_year": "Conferences This Year",
    "conferences_last30": "Conferences (Last 30 Days)",
    "drafts_this_year": "Drafts (Documents) This Year",
    "drafts_last30": "Drafts (Documents), Last 30 Days",
    "total_outstanding": "Total Outstanding",
    "amount_overdue": "Amount Overdue",
    "memos_awaiting_payment": "Memos Awaiting Payment",
    "written_off_total": "Written Off",
    "draft_memos_count": "Draft Memos",
    "draft_memos_total": "Draft Memos Total",
}

#: The money KPI ids (serialised as ``str(Decimal)`` in the cached / returned
#: catalogue); every other id is a plain integer count.
_MONEY_KPIS = frozenset(
    (
        "billed_this_month",
        "billed_this_year",
        "billed_last30",
        "received_this_month",
        "received_this_year",
        "received_last30",
        "total_outstanding",
        "amount_overdue",
        "written_off_total",
        "draft_memos_total",
    )
)

#: The result returned when the dashboard-KPIs switch is OFF: every id at 0
#: (money as the string "0", counts as the int 0). A fresh dict per access so a
#: caller can never mutate the shared default.
def _empty_kpis():
    return {
        kpi: ("0" if kpi in _MONEY_KPIS else 0) for kpi in KPI_IDS
    }


#: Convenience module-level snapshot of the off-switch result (read-only use).
EMPTY_KPIS = _empty_kpis()


def selected_kpi_ids(settings):
    """The KPI ids the user chose (the comma list in ``dashboard_kpis``), in saved order.

    Unknown ids are dropped; an empty or missing selection means every KPI (the default).
    """
    chosen = [k.strip() for k in str((settings or {}).get("dashboard_kpis") or "").split(",")]
    chosen = list(dict.fromkeys(k for k in chosen if k in KPI_GROUPS))
    return chosen or list(KPI_IDS)


def order_kpis(ticked, previous=(), move=""):
    """The saved KPI order from a Customise submission.

    ``ticked`` are the ticked ids (form order); ``previous`` the order the page showed (the hidden
    ``order`` field, kept in step by the JavaScript); ``move`` an optional ``"<id>:up"`` or
    ``"<id>:down"`` from a no-JavaScript arrow button. Unticked ids drop out, newly ticked ids go to
    the end, unknown ids are ignored.
    """
    ticked = list(dict.fromkeys(k for k in ticked if k in KPI_GROUPS))
    order = [k for k in dict.fromkeys(previous) if k in ticked]
    order += [k for k in ticked if k not in order]
    kpi, _sep, direction = str(move or "").partition(":")
    if kpi in order and direction in ("up", "down"):
        i = order.index(kpi)
        j = i - 1 if direction == "up" else i + 1
        if 0 <= j < len(order):
            order[i], order[j] = order[j], order[i]
    return order


def local_iso(d) -> str:
    """The LOCAL calendar date as ``YYYY-MM-DD`` (ports ``localIso``).

    Accepts a ``date`` / ``datetime``; a ``datetime`` is reduced to its date.
    """
    if isinstance(d, datetime.datetime):
        d = d.date()
    return f"{d.year:04d}-{d.month:02d}-{d.day:02d}"


def _as_date(now):
    """Coerces ``now`` (``None`` / ``date`` / ``datetime``) to a local ``date``."""
    if now is None:
        return datetime.date.today()
    if isinstance(now, datetime.datetime):
        return now.date()
    return now


def _gross_received_between(profile, start_iso, end_iso) -> Decimal:
    """Gross allocations (amount + tds_amount) whose payment date is in ``[start, end]``.

    ONE aggregate query over the profile's allocations joined to their payment.
    The payment date is an ISO ``YYYY-MM-DD`` column, so an inclusive string range
    selects the right calendar window. Returns a two-decimal ``Decimal``.
    """
    money_field = DecimalField(max_digits=14, decimal_places=2)
    agg = (
        Allocation.objects.filter(
            profile=profile,
            payment__date_of_payment__gte=start_iso,
            payment__date_of_payment__lte=end_iso,
        )
        .aggregate(
            received=Coalesce(
                Sum("amount") + Sum("tds_amount"),
                Value(_ZERO),
                output_field=money_field,
            )
        )
    )
    return round2(agg["received"] or _ZERO)


def stats_appearances(profile, now, *, enabled=True):
    """Appearances for the current month and FY, from the statistics engine.

    Ports ``statsAppearances``: appearances come from
    ``get_period_statistics`` (the SAME engine as the Statistics page) so the
    dashboard and statistics always agree, including the manual "extras" entered
    in Edit Statistics which the raw memo counts do not carry.

    ``enabled`` gates the ``statistics_enabled`` switch: when False the engine is
    not called and ``{"month": 0, "year": 0}`` is returned (no query).
    """
    if not enabled:
        return {"month": 0, "year": 0}
    today = _as_date(now)
    fy = derive_financial_year(local_iso(today))
    opts = {"exclude_future_months": True, "pro_rate_current_month": True}
    months = get_period_statistics(profile, "month", fy, opts, today)
    years = get_period_statistics(profile, "financialYear", None, opts, today)

    month_value = 0
    for period in months["periods"]:
        if period["month"] == today.month:
            month_value = period["num_appearances"]
            break
    year_value = 0
    for period in years["periods"]:
        if period["key"] == fy:
            year_value = period["num_appearances"]
            break
    return {"month": month_value, "year": year_value}


def get_dashboard_summary(profile, now=None, settings=None, with_appearances=True):
    """The headline Dashboard figures (ports ``getDashboardSummary``).

    Reads every non-draft memo ONCE (the stored ``total_fees`` plus
    ``date`` / ``financial_year`` / ``written_off`` and the stored gross
    ``amount_paid`` column, which ``payments.recompute_paid`` maintains, read
    directly rather than via a per-row subquery, mirroring ``outstanding.py``),
    then accumulates in Python. Received figures are two aggregate queries over
    allocations by payment date, and appearances come from the statistics engine.

    Returns a dict with the snake_case ``DashboardSummary`` keys:
    ``total_outstanding``, ``received_this_month``, ``memos_awaiting_payment``,
    ``written_off_total``, ``billed_this_month``, ``billed_this_year``,
    ``appearances_this_year``, ``received_this_year`` and ``amount_overdue``.
    Every money figure is a two-decimal ``Decimal``.

    ``settings`` may be a pre-read settings dict (to avoid the get-or-create read
    and to honour the ``statistics_enabled`` switch without a second hop); when
    None it is read with ``get_settings``. ``with_appearances=False`` skips the statistics engine
    (``appearances_this_year`` is then 0); the KPI catalogue uses that and asks for appearances itself.
    """
    if settings is None:
        settings = get_settings(profile)
    overdue_days = settings.get("overdue_days") or 0
    statistics_enabled = bool(settings.get("statistics_enabled", True))

    today = _as_date(now)
    today_iso = local_iso(today)
    current_fy = derive_financial_year(today_iso)
    ym = today_iso[:7]

    rows = Memo.objects.filter(profile=profile, is_draft=False).values(
        "date",
        "financial_year",
        "written_off",
        "amount_paid",
        "total_fees",
        "num_appearances",
        "fees_per_appearance",
        "num_conferences",
        "fees_per_conference",
        "fees_misc_drafting",
        "custom_fees_appearances",
        "custom_fees_conferences",
        "custom_fees_misc",
        "custom_total_fees",
    )

    total_outstanding = _ZERO
    written_off_total = _ZERO
    memos_awaiting_payment = 0
    billed_this_month = _ZERO
    billed_this_year = _ZERO
    amount_overdue = _ZERO

    for row in rows.iterator():
        total = memo_fees.effective_total_fees(row)
        date_iso = local_iso(row["date"]) if isinstance(row["date"], datetime.date) else str(row["date"])[:10]

        if row["financial_year"] == current_fy:
            billed_this_year = round2(billed_this_year + total)
        if date_iso[:7] == ym:
            billed_this_month = round2(billed_this_month + total)

        if row["written_off"]:
            written_off_total = round2(written_off_total + total)
            continue

        outstanding = round2(total - round2(row["amount_paid"]))
        if outstanding > 0:
            total_outstanding = round2(total_outstanding + outstanding)
            memos_awaiting_payment += 1
            if memo_fees.compute_is_overdue(
                row["date"], _UNPAID, False, overdue_days, today
            ):
                amount_overdue = round2(amount_overdue + outstanding)

    last_day = calendar.monthrange(today.year, today.month)[1]
    month_end = f"{ym}-{last_day:02d}"
    received_this_month = _gross_received_between(
        profile, f"{ym}-01", month_end
    )
    fy_start_year = int(current_fy[:4])
    fy_start = f"{fy_start_year}-04-01"
    fy_end = f"{fy_start_year + 1}-03-31"
    received_this_year = _gross_received_between(profile, fy_start, fy_end)

    appearances_this_year = (
        stats_appearances(profile, today, enabled=statistics_enabled)["year"]
        if with_appearances
        else 0
    )

    return {
        "total_outstanding": total_outstanding,
        "received_this_month": received_this_month,
        "memos_awaiting_payment": memos_awaiting_payment,
        "written_off_total": written_off_total,
        "billed_this_month": billed_this_month,
        "billed_this_year": billed_this_year,
        "appearances_this_year": appearances_this_year,
        "received_this_year": received_this_year,
        "amount_overdue": amount_overdue,
    }


def _compute_activity(profile, today):
    """The ``activity`` group: counts and last-30-day billing from one pass over the memos."""
    today_iso = local_iso(today)
    start30 = local_iso(today - datetime.timedelta(days=29))
    fy = derive_financial_year(today_iso)
    ym = today_iso[:7]

    rows = Memo.objects.all().filter(profile=profile).values(
        "date",
        "financial_year",
        "is_draft",
        "written_off",
        "num_appearances",
        "fees_per_appearance",
        "num_conferences",
        "fees_per_conference",
        "fees_misc_drafting",
        "num_drafts",
        "custom_fees_appearances",
        "custom_fees_conferences",
        "custom_fees_misc",
        "custom_total_fees",
    )

    memos_this_month = memos_this_year = memos_last30 = 0
    conferences_this_month = conferences_this_year = conferences_last30 = 0
    appearances_last30 = 0
    billed_last30 = _ZERO
    drafts_this_year = drafts_last30 = 0
    draft_memos_count = 0
    draft_memos_total = _ZERO

    for row in rows.iterator():
        total = memo_fees.effective_total_fees(row)
        if row["is_draft"]:
            draft_memos_count += 1
            draft_memos_total = round2(draft_memos_total + total)
            continue
        date_iso = (
            local_iso(row["date"])
            if isinstance(row["date"], datetime.date)
            else str(row["date"])[:10]
        )
        in_month = date_iso[:7] == ym
        in_year = row["financial_year"] == fy
        in_last30 = start30 <= date_iso <= today_iso
        num_conferences = row["num_conferences"] or 0
        num_drafts = row["num_drafts"] or 0
        if in_month:
            memos_this_month += 1
            conferences_this_month += num_conferences
        if in_year:
            memos_this_year += 1
            conferences_this_year += num_conferences
            drafts_this_year += num_drafts
        if in_last30:
            memos_last30 += 1
            conferences_last30 += num_conferences
            appearances_last30 += row["num_appearances"] or 0
            drafts_last30 += num_drafts
            billed_last30 = round2(billed_last30 + total)

    return {
        "billed_last30": billed_last30,
        "memos_this_month": memos_this_month,
        "memos_this_year": memos_this_year,
        "memos_last30": memos_last30,
        "appearances_last30": appearances_last30,
        "conferences_this_month": conferences_this_month,
        "conferences_this_year": conferences_this_year,
        "conferences_last30": conferences_last30,
        "drafts_this_year": drafts_this_year,
        "drafts_last30": drafts_last30,
        "draft_memos_count": draft_memos_count,
        "draft_memos_total": draft_memos_total,
    }


def _compute_kpis(profile, today, settings, selected=None):
    """Builds the selected part of the KPI catalogue as a JSON-safe dict (money as str, counts int).

    ``today`` is already a local ``date``; ``settings`` is the resolved settings dict; ``selected`` is
    the list of KPI ids wanted (every id when None). Only the groups the selection needs are computed
    (see ``KPI_GROUPS``), so an unselected group issues no queries. Honours ``statistics_enabled``
    for the appearances figures.
    """
    selected = list(KPI_IDS) if selected is None else list(selected)
    groups = {KPI_GROUPS[kpi] for kpi in selected}
    values = {}
    if "summary" in groups:
        values.update(get_dashboard_summary(profile, today, settings=settings, with_appearances=False))
    if "activity" in groups:
        values.update(_compute_activity(profile, today))
    if "received30" in groups:
        start30 = local_iso(today - datetime.timedelta(days=29))
        values["received_last30"] = _gross_received_between(profile, start30, local_iso(today))
    if "appearances" in groups:
        appearances = stats_appearances(
            profile, today, enabled=bool(settings.get("statistics_enabled", True))
        )
        values["appearances_this_month"] = appearances["month"]
        values["appearances_this_year"] = appearances["year"]
    return _to_json_safe(values, selected)


def _to_json_safe(values, ids=KPI_IDS):
    """Serialises the KPI values for ``ids`` to JSON-safe form: money as str, counts as int."""
    out = {}
    for kpi in ids:
        value = values[kpi]
        if kpi in _MONEY_KPIS:
            out[kpi] = str(round2(value))
        else:
            out[kpi] = int(value)
    return out


def get_dashboard_kpis(profile, now=None, settings=None):
    """Every Overview KPI as an id -> value map (ports ``getDashboardKpis``).

    THE SWITCH (zero queries when off): when ``dashboard_kpis_enabled`` is False
    the function returns :data:`EMPTY_KPIS` (every id at 0) WITHOUT any database
    query, short-circuiting BEFORE ``stats_cache.get_or_compute``. To make that a
    genuine zero-query path the caller passes an already-read ``settings`` dict as
    the ``settings`` keyword (``get_settings`` itself issues a get-or-create
    query, so a function-internal read could not be zero queries). When
    ``settings`` is None it is read with ``get_settings`` (one query) and the same
    switch is applied.

    When the switch is ON the catalogue is memoised in ``StatsCache`` under
    ``kind="dashboard"`` with ``params={"view": "kpis", "today": local_iso(now)}``
    and ``today_sensitive=True`` (the figures depend on the current date). Money
    values are stored and returned as strings (``str(Decimal)``) and counts as
    ints, so the payload is JSON-serialisable; a caller needing a ``Decimal``
    reconstructs it with ``Decimal(value)``.

    "Last 30 days" is the 30 calendar days ending today inclusive, by memo date
    for billed / counts and by payment date for received. ``statistics_enabled``
    gates the appearances figures (reported 0 when off).

    Only the KPI ids the user selected (``dashboard_kpis`` in the settings, every id when none) are
    computed and returned; a group nobody selected is never queried (items 2.4 and 2.12). The
    switch-off result stays the full zeroed catalogue.
    """
    if settings is None:
        settings = get_settings(profile)
    if not settings.get("dashboard_kpis_enabled", True):
        return _empty_kpis()

    today = _as_date(now)
    selected = selected_kpi_ids(settings)
    # The selected ids, in their saved order, are part of the cache key, so a changed selection or
    # order never reads a stale shape.
    params = {"view": "kpis", "today": local_iso(today), "ids": ",".join(selected)}

    def compute():
        return _compute_kpis(profile, today, settings, selected)

    return stats_cache.get_or_compute(
        profile, "dashboard", params, compute, today_sensitive=True
    )
