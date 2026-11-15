"""Buy and sell markers for charts that plot a portfolio over time. Pure functions (no database): the services read the transactions once,
when a chart's figures are worked out, and keep the result in the cached chart payload."""
from bisect import bisect_left
from decimal import Decimal

from investments.money_auto import format_indian


def aggregate(days, txns):
    """One marker per sampled day and side. ``txns`` is ``[(date, "buy" or "sell", amount)]``; each lands on the first sampled day on or after
    its date (days before the first or after the last sample are left out). Returns ``[[iso day, label, "buy" or "sell"]]`` (plain lists, so
    they keep as JSON), the label giving the count and the net amount in Indian grouping."""
    if not days:
        return []
    buckets = {}
    for day, side, amount in txns:
        i = bisect_left(days, day)
        if i >= len(days) or side not in ("buy", "sell"):
            continue
        count, total = buckets.get((i, side), (0, Decimal(0)))
        buckets[(i, side)] = (count + 1, total + Decimal(amount or 0))
    out = []
    for (i, side), (count, total) in sorted(buckets.items()):
        word = ("purchase" if side == "buy" else "sale") + ("" if count == 1 else "s")
        out.append([days[i].isoformat(), f"{count} {word}, net Rs{format_indian(total)}, up to {days[i]:%-d %b %Y}", side])
    return out
