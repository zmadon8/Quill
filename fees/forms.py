"""Form helpers for the Fee Register views (design section 1): the values a form starts with, and (later)
the parsing of a submitted form into the plain dict a service takes.

There is no fee arithmetic here. A form carries the counts and rates the user typed; the total is always
worked out by ``fees.services.memo_fees`` when the memo is saved.
"""
import datetime
from decimal import Decimal, InvalidOperation

from fees.errors import FeesError
from fees.services import matters as matter_service

#: The text fields of a memo form, in page order.
MEMO_TEXT_FIELDS = (
    "addressee_line1",
    "addressee_line2",
    "court_name",
    "additional_details_left",
    "additional_details_right",
    "plaintiff_name",
    "plaintiff_type",
    "defendant_name",
    "defendant_type",
    "client",
    "dates_of_appearances",
    "dates_of_conferences",
    "misc_drafting_description",
)
#: Whole-number fields of a memo form.
MEMO_COUNT_FIELDS = ("num_appearances", "num_conferences", "num_drafts")
#: Money fields of a memo form (a rate or an amount typed by the user).
MEMO_RATE_FIELDS = ("fees_per_appearance", "fees_per_conference", "fees_misc_drafting")
#: Optional override amounts (blank means no override).
MEMO_CUSTOM_FIELDS = (
    "custom_fees_appearances",
    "custom_fees_conferences",
    "custom_fees_misc",
    "custom_total_fees",
)


def _text(value):
    return "" if value is None else str(value)


def blank_memo_form(config):
    """A new memo form's starting values: the user's Settings defaults."""
    form = {name: "" for name in MEMO_TEXT_FIELDS + MEMO_CUSTOM_FIELDS}
    form.update(
        date="",
        matter_id="",
        custom_memo_number="",
        num_appearances="0",
        num_conferences="0",
        num_drafts="0",
        fees_per_appearance=_text(config.get("default_fees_per_appearance", "0")),
        fees_per_conference=_text(config.get("default_fees_per_conference", "0")),
        fees_misc_drafting=_text(config.get("default_fees_misc_drafting", "0")),
        court_name=_text(config.get("default_court_name", "")),
        additional_details_left=_text(config.get("default_additional_details_left", "")),
        additional_details_right=_text(config.get("default_additional_details_right", "")),
    )
    return form


def apply_matter_defaults(form, matter):
    """Prefill ``form`` from a matter's memo defaults (the matter's own value wins over the Settings default)."""
    form["matter_id"] = str(matter.pk)
    for name in matter_service.MEMO_DEFAULT_FIELDS:
        if name in ("notes", "short_name", "addressee_use_firm_name"):
            continue
        value = getattr(matter, name, "")
        if value:
            form[name] = _text(value)
    if matter.addressee_use_firm_name:
        form["addressee_line1"] = matter.firm.name
    return form


def memo_form_from_detail(detail):
    """The form values for an existing memo (a ``memos.get_memo`` dict or a ``create_based_on`` dict)."""
    form = {}
    for name in MEMO_TEXT_FIELDS + MEMO_COUNT_FIELDS + MEMO_RATE_FIELDS + MEMO_CUSTOM_FIELDS:
        form[name] = _text(detail.get(name))
    date = detail.get("date")
    form["date"] = date.isoformat() if hasattr(date, "isoformat") else _text(date)
    form["matter_id"] = _text(detail.get("matter_id"))
    form["custom_memo_number"] = _text(detail.get("custom_memo_number"))
    return form


# ---------------------------------------------------------------------------
# Parsing a typed value
# ---------------------------------------------------------------------------


def parse_date(text, label="Date"):
    """A real ``YYYY-MM-DD`` date from ``text``, or ``None`` when blank. Anything else is ``INVALID_DATE`` (422)."""
    value = (text or "").strip()
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise FeesError("INVALID_DATE", f"{label} must be a real date like 2026-07-15.") from exc


def parse_decimal(text, label="Amount", required=False):
    """A ``Decimal`` from ``text`` (commas allowed), or ``None`` when blank and not required."""
    value = (text or "").strip().replace(",", "")
    if not value:
        if required:
            raise FeesError("INVALID_NUMBER", f"{label} is required.")
        return None
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise FeesError("INVALID_NUMBER", f"{label} must be a number.") from exc
    if not number.is_finite():
        raise FeesError("INVALID_NUMBER", f"{label} must be a number.")
    return number


def parse_int(text, label="Number", default=0):
    """A whole number from ``text``; ``default`` when blank."""
    value = (text or "").strip().replace(",", "")
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise FeesError("INVALID_NUMBER", f"{label} must be a whole number.") from exc


# ---------------------------------------------------------------------------
# Payment form values
# ---------------------------------------------------------------------------

#: How many memo rows a payment form shows (a payment may be split over several memos).
PAYMENT_ROWS = 5


def _padded(rows):
    rows = list(rows)[:PAYMENT_ROWS]
    return rows + [{"memo_number": "", "amount": "", "tds_amount": ""}] * (PAYMENT_ROWS - len(rows))


def blank_payment_form(config, memo=None, prefill=None):
    """A new payment form's starting values. ``memo`` is a ``memos.get_memo`` dict; ``prefill`` a
    ``payments.payment_prefill`` dict (the amount to suggest)."""
    prefill = prefill or {}
    form = {
        "amount": _text(prefill.get("amount", "")),
        "tds_rate": _text(config.get("default_tds_rate", "0")),
        "auto_tds": bool(prefill.get("auto_tds", True)),
        "tds_amount": _text(prefill.get("tds_amount", "")) if prefill.get("tds_amount") else "",
        "date_of_payment": "",
        "payee": "",
        "bank_account_id": "",
        "payment_mode": "",
        "payment_details": "",
        "rows": _padded([]),
    }
    if memo is not None:
        form["rows"] = _padded([{"memo_number": _text(memo.get("memo_number")), "amount": "", "tds_amount": ""}])
    return form


def payment_form_from_dto(dto):
    """The form values for an existing payment (a ``payments.get_payment`` dict)."""
    date = dto.get("date_of_payment")
    rows = [
        {
            "memo_number": _text(a.get("memo_number")),
            "amount": _text(a.get("amount")),
            "tds_amount": _text(a.get("tds_amount")),
        }
        for a in dto.get("allocations", [])
    ]
    return {
        "amount": _text(dto.get("amount")),
        "tds_rate": _text(dto.get("tds_rate")),
        "auto_tds": bool(dto.get("auto_tds")),
        "tds_amount": _text(dto.get("tds_amount")),
        "date_of_payment": date.isoformat() if hasattr(date, "isoformat") else _text(date),
        "payee": _text(dto.get("payee")),
        "bank_account_id": _text(dto.get("bank_account_id")),
        "payment_mode": _text(dto.get("payment_mode")),
        "payment_details": _text(dto.get("payment_details")),
        "rows": _padded(rows),
    }
