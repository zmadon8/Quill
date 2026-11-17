"""Dependent filter drop-downs (owner round): each drop-down lists only the values that have at least one row
under the OTHER applied filters, and always keeps the value now chosen so a saved link shows its own choice.

Pure reads. Every drop-down costs one small ``DISTINCT`` query (or, for the Feebook, whose financial year comes
from the payment date, two queries whose rows are narrowed in memory), never one per row.
"""
from __future__ import annotations

from fees.models import Allocation, Firm, Group, Matter, Memo, Payment
from fees.services import client_scope
from fees.services.financial_year import derive_financial_year
from fees.services.settings import get_settings

__all__ = ["default_year", "memo_options", "feebook_options", "explore_options", "narrow_outstanding_choices"]


def default_year(years, current):
    """The year a list opens on when the link names none: ``current`` when it has rows, else the newest year in
    ``years`` (labels with rows), else ``None`` (All years). Labels sort as text because they are ``YYYY-YY``."""
    if current in years:
        return current
    return max(years) if years else None


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


def _labelled(pairs, firm_names, firm_id):
    """``pairs`` ({id: (name, firm id)}) as ``[{"pk", "name"}]`` by name. Without a chosen firm a name is followed by its firm, in
    brackets, since two firms may have a partner or matter of the same name."""
    rows = [(pk, name if firm_id is not None else f"{name} ({firm_names.get(fid, '')})") for pk, (name, fid) in pairs.items()]
    return [{"pk": pk, "name": name} for pk, name in sorted(rows, key=lambda r: (r[1] or "").lower())]


def _keep_chosen(profile, model, pairs, chosen):
    """Add the chosen partner or matter to ``pairs`` ({id: (name, firm id)}) when the narrowing left it out (one small query, only then)."""
    if chosen is not None and chosen not in pairs:
        row = model.objects.filter(profile=profile, pk=chosen).values_list("name", "firm_id").first()
        if row is not None:
            pairs[chosen] = row
    return pairs


def _memo_base(profile, draft_mode):
    qs = Memo.objects.filter(profile=profile).order_by()
    if draft_mode == "exclude_drafts":
        qs = qs.filter(is_draft=False)
    elif draft_mode == "drafts_only":
        qs = qs.filter(is_draft=True)
    return qs


def memo_options(profile, filters, draft_mode):
    """For the Memos and Drafts filter bar: ``{"firms", "partners", "matters": [{"pk","name"}], "years": {labels with a memo}}``.

    Each list follows the other filters: firms follow the chosen year, partner and matter; partners follow the year, firm, client and
    matter; matters follow the year, firm, client and partner; the year list follows the chosen firm. Five queries.
    """
    base = client_scope.narrow(_memo_base(profile, draft_mode), filters.get("client_id"), "matter__")
    group_id = filters.get("group_id") if isinstance(filters.get("group_id"), int) else None
    matter_id = filters.get("matter_id")
    firm_id = filters.get("firm_id")
    fy = filters.get("financial_year")

    def narrowed(qs, year=True, firm=True, group=True, matter=True):
        if year and fy:
            qs = qs.filter(financial_year=fy)
        if firm and firm_id is not None:
            qs = qs.filter(firm_id=firm_id)
        if group and group_id is not None:
            qs = qs.filter(group_id=group_id)
        if matter and matter_id is not None:
            qs = qs.filter(matter_id=matter_id)
        return qs

    pairs = dict(narrowed(base, firm=False).values_list("firm_id", "firm__name").distinct())
    years = set(narrowed(base, year=False).values_list("financial_year", flat=True).distinct())
    firm_names = dict(Firm.objects.filter(profile=profile).values_list("pk", "name")) if firm_id is None else {}
    partners = {pk: (name, fid) for pk, name, fid in narrowed(base, group=False).filter(group__isnull=False).values_list("group_id", "group__name", "group__firm_id").distinct()}
    matters = {pk: (name, fid) for pk, name, fid in narrowed(base, matter=False).values_list("matter_id", "matter__name", "firm_id").distinct()}
    return {
        "firms": _by_name(_keep_firm(profile, pairs, firm_id)),
        "partners": _labelled(_keep_chosen(profile, Group, partners, group_id), firm_names, firm_id),
        "matters": _labelled(_keep_chosen(profile, Matter, matters, matter_id), firm_names, firm_id),
        "years": years,
    }


