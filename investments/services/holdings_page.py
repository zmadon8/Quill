"""The rows of the Holdings page, worked out once and kept in the statistics cache (plan 26.4).

The page used to replay every transaction (FIFO lots and an XIRR per holding), look up each investment's newest price and read 90 days of
closes for the sparklines on every visit. All of that depends only on the profile's data, the prices, the selection and the date, which
is exactly what the cache is keyed on, so the page now reads the kept rows and only filters them (Type and Status) per request.

The payload is JSON (money as text); ``load`` gives back light row objects with the attributes the template reads."""
from datetime import date
from decimal import Decimal

from investments.models import HOLDABLE_KINDS, KIND_ALTERNATIVE, ProfileInvestment
from investments.services import fetch, holdings, prices, statscache
from investments.svgchart import sparkline


class _Instrument:
    """The few fields of an investment the Holdings table shows."""

    def __init__(self, data):
        self.pk = self.id = data["id"]
        self.name = data["name"]
        self.code = data["code"]
        self.isin = data.get("isin", "")
        self.kind = data["kind"]
        self.price_source = data["price_source"]
        self._kind_label = data["kind_label"]

    def get_kind_display(self):
        return self._kind_label

    def __str__(self):
        return self.name


class Row:
    """One Holdings line as the template reads it (the same names as ``holdings.Holding``)."""

    def __init__(self, data):
        self.instrument = _Instrument(data["instrument"])
        self.units = Decimal(data["units"])
        self.cost = Decimal(data["cost"])
        self.value = Decimal(data["value"])
        self.awaiting = Decimal(data["awaiting"])
        self.first_date = date.fromisoformat(data["first_date"]) if data["first_date"] else None
        self.price_date = date.fromisoformat(data["price_date"]) if data["price_date"] else None
        self.xirr = data["xirr"]
        self.unpriced = data["unpriced"]
        self.stale = data["stale"]
        self.blocked = data["blocked"]
        self.is_held = data["is_held"]
        self.sold_out = data["sold_out"]
        self.empty = data["empty"]
        self.is_hidden = data["hidden"]
        self.spark = data["spark"]
        self.realised = Decimal(data.get("realised", "0"))
        self.dividends = Decimal(data.get("dividends", "0"))

    @property
    def gain(self):
        return self.value - self.cost

    @property
    def gain_pct(self):
        return float(self.gain / self.cost) if self.cost else None

    @property
    def avg_cost(self):
        return (self.cost - self.awaiting) / self.units if self.units else None


def _dump(h, hidden_ids, stale, sparks):
    inst = h.instrument
    return {
        "instrument": {"id": inst.pk, "name": inst.name, "code": inst.code, "isin": inst.isin or "", "kind": inst.kind, "kind_label": inst.get_kind_display(),
                       "price_source": inst.price_source},
        "units": str(h.units), "cost": str(h.cost), "value": str(h.value), "awaiting": str(h.awaiting),
        "first_date": h.first_date.isoformat() if h.first_date else None, "price_date": h.price_date.isoformat() if h.price_date else None,
        "xirr": h.xirr, "unpriced": h.unpriced, "stale": inst.pk in stale, "blocked": h.blocked, "is_held": h.is_held,
        "sold_out": h.sold_out, "empty": h.empty, "hidden": inst.pk in hidden_ids, "spark": sparks.get(inst.pk),
        "realised": str(h.realised), "dividends": str(h.dividends),
    }


def compute(profile, portfolio=None, broker=None, as_of=None):
    """Every line the page can show (all types and statuses), plus the counts the page keeps: ``{"rows", "held_count", "sold_count"}``."""
    rows, _totals = holdings.compute(profile, portfolio=portfolio, broker=broker, as_of=as_of)
    hidden_ids = set(ProfileInvestment.objects.filter(profile=profile, hidden=True).values_list("instrument_id", flat=True))
    # Investments added but not yet bought still belong in the list.
    # They are "Not bought yet", never "Held": nothing is held until units (or a purchase awaiting allotment) exist.
    seen = {h.instrument.pk for h in rows}
    extra = [holdings.Holding(instrument=pi.instrument, empty=True) for pi in
             ProfileInvestment.objects.filter(profile=profile).select_related("instrument") if pi.instrument_id not in seen
             and pi.instrument.kind in HOLDABLE_KINDS]
    rows = rows + extra
    stale = fetch.stale_ids([h.instrument for h in rows if h.is_held and h.instrument.price_source not in ("manual", "upload")])
    spark_of = [h.instrument for h in rows if h.is_held and not h.unpriced and h.instrument.kind != KIND_ALTERNATIVE]
    closes = prices.recent_closes([i.pk for i in spark_of], as_of or date.today())
    sparks = {iid: sparkline(vals) for iid, vals in closes.items()}
    return {
        "rows": [_dump(h, hidden_ids, stale, sparks) for h in rows],
        "held_count": sum(1 for h in rows if h.is_held and h.instrument.pk not in hidden_ids),
        "sold_count": sum(1 for h in rows if h.sold_out),
    }


def load(profile, portfolio=None, broker=None, as_of=None):
    """``(rows, held_count, sold_count)`` for the selection, from the cache while the data, the prices and the date are unchanged."""
    payload = statscache.get_or_compute(profile, "holdings", {"p": portfolio, "b": broker, "a": as_of},
                                        lambda: compute(profile, portfolio, broker, as_of), today_sensitive=True)
    return [Row(r) for r in payload["rows"]], payload["held_count"], payload["sold_count"]
