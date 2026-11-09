"""Search (plan 24.2), following `fees/services/search.py`: case-insensitive substring (`icontains` matches % and _ literally), at least two
characters, a small typed result list grouped by kind: investments (name, code, ISIN), folio numbers, brokers, transactions (by investment,
reference or note) and the program's pages (hidden pages left out). Scoped to the open profile; a pure read."""
from django.db.models import Q

from investments import pages
from investments.models import HOLDABLE_KINDS, Broker, Folio, Instrument, ProfileInvestment, Transaction

MIN_LEN = 2


def search(profile, raw, limit=8, hidden=frozenset()):
    q = (raw or "").strip()
    if len(q) < MIN_LEN:
        return []
    mine = ProfileInvestment.objects.filter(profile=profile).values("instrument_id")
    results = []
    for inst in Instrument.objects.filter(Q(pk__in=mine) | Q(profile=profile), kind__in=HOLDABLE_KINDS).filter(
            Q(name__icontains=q) | Q(code__icontains=q) | Q(isin__icontains=q)).order_by("name")[:limit]:
        results.append({"kind": "Investments", "title": inst.name, "subtitle": " ".join(x for x in (inst.get_kind_display(), inst.code) if x),
                        "url": ("investment", inst.pk)})
    for folio in Folio.objects.filter(profile=profile, number__icontains=q).select_related("instrument", "portfolio")[:limit]:
        results.append({"kind": "Folios", "title": folio.number, "subtitle": f"{folio.instrument.name}, {folio.portfolio.name}", "url": ("investment", folio.instrument_id)})
    for broker in Broker.objects.filter(profile=profile, name__icontains=q)[:limit]:
        results.append({"kind": "Brokers", "title": broker.name, "subtitle": "Broker", "url": ("broker_detail", broker.pk)})
    for t in Transaction.objects.filter(profile=profile).filter(Q(instrument__name__icontains=q) | Q(reference__icontains=q) | Q(note__icontains=q)).select_related(
            "instrument").order_by("-date", "-id")[:limit]:
        results.append({"kind": "Transactions", "title": f"{t.date:%-d %b %Y} {t.get_side_display()} {t.instrument.name}",
                        "subtitle": t.reference or t.get_status_display(), "url": ("transactions", t.pk)})
    lowered = q.casefold()
    for page in pages.PAGES:
        if page.slug in hidden or page.slug in ("search",) or page.admin:
            continue
        if lowered in page.title.casefold() or lowered in (page.sub or "").casefold():
            results.append({"kind": "Pages", "title": page.title, "subtitle": page.sub or "", "url": ("page", page.slug)})
            if sum(1 for r in results if r["kind"] == "Pages") >= limit:
                break
    return results
