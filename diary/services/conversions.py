"""Conversions between Item, Multi-Item and Nested Item (docs/DESIGN.md section 6, spec 4.13).

The record keeps its id. ``preview_conversion`` shows before and after and every warning or
refusal without writing anything; ``convert_item`` does the same plan in one transaction. All
the changes share one Undo group and are recorded with change kind 'convert'.
"""
from dataclasses import dataclass, field

from django.db import transaction

from .. import numbering
from ..models import KIND_CHOICES, KIND_MULTI, KIND_NESTED, KIND_PLAIN, Case, Item, Note, TrashBatch
from .core import Ctx, check_version, commit, create, get_record, label, make_result, now
from .errors import ConfirmationRequired, Refused
from .sequences import ident, lock_sequence, members, place, sequence_key

KIND_NAMES = dict(KIND_CHOICES)
FLATTEN_WARNING = "Formatting and line breaks in comments will be lost."
OPTIONS = ("keep", "fold")


@dataclass
class Plan:
    from_kind: str
    to_kind: str
    changed: bool = True
    refusal: str = ""
    reasons: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    needs_option: bool = False
    fold_reasons: list = field(default_factory=list)
    new_citation: str = ""
    cases: list = field(default_factory=list)  # Cases to remove
    kids: list = field(default_factory=list)  # live Items beneath a Nested Item
    make_cases: list = field(default_factory=list)  # [{"citation", "comment"}]
    make_children: list = field(default_factory=list)  # [{"text", "citation"}]
    release_kids: bool = False
    trash_kids: bool = False


def join_cases(entries):
    """One single-line citation from [(citation, comment text)]: ``(a) X - note; (b) Y``."""
    marks = numbering.multi_item_labels(len(entries))
    parts = []
    for mark, (citation, comment) in zip(marks, entries):
        citation = " ".join(citation.split())
        comment = " ".join(comment.split())
        piece = f"{citation} - {comment}" if citation and comment else (citation or comment)
        parts.append(piece if len(entries) == 1 else f"{mark} {piece}".strip())
    return "; ".join(parts)


def live_cases(item):
    return list(Case._base_manager.filter(item=item, deleted_at__isnull=True).order_by("position", "pk"))


def live_kids(item):
    return list(Item._base_manager.filter(parent_item=item, deleted_at__isnull=True).order_by("position", "pk"))


def fold_problems(kids):
    """Reasons why the Items beneath a Nested Item cannot be folded into Cases (spec 4.13, rule 2)."""
    reasons = []
    for kid in kids:
        name = label(kid)
        if kid.kind == KIND_MULTI:
            reasons.append(f"{name!r} is a Multi-Item.")
        elif kid.kind == KIND_NESTED:
            reasons.append(f"{name!r} is a Nested Item.")
        if Case._base_manager.filter(item=kid, deleted_at__isnull=True).count() > 1:
            reasons.append(f"{name!r} has several Cases.")
        if kid.flag != "none":
            reasons.append(f"{name!r} has a flag.")
        if kid.needs_review:
            reasons.append(f"{name!r} is marked For review.")
        if Note._base_manager.filter(item=kid, deleted_at__isnull=True).exists():
            reasons.append(f"{name!r} has a Note.")
    return reasons


def build_plan(item, to_kind, option=None):
    """What converting ``item`` to ``to_kind`` would do. Never writes."""
    if to_kind not in KIND_NAMES:
        raise Refused(f"{to_kind!r} is not an Item type.")
    plan = Plan(from_kind=item.kind, to_kind=to_kind)
    if item.kind == to_kind:
        plan.changed = False
        return plan
    if item.parent_item_id is not None:
        return _refuse(plan, "An Item beneath a Nested Item must stay a plain Item (one level of nesting).")
    plan.new_citation = item.citation
    if item.kind == KIND_PLAIN and to_kind == KIND_MULTI:
        plan.new_citation = ""
        plan.make_cases = [{"citation": item.citation, "comment": ""}]
    elif item.kind == KIND_PLAIN and to_kind == KIND_NESTED:
        pass
    elif item.kind == KIND_MULTI:
        plan.cases = live_cases(item)
        if to_kind == KIND_PLAIN:
            entries = [(c.citation, c.comment_plain) for c in plan.cases]
            plan.new_citation = join_cases(entries)
            if any(c.comment_plain.strip() for c in plan.cases):
                plan.warnings.append(FLATTEN_WARNING)
            if len(plan.new_citation) > 1000:
                return _refuse(plan, "The joined citation would be longer than 1000 characters.")
        else:
            plan.new_citation = ""
            plan.make_children = [{"text": c.comment, "citation": c.citation} for c in plan.cases]
    else:  # from Nested to Item or Multi
        plan.kids = live_kids(item)
        if not plan.kids:
            if to_kind == KIND_MULTI:
                plan.new_citation = ""
                plan.make_cases = [{"citation": item.citation, "comment": ""}]
            return plan
        plan.fold_reasons = fold_problems(plan.kids)
        if option not in OPTIONS:
            plan.needs_option = True
            return plan
        if option == "keep":
            plan.release_kids = True
            if to_kind == KIND_MULTI:
                plan.new_citation = ""
                plan.make_cases = [{"citation": item.citation, "comment": ""}]
        else:
            if plan.fold_reasons:
                return _refuse(
                    plan,
                    "The Items beneath it cannot be folded into Cases, so nothing was changed. "
                    "Keep them as separate Items instead.",
                    plan.fold_reasons,
                )
            plan.trash_kids = True
            folded = [{"citation": item.citation, "comment": ""}] + [
                {"citation": k.citation, "comment": k.text} for k in plan.kids
            ]
            if to_kind == KIND_MULTI:
                plan.new_citation = ""
                plan.make_cases = folded
            else:
                plan.new_citation = join_cases([(f["citation"], _plain(f["comment"])) for f in folded])
                if any(k.text_plain.strip() for k in plan.kids):
                    plan.warnings.append(FLATTEN_WARNING)
                if len(plan.new_citation) > 1000:
                    return _refuse(plan, "The joined citation would be longer than 1000 characters.")
    return plan


