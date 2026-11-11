"""Insights (plan 5): short plain statements worked out from the profile's data by fixed rules, not AI, ranked by importance. Each links to
the report behind it, can be dismissed, and each kind can be switched off in Settings > Insights. They describe what the data shows; they
never say whether to buy or sell."""
from datetime import date, timedelta
from decimal import Decimal

from fees.services.financial_year import current_financial_year

from investments.models import AlertState, Dividend
from investments.services import core, dashboard, fetch

KINDS = [
    ("vs_index", "Portfolio against the Default Index"),
    ("below_cost", "A holding well below cost and trailing the index"),
    ("turning_long", "Purchases turning long-term within 60 days"),
    ("concentration", "A holding above the concentration limit"),
    ("dividends", "Dividends this year against last year"),
    ("stale", "Holdings with old prices"),
]
DISMISS_PREFIX = "insight:"


def compute(profile, today=None):
    """The insights to show: worked out once and kept (they replay the holdings, so they must not run on every Overview visit), then the
    ones the person dismissed are left out. Dismissing does not change the profile's data, so it is applied after the cache."""
    from investments.services import statscache

    today = today or date.today()
    kept = statscache.get_or_compute(profile, "insights", {}, lambda: _worked_out(profile, today), today_sensitive=True, today=today)
    dismissed = set(AlertState.objects.filter(profile=profile, key__startswith=DISMISS_PREFIX, dismissed_on__isnull=False).values_list("key", flat=True))
    return sorted((i for i in kept if i["key"] not in dismissed), key=lambda i: -i["rank"])


def _worked_out(profile, today):
    from django.urls import reverse

    s = core.get_settings(profile, create=False)
    off = set(s.insights_off or [])
    # The same arguments as the Overview page uses for its own figures (the profile's Include Dividends choice), so this reads the figures
    # the page has just kept instead of working out a second set.
    data = dashboard.load(profile, include_dividends=s.include_dividends)
    rows, totals = data["rows"], data["totals"]
    out = []

    def add(kind, rank, text, url, key):
        if kind not in off:
            out.append({"kind": kind, "rank": rank, "text": text, "url": url, "key": f"{DISMISS_PREFIX}{kind}:{key}"})

    if totals["xirr"] is not None and totals["index_xirr"] is not None:
        diff = (totals["xirr"] - totals["index_xirr"]) * 100
        leader = max((r for r in rows if r["alpha"] is not None), key=lambda r: r["alpha"], default=None)
        word = "above" if diff >= 0 else "below"
        text = f"Your portfolio's XIRR is {abs(diff):.1f} points {word} the Default Index."
        if leader and leader["alpha"] > 0:
            text += f" {leader['name']} led, {leader['alpha'] * 100:.1f} points ahead."
        add("vs_index", 90, text, reverse("investments_performance"), f"{today:%Y%m}")
    for r in rows:
        if r["gain_pct"] is not None and r["gain_pct"] <= -0.15 and r["alpha"] is not None and r["alpha"] < 0 and not r["unpriced"]:
            add("below_cost", 80, f"{r['name']} is {abs(r['gain_pct']) * 100:.1f}% below cost and trailing the index.", reverse("investments_investment", args=[r["id"]]),
                f"{r['id']}")
    from investments.services import reports

    soon = reports.turning_long(profile, days=60)
    if soon.rows:
        first = soon.rows[0]
        add("turning_long", 70, f"{len(soon.rows)} purchase{'s' if len(soon.rows) != 1 else ''} turn long-term within 60 days; the first is {first[0]} in {first[5]} days.",
            reverse("investments_report", args=["turning-long"]), f"{first[0]}:{first[4]}")
    limit = float(s.concentration_limit)
    for r in rows:
        if totals["value"] and not r["blocked"]:
            share = float(r["value"] / totals["value"]) * 100
            if share > limit:
                add("concentration", 60, f"{r['name']} is {share:.1f}% of the portfolio, above your {limit:.0f}% limit.", reverse("investments_report", args=["concentration"]),
                    f"{r['id']}")
    fy = current_financial_year(today)
    start = date(int(fy[:4]), 4, 1)
    this = sum(Dividend.objects.filter(profile=profile, date__range=(start, today)).values_list("amount", flat=True), Decimal(0))
    same_last = sum(Dividend.objects.filter(profile=profile, date__range=(start.replace(year=start.year - 1), today.replace(year=today.year - 1)))
                    .values_list("amount", flat=True), Decimal(0))
    if this or same_last:
        change = "up" if this >= same_last else "down"
        add("dividends", 40, f"Dividends so far this financial year: Rs {this:,.0f}, {change} from Rs {same_last:,.0f} by this time last year.",
            reverse("investments_report", args=["dividends"]), fy)
    stale = fetch.stale_ids([type("I", (), {"pk": r["id"]})() for r in rows if r["price_source"] not in ("manual", "upload")])
    if stale:
        add("stale", 50, f"{len(stale)} holding{'s have' if len(stale) != 1 else ' has'} a price more than {fetch.STALE_DAYS} days old.",
            reverse("investments_report", args=["data-check"]), f"{today:%Y%m%d}")
    return out


def dismiss(profile, key):
    if not key.startswith(DISMISS_PREFIX):
        return
    AlertState.objects.update_or_create(profile=profile, key=key[:120], defaults={"dismissed_on": date.today()})


__all__ = ["compute", "dismiss", "KINDS", "timedelta"]