def feebook_options(profile, filters, bank_accounts):
    """For the Feebook filter bar: ``{"firms", "partners", "matters", "banks", "years"}``, each narrowed by the other filters.

    The year of a payment is worked out from its date, so the rows are read once (the allocations and the
    unaccounted payments, two queries) and narrowed in memory. ``bank_accounts`` is the profile's bank list.
    """
    # (financial year, firm id or None, firm name, bank id or None, partner id, partner name, matter id, matter name); a payment
    # with no memo (unaccounted) has no firm, partner or matter, and the firm, partner and matter filters leave it in.
    rows = []
    if not filters.get("unaccounted_only"):
        allocations = client_scope.narrow(Allocation.objects.filter(profile=profile).order_by(), filters.get("client_id"), "memo__matter__")
        for day, firm_id, firm_name, bank_id, group_id, group_name, matter_id, matter_name in allocations.values_list(
            "payment__date_of_payment", "memo__firm_id", "memo__firm__name", "payment__bank_account_id",
            "memo__group_id", "memo__group__name", "memo__matter_id", "memo__matter__name",
        ).distinct():
            rows.append((derive_financial_year(day), firm_id, firm_name, bank_id, group_id, group_name, matter_id, matter_name))
    for day, bank_id in Payment.objects.filter(profile=profile, allocations__isnull=True).order_by().values_list(
        "date_of_payment", "bank_account_id"
    ).distinct():
        rows.append((derive_financial_year(day), None, None, bank_id, None, None, None, None))
    # The Feebook list never shows payments before the Initial-FY cutoff, so no drop-down may offer them either.
    cutoff = get_settings(profile)["feebook_start_year"]
    rows = [r for r in rows if r[0] >= cutoff]
    fy = filters.get("financial_year")
    firm_id = filters.get("firm_id")
    bank_id = filters.get("bank_account_id")
    group_id = filters.get("group_id")
    matter_id = filters.get("matter_id")

    def keep(r, year=True, firm=True, bank=True, group=True, matter=True):
        return ((not year or not fy or r[0] == fy) and (not firm or firm_id is None or r[1] in (firm_id, None))
                and (not bank or bank_id is None or r[3] == bank_id)
                and (not group or group_id is None or r[1] is None or r[4] == group_id)
                and (not matter or matter_id is None or r[1] is None or r[6] == matter_id))

    firms = {r[1]: r[2] for r in rows if r[1] is not None and keep(r, firm=False)}
    years = {r[0] for r in rows if keep(r, year=False)}
    bank_ids = {r[3] for r in rows if keep(r, bank=False)}
    banks = [b for b in bank_accounts if b.pk in bank_ids or b.pk == bank_id]
    firm_names = {r[1]: r[2] for r in rows if r[1] is not None}
    partners = {r[4]: (r[5], r[1]) for r in rows if r[4] is not None and keep(r, group=False)}
    matters = {r[6]: (r[7], r[1]) for r in rows if r[6] is not None and keep(r, matter=False)}
    return {
        "firms": _by_name(_keep_firm(profile, firms, firm_id)),
        "partners": _labelled(_keep_chosen(profile, Group, partners, group_id), firm_names, firm_id),
        "matters": _labelled(_keep_chosen(profile, Matter, matters, matter_id), firm_names, firm_id),
        "banks": banks,
        "years": years,
    }


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
    """Narrow ``list_outstanding_scope`` output: groups to the chosen firm, firms to the chosen group's firm. The clients are passed
    through, with the chosen client added back when it has nothing outstanding in the view.

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
    clients = list(choices.get("clients", []))
    client_id = filters.get("client_id")
    if isinstance(client_id, int) and all(c["id"] != client_id for c in clients):
        from fees.models import Client

        name = Client.objects.filter(profile=profile, pk=client_id).values_list("name", flat=True).first()
        if name is not None:
            clients.append({"id": client_id, "name": name})
            clients.sort(key=lambda c: c["name"].lower())
    return {"firms": firms, "partners": partners, "clients": clients, "no_client": choices.get("no_client", False)}
