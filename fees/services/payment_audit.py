"""Read-only audit of the payment data, to run BEFORE database rules are added to the payment tables.

It looks for what a rule such as "a memo cannot be paid more than it is for" or "no negative or repeated allocation" would
refuse, so that the rule can be added without a failed update. It never writes anything and never bumps ``data_version``.

Problems that stop such a rule (reported first, and the command exits with an error when any is found):

* **Overpaid memos**: the memo's payments, counting the TDS as paid (``net + TDS``, the "gross"), come to more than the
  memo's total. The net paid alone is also compared, because it is the stricter reading of "paid".
* **Negative allocations**: an allocation row with a negative amount or a negative TDS amount.
* **Repeated allocations**: one payment applied to the same memo in more than one row.

Information only (listed after, never an error): draft memos that have payments, written-off memos that have payments,
and payments whose rows do not add up to the payment's own amount or TDS (the app allows a part-allocated payment).

Sums come from the allocation rows, which are the source of truth. Whether the memo's stored paid columns agree with them
is a different question; ``fees_check`` answers it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Count, Q, Sum

from accounts.suite import KEY_FEES
from fees.models import Allocation, Memo, Payment
from fees.services.money import round2

__all__ = ["AuditReport", "audit_profile", "audit_all", "format_report"]

_ZERO = Decimal("0.00")


@dataclass
class AuditReport:
    profile_id: int
    profile_name: str
    memos_checked: int = 0
    allocations_checked: int = 0
    payments_checked: int = 0
    unaccounted_payments: int = 0
    overpaid: list = field(default_factory=list)          # gross (net + TDS) is more than the memo's total
    negative: list = field(default_factory=list)          # an allocation with a negative amount or TDS
    repeated: list = field(default_factory=list)          # the same payment on the same memo more than once
    draft_with_payments: list = field(default_factory=list)
    written_off_with_payments: list = field(default_factory=list)
    split_differs: list = field(default_factory=list)     # a payment's rows do not add up to the payment

    @property
    def blocking(self) -> int:
        """How many problems a database rule would refuse."""
        return len(self.overpaid) + len(self.negative) + len(self.repeated)


def _label(number, memo_id):
    return number or f"draft memo {memo_id}"


def audit_profile(profile) -> AuditReport:
    """Audits one Fee Register profile (read-only)."""
    report = AuditReport(profile_id=profile.pk, profile_name=profile.name)

    memo_rows = (
        Memo.objects.filter(profile=profile)
        .annotate(net=Sum("allocations__amount"), tds=Sum("allocations__tds_amount"), rows=Count("allocations"))
        .values("id", "memo_number", "is_draft", "written_off", "total_fees", "net", "tds", "rows", "firm__name", "matter__name")
    )
    for row in memo_rows.iterator():
        report.memos_checked += 1
        if not row["rows"]:
            continue
        net = round2(row["net"] or 0)
        tds = round2(row["tds"] or 0)
        gross = round2(net + tds)
        total = round2(row["total_fees"] or 0)
        entry = {
            "memo_id": row["id"],
            "memo": _label(row["memo_number"], row["id"]),
            "firm": row["firm__name"],
            "matter": row["matter__name"],
            "total": total,
            "net": net,
            "tds": tds,
            "gross": gross,
            "over_gross": round2(gross - total),
            "over_net": round2(net - total),
        }
        if row["is_draft"]:
            report.draft_with_payments.append(entry)
        elif gross > total:
            report.overpaid.append(entry)
        if row["written_off"] and not row["is_draft"]:
            report.written_off_with_payments.append(entry)

    allocations = Allocation.objects.filter(profile=profile)
    report.allocations_checked = allocations.count()
    memo_names = {}

    def memo_name(memo_id):
        if memo_id not in memo_names:
            number = Memo.objects.filter(pk=memo_id).values_list("memo_number", flat=True).first()
            memo_names[memo_id] = _label(number, memo_id)
        return memo_names[memo_id]

    for alloc in allocations.filter(Q(amount__lt=0) | Q(tds_amount__lt=0)).values("id", "payment_id", "memo_id", "amount", "tds_amount"):
        report.negative.append({**alloc, "memo": memo_name(alloc["memo_id"])})

    for pair in allocations.values("payment_id", "memo_id").annotate(n=Count("id")).filter(n__gt=1):
        report.repeated.append({"payment_id": pair["payment_id"], "memo_id": pair["memo_id"], "memo": memo_name(pair["memo_id"]), "rows": pair["n"]})

    payment_rows = (
        Payment.objects.filter(profile=profile)
        .annotate(split=Sum("allocations__amount"), split_tds=Sum("allocations__tds_amount"), rows=Count("allocations"))
        .values("id", "date_of_payment", "payee", "amount", "tds_amount", "split", "split_tds", "rows")
    )
    for row in payment_rows.iterator():
        report.payments_checked += 1
        if not row["rows"]:
            report.unaccounted_payments += 1
            continue
        split, split_tds = round2(row["split"] or 0), round2(row["split_tds"] or 0)
        if split != round2(row["amount"]) or split_tds != round2(row["tds_amount"]):
            report.split_differs.append({
                "payment_id": row["id"], "date": row["date_of_payment"], "payee": row["payee"] or "",
                "amount": round2(row["amount"]), "tds": round2(row["tds_amount"]), "split": split, "split_tds": split_tds,
            })
    return report


def audit_all() -> list:
    """Audits every live Fee Register profile."""
    from accounts.models import Profile

    return [audit_profile(p) for p in Profile.objects.filter(program=KEY_FEES, deleted_at__isnull=True).order_by("id")]


def _money(value) -> str:
    return f"{value:,.2f}"


def format_report(report) -> list:
    """The report as lines of plain text, problems first."""
    out = [f"Profile {report.profile_id} ({report.profile_name}): {report.memos_checked} memos, "
           f"{report.allocations_checked} allocation rows, {report.payments_checked} payments "
           f"({report.unaccounted_payments} not applied to any memo)."]
    out.append("")
    out.append(f"1. OVERPAID MEMOS (payments plus TDS come to more than the memo): {len(report.overpaid)}")
    for e in sorted(report.overpaid, key=lambda e: e["over_gross"], reverse=True):
        extra = f" (the net received alone is also {_money(e['over_net'])} too much)" if e["over_net"] > 0 else ""
        out.append(f"   memo {e['memo']}, {e['firm']}, {e['matter']}: total {_money(e['total'])}, received {_money(e['net'])}, "
                   f"TDS {_money(e['tds'])}, together {_money(e['gross'])}: {_money(e['over_gross'])} too much{extra}")
    out.append("")
    out.append(f"2. NEGATIVE ALLOCATIONS: {len(report.negative)}")
    for e in report.negative:
        out.append(f"   memo {e['memo']}, payment id {e['payment_id']}: amount {_money(e['amount'])}, TDS {_money(e['tds_amount'])}")
    out.append("")
    out.append(f"3. THE SAME PAYMENT ON THE SAME MEMO MORE THAN ONCE: {len(report.repeated)}")
    for e in report.repeated:
        out.append(f"   memo {e['memo']}, payment id {e['payment_id']}: {e['rows']} rows")
    out.append("")
    out.append("For information (a database rule would not be stopped by these)")
    out.append(f"4. Draft memos that have payments: {len(report.draft_with_payments)}")
    for e in report.draft_with_payments:
        out.append(f"   {e['memo']}, {e['firm']}, {e['matter']}: received {_money(e['net'])}, TDS {_money(e['tds'])}")
    out.append(f"5. Written-off memos that have payments: {len(report.written_off_with_payments)}")
    for e in report.written_off_with_payments:
        out.append(f"   memo {e['memo']}, {e['firm']}, {e['matter']}: total {_money(e['total'])}, together paid {_money(e['gross'])}")
    out.append(f"6. Payments whose memo rows do not add up to the payment: {len(report.split_differs)}")
    for e in report.split_differs:
        out.append(f"   payment id {e['payment_id']} on {e['date']} ({e['payee']}): amount {_money(e['amount'])}, TDS {_money(e['tds'])}; "
                   f"rows add up to {_money(e['split'])} and TDS {_money(e['split_tds'])}")
    out.append("")
    out.append("Nothing was changed." + (f" {report.blocking} problem(s) in 1 to 3 need a decision first." if report.blocking else " Items 1 to 3 are clear."))
    return out