def _plain(html):
    from ..richtext import plain_text

    return plain_text(html)


def _refuse(plan, message, reasons=None):
    plan.refusal = message
    plan.reasons = list(reasons) if reasons else [message]
    return plan


def _describe_before(item, plan):
    cases = plan.cases if plan.from_kind == KIND_MULTI else []
    marks = numbering.multi_item_labels(len(cases))
    return {
        "kind": item.kind,
        "kind_label": KIND_NAMES[item.kind],
        "citation": item.citation,
        "cases": [{"label": m, "citation": c.citation, "comment": c.comment} for m, c in zip(marks, cases)],
        "children": [{"label": numbering.BULLET, "text": k.text, "citation": k.citation} for k in plan.kids],
    }


def _describe_after(item, plan):
    marks = numbering.multi_item_labels(len(plan.make_cases))
    children = [{"label": numbering.BULLET, "text": c["text"], "citation": c["citation"]} for c in plan.make_children]
    return {
        "kind": plan.to_kind,
        "kind_label": KIND_NAMES[plan.to_kind],
        "citation": plan.new_citation,
        "cases": [{"label": m, "citation": c["citation"], "comment": c["comment"]} for m, c in zip(marks, plan.make_cases)],
        "children": children,
        "released": [{"text": k.text, "citation": k.citation} for k in plan.kids] if plan.release_kids else [],
    }


def preview_conversion(profile, user, item_id, to_kind, option=None):
    """Before and after, warnings, refusal and the choices for a conversion. Writes nothing."""
    ctx = Ctx(profile, user)
    item = get_record(ctx, "item", item_id, lock=False)
    plan = build_plan(item, to_kind, option)
    out = {
        "item_id": item.pk,
        "version": item.version,
        "from_kind": plan.from_kind,
        "to_kind": plan.to_kind,
        "changed": plan.changed,
        "refusal": plan.refusal,
        "reasons": plan.reasons,
        "warnings": plan.warnings,
        "needs_option": plan.needs_option,
        "options": [],
        "before": _describe_before(item, plan),
        "after": None,
    }
    if plan.needs_option:
        out["options"] = [
            {"key": "keep", "available": True, "reasons": []},
            {"key": "fold", "available": not plan.fold_reasons, "reasons": plan.fold_reasons},
        ]
    elif plan.changed and not plan.refusal:
        out["after"] = _describe_after(item, plan)
    return out


def convert_item(profile, user, item_id, to_kind, expected_version=None, option=None, accept_warnings=False):
    """Convert an Item. Raises Refused (nothing changes) if the rules forbid it, ConfirmationRequired if
    there are warnings and ``accept_warnings`` is False. Converting to the type it already has changes nothing."""
    ctx = Ctx(profile, user)
    with transaction.atomic():
        item = get_record(ctx, "item", item_id)
        plan = build_plan(item, to_kind, option)
        if not plan.changed:
            return make_result(ctx, item)
        if plan.needs_option:
            raise Refused("Choose what happens to the Items beneath it: keep them as Items or fold them into Cases.")
        if plan.refusal:
            raise Refused(plan.refusal, plan.reasons)
        check_version(item, expected_version)
        if plan.warnings and not accept_warnings:
            raise ConfirmationRequired(plan.warnings)
        key = sequence_key(item)
        lock_sequence(ctx, key)
        stamp = now()
        batch = None
        if plan.cases or plan.trash_kids:
            batch = TrashBatch.objects.create(
                profile_id=ctx.profile_id,
                root_type="item",
                root_id=item.pk,
                label=f"Removed by conversion: {label(item)}"[:500],
                created_by=ctx.actor,
            )
        for case in plan.cases:
            case.deleted_at, case.delete_batch = stamp, batch.id
            commit(ctx, case, "convert", check=False)
        if plan.trash_kids:
            for kid in plan.kids:
                kid.deleted_at, kid.delete_batch = stamp, batch.id
                commit(ctx, kid, "convert", check=False)
        if plan.release_kids:
            column, value = key[1], key[2]
            for offset, kid in enumerate(plan.kids, start=1):
                kid.parent_item_id = None
                setattr(kid, f"{column}_id", value)
                at = [ident(m) for m in members(ctx.profile_id, key)].index(ident(item)) + offset
                place(ctx, kid, key, at, "convert")
        item.kind = to_kind
        item.citation = plan.new_citation
        commit(ctx, item, "convert")
        for number, spec in enumerate(plan.make_cases, start=1):
            create(ctx, Case, "convert", item=item, citation=spec["citation"], comment=spec["comment"], position=number)
        for number, spec in enumerate(plan.make_children, start=1):
            create(
                ctx, Item, "convert", parent_item=item, kind=KIND_PLAIN, text=spec["text"],
                citation=spec["citation"], position=number,
            )
        return make_result(ctx, item)
