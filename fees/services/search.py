"""Global search read service for the Fee Register (T3.5, R-RD-7, brief 6.8, Q6).

Ports ``searchService.ts`` (``search``) to the Django ORM. A single
case-insensitive substring search across firms, matters and memos that powers
the header search box, returning a small, ranked, typed result list.

Behaviour (matching the TypeScript source):

* the raw query is trimmed; under two characters it returns an empty list;
* firms come first (ordered by the lower-cased name), then matters (ordered by
  the lower-cased name), then memos (matched on the memo number OR any of the
  party-name snapshot fields plaintiff_name / defendant_name / client, ordered
  by financial_year descending then seq descending);
* each section is limited to ``limit`` rows and the combined list is finally
  sliced to ``limit``;
* a result is ``{"kind", "id", "title", "subtitle"}`` where kind is one of
  "firm" / "matter" / "memo"; a matter's subtitle is "Matter" plus its firm
  name; a memo's title is its number (or "(draft)") and its subtitle is "Memo"
  plus its matter name plus its firm name.

Q6 (brief line 1159, R-RD-7): the original SQL built ``lower(col) LIKE '%q%'``
without escaping, so a user query containing ``%`` or ``_`` (the SQL LIKE
wildcards) behaved as a wildcard. Django's ``__icontains`` already escapes the
LIKE wildcards ``%`` and ``_`` (and the backslash) in the search VALUE on all
supported backends, so those characters are matched LITERALLY and never act as
wildcards. Q6 is therefore satisfied by the ORM and no manual escaping is
needed; the trimmed query is handed straight to ``__icontains``.

Scoping (design section 11): every query is filtered by ``profile`` like the
sibling read services. This is a pure READ: it never bumps ``data_version``.

Query-count discipline (asserted in the tests with ``assertNumQueries``): the
service runs THREE queries, one each for firms, matters and memos.
``select_related`` on the matter / firm means reading their names costs no
per-row query.
"""
from __future__ import annotations

from django.db.models import Q
from django.db.models.functions import Lower

from fees.models import Firm, Matter, Memo

__all__ = ["search"]

#: The shortest query that searches; a shorter one returns nothing (brief 6.8).
_MIN_QUERY_LEN = 2


def search(profile, raw_query, limit=20):
    """Searches firms, matters and memos for ``profile`` (R-RD-7, brief 6.8, Q6).

    Returns a ranked list of ``{"kind", "id", "title", "subtitle"}`` dicts:
    firms first, then matters, then memos, each section limited to ``limit`` and
    the combined list sliced to ``limit``. ``raw_query`` is trimmed and a query
    shorter than two characters returns an empty list. The match is
    case-insensitive substring; Django's ``__icontains`` already escapes the
    LIKE wildcards ``%`` and ``_`` in the query so they match literally (Q6).
    Three queries; a pure read.
    """
    query = (raw_query or "").strip()
    if len(query) < _MIN_QUERY_LEN:
        return []

    results = []

    firms = (
        Firm.objects.filter(profile=profile, name__icontains=query)
        .order_by(Lower("name"))[:limit]
    )
    for firm in firms:
        results.append(
            {
                "kind": "firm",
                "id": firm.pk,
                "title": firm.name,
                "subtitle": "Firm",
            }
        )

    matters = (
        Matter.objects.filter(profile=profile, name__icontains=query)
        .select_related("firm")
        .order_by(Lower("name"))[:limit]
    )
    for matter in matters:
        results.append(
            {
                "kind": "matter",
                "id": matter.pk,
                "title": matter.name,
                "subtitle": f"Matter \u00b7 {matter.firm.name}",
            }
        )

    memos = (
        Memo.objects.filter(
            Q(memo_number__icontains=query)
            | Q(plaintiff_name__icontains=query)
            | Q(defendant_name__icontains=query)
            | Q(client__icontains=query),
            profile=profile,
        )
        .select_related("matter", "firm")
        .order_by("-financial_year", "-seq")[:limit]
    )
    for memo in memos:
        results.append(
            {
                "kind": "memo",
                "id": memo.pk,
                "title": memo.memo_number or "(draft)",
                "subtitle": f"Memo \u00b7 {memo.matter.name} \u00b7 {memo.firm.name}",
            }
        )

    return results[:limit]
