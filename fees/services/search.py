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
wildcards) behaved as a wildcard. This port escapes the backslash, percent and
underscore in the query before matching so those characters are matched
LITERALLY and never act as wildcards. Django's ``__icontains`` builds a
parameterised ``LIKE`` whose escape character is the backslash, so prefixing
each of ``\\``, ``%`` and ``_`` in the term with a backslash makes it literal on
the backends the project uses. The ``\\`` substitution runs first so the escapes
added for ``%`` and ``_`` are not themselves re-escaped.

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

__all__ = ["search", "escape_like"]

#: The shortest query that searches; a shorter one returns nothing (brief 6.8).
_MIN_QUERY_LEN = 2


def escape_like(term):
    """Escapes the LIKE wildcards in ``term`` so they match literally (Q6).

    Prefixes each backslash, percent and underscore with a backslash so that an
    ``__icontains`` built over the result treats ``%`` and ``_`` as ordinary
    characters rather than wildcards. The backslash substitution runs first so
    the backslashes added for ``%`` and ``_`` are not re-escaped.
    """
    return (
        term.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def search(profile, raw_query, limit=20):
    """Searches firms, matters and memos for ``profile`` (R-RD-7, brief 6.8, Q6).

    Returns a ranked list of ``{"kind", "id", "title", "subtitle"}`` dicts:
    firms first, then matters, then memos, each section limited to ``limit`` and
    the combined list sliced to ``limit``. ``raw_query`` is trimmed and a query
    shorter than two characters returns an empty list. The match is
    case-insensitive substring; the LIKE wildcards ``%`` and ``_`` in the query
    are escaped so they are matched literally (Q6). Three queries; a pure read.
    """
    query = (raw_query or "").strip()
    if len(query) < _MIN_QUERY_LEN:
        return []

    needle = escape_like(query)

    results = []

    firms = (
        Firm.objects.filter(profile=profile, name__icontains=needle)
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
        Matter.objects.filter(profile=profile, name__icontains=needle)
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
            Q(memo_number__icontains=needle)
            | Q(plaintiff_name__icontains=needle)
            | Q(defendant_name__icontains=needle)
            | Q(client__icontains=needle),
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
