"""Dependent filter drop-downs (owner round): each drop-down lists only the values that have at least one row
under the OTHER applied filters, and always keeps the value now chosen so a saved link shows its own choice.

Pure reads. Every drop-down costs one small ``DISTINCT`` query (or, for the Feebook, whose financial year comes
from the payment date, two queries whose rows are narrowed in memory), never one per row.
"""
from __future__ import annotations

from fees.models import Allocation, Firm, Group, Memo, Payment
from fees.services.financial_year import derive_financial_year

__all__ = ["memo_options", "feebook_options", "explore_options", "narrow_outstanding_choices"]


def _by_name(pairs):
    """``{id: name}`` as a list of ``{"pk", "name"}`` dicts sorted by name, case-insensitively."""
    return [{"pk": pk, "name": name} for pk, name in sorted(pairs.items(), key=lambda p: (p[1] or "").lower())]


def _keep_firm(profile, pairs, firm_id):
    """Add the chosen firm to ``pairs`` when the narrowing left it out (one small query, only then)."""
    if firm_id is not None and firm_id not in pairs:
        name = Firm.objects.filter(profile=profile, pk=firm_id).values_list("name", flat=True).first()
        if name is not None:
            pairs[firm_id] = name
    return pairs


def _memo_base(profile, draft_mode):
    qs = Memo.objects.filter(profile=profile).order_by()
    if draft_mode == "exclude_drafts":
        qs = qs.filter(is_draft=False)
    elif draft_mode == "drafts_only":
        qs = qs.filter(is_draft=True)
    return qs


def memo_options(profile, filters, draft_mode):
    """For the Memos and Drafts filter bar: ``{"firms": [{"pk","name"}], "years": {labels with a memo}}``.

    The firm list follows the chosen financial year; the year list follows the chosen firm. Two queries.
    """
    base = _memo_base(profile, draft_mode)
    group_id = filters.get("group_id")
    if isinstance(group_id, int):
        base = base.filter(group_id=group_id)
    matter_id = filters.get("matter_id")
    if matter_id is not None:
        base = base.filter(matter_id=matter_id)
    firm_id = filters.get("firm_id")
    fy = filters.get("financial_year")
    firm_qs = base.filter(financial_year=fy) if fy else base
    year_qs = base.filter(firm_id=firm_id) if firm_id is not None else base
    pairs = dict(firm_qs.values_list("firm_id", "firm__name").distinct())
    years = set(year_qs.values_list("financial_year", flat=True).distinct())
    return {"firms": _by_name(_keep_firm(profile, pairs, firm_id)), "years": years}


def feebook_options(profile, filters, bank_accounts):
    """For the Feebook filter bar: ``{"firms", "banks", "years"}``, each narrowed by the other two filters.

    The year of a payment is worked out from its date, so the rows are read once (the allocations and the
    unaccounted payments, two queries) and narrowed in memory. ``bank_accounts`` is the profile's bank list.
    """
    rows = []  # (financial year, firm id or None, firm name, bank id or None)
    if not filters.get("unaccounted_only"):
        group_id = filters.get("group_id")
        allocations = Allocation.objects.filter(profile=profile).order_by()
        if group_id is not None:
            allocations = allocations.filter(memo__group_id=group_id)
        for day, firm_id, firm_name, bank_id in allocations.values_list(
            "payment__date_of_payment", "memo__firm_id", "memo__firm__name", "payment__bank_account_id"
        ).distinct():
            rows.append((derive_financial_year(day), firm_id, firm_name, bank_id))
    for day, bank_id in Payment.objects.filter(profile=profile, allocations__isnull=True).order_by().values_list(
        "date_of_payment", "bank_account_id"
    ).distinct():
        rows.append((derive_financial_year(day), None, None, bank_id))
    fy = filters.get("financial_year")
    firm_id = filters.get("firm_id")
    bank_id = filters.get("bank_account_id")
    firms = {r[1]: r[2] for r in rows if r[1] is not None and (not fy or r[0] == fy) and (bank_id is None or r[3] == bank_id)}
    years = {r[0] for r in rows if (firm_id is None or r[1] in (firm_id, None)) and (bank_id is None or r[3] == bank_id)}
    bank_ids = {r[3] for r in rows if (not fy or r[0] == fy) and (firm_id is None or r[1] in (firm_id, None))}
    banks = [b for b in bank_accounts if b.pk in bank_ids or b.pk == bank_id]
    return {"firms": _by_name(_keep_firm(profile, firms, firm_id)), "banks": banks, "years": years}


def explore_options(profile, chosen):
    """For the Statistics Explore bar: ``{"firms", "years"}``. Firms follow the From and To years, years follow the firm."""
    base = Memo.objects.filter(profile=profile, is_draft=False).order_by()
    low, high, firm_id = chosen.get("from_fy"), chosen.get("to_fy"), chosen.get("firm_id")
    firm_qs = base
    if low:
        firm_qs = firm_qs.filter(financial_year__gte=low)
    if high:
        firm_qs = firm_qs.filter(financial_year__lte=high)
    year_qs = base.filter(firm_id=firm_id) if firm_id else base
    pairs = dict(firm_qs.values_list("firm_id", "firm__name").distinct())
    years = set(year_qs.values_list("financial_year", flat=True).distinct())
    return {"firms": _by_name(_keep_firm(profile, pairs, firm_id)), "years": years}


def narrow_outstanding_choices(profile, choices, filters):
    """Narrow ``list_outstanding_scope`` output: groups to the chosen firm, firms to the chosen group's firm.

    Works on the lists already read; the chosen firm or group is added back (one small query each, only when it
    is missing) so it stays in its drop-down.
    """
    firm_id = filters.get("firm_id")
    group_id = filters.get("group_id")
    partners = list(choices["partners"])
    firms = list(choices["firms"])
    group_firm = next((p["firm_id"] for p in partners if p["id"] == group_id), None)
    if firm_id is not None:
        partners = [p for p in partners if p["firm_id"] == firm_id]
    if group_firm is not None:
        firms = [f for f in firms if f["id"] == group_firm]
    if firm_id is not None and all(f["id"] != firm_id for f in firms):
        name = Firm.objects.filter(profile=profile, pk=firm_id).values_list("name", flat=True).first()
        if name is not None:
            firms.append({"id": firm_id, "name": name})
            firms.sort(key=lambda f: f["name"].lower())
    if group_id is not None and all(p["id"] != group_id for p in partners):
        row = Group.objects.filter(profile=profile, pk=group_id).values_list("name", "firm_id").first()
        if row is not None:
            partners.append({"id": group_id, "firm_id": row[1], "name": row[0]})
            partners.sort(key=lambda p: p["name"].lower())
    return {"firms": firms, "partners": partners}
