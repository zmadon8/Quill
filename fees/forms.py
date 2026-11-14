"""Form helpers for the Fee Register views (design section 1): the values a form starts with, and (later)
the parsing of a submitted form into the plain dict a service takes.

There is no fee arithmetic here. A form carries the counts and rates the user typed; the total is always
worked out by ``fees.services.memo_fees`` when the memo is saved.
"""
import datetime
import re
from decimal import Decimal, InvalidOperation

from fees.errors import FeesError
from fees.models import Matter, Memo, Payment
from fees.services import matters as matter_service
from fees.services import payments as payment_service
from fees.services.memo_numbers import find_memo_id_by_number
from fees.services.money import format_currency

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
    """A form value as text. A whole-number amount shows without the ``.00`` (item 2.11)."""
    if isinstance(value, Decimal) and value.is_finite() and value == value.to_integral_value():
        return str(int(value))
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
        include_signature="1" if config.get("memo_signature_default") else "",
        additional_details_left="",
        additional_details_right="",
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
    form["include_signature"] = "1" if detail.get("include_signature") else ""
    return form


def echo_memo_form(post, names):
    """``echo_form`` for the memo form, plus the signature box (the last posted value wins)."""
    form = echo_form(post, names)
    form["include_signature"] = "1" if post.getlist("include_signature")[-1:] == ["1"] else ""
    return form


# ---------------------------------------------------------------------------
# Parsing a typed value
# ---------------------------------------------------------------------------


#: Largest money figure a form accepts (the money columns hold 14 digits, two after the point).
MAX_AMOUNT = Decimal(10) ** 11
#: Largest count (appearances, conferences, drafts) a form accepts.
MAX_COUNT = 1_000_000


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
    if not number.is_finite() or abs(number) >= MAX_AMOUNT:
        raise FeesError("INVALID_NUMBER", f"{label} must be a number below {format_currency(MAX_AMOUNT)}.")
    return number


def parse_int(text, label="Number", default=0):
    """A whole number from ``text``; ``default`` when blank."""
    value = (text or "").strip().replace(",", "")
    if not value:
        return default
    try:
        number = int(value)
    except ValueError as exc:
        raise FeesError("INVALID_NUMBER", f"{label} must be a whole number.") from exc
    if number < 0 or number > MAX_COUNT:
        raise FeesError("INVALID_NUMBER", f"{label} must be between 0 and {format_currency(MAX_COUNT)}.")
    return number


# ---------------------------------------------------------------------------
# Payment form values
# ---------------------------------------------------------------------------

#: How many memo rows a payment form shows at least (a payment may be split over up to
#: ``payment_service.MAX_ALLOCATIONS`` memos).
PAYMENT_ROWS = 3

_ROW_KEY = re.compile(r"^alloc_(?:memo|amount|tds)_(\d+)$")


def _padded(rows):
    rows = list(rows)
    return rows + [{"memo_number": "", "amount": "", "tds_amount": ""} for _ in range(PAYMENT_ROWS - len(rows))]


def blank_rows():
    """The empty memo rows a new payment form starts with."""
    return _padded([])


def posted_row_indexes(post):
    """The row numbers present in a submitted payment form, in order (rows may be any number)."""
    found = set()
    for key in post.keys():
        match = _ROW_KEY.match(key)
        if match:
            found.add(int(match.group(1)))
    return sorted(found)


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


def multi_memo_payment_form(config, found):
    """A new payment form for several memos at once (ticked on Outstanding): one row per memo, each for what the
    default payment setting suggests for its due, and the payment amount as their total. ``found`` is a list of
    ``memos.get_memo`` dicts. These are starting values only; the server checks every figure when the form is saved."""
    rate = config.get("default_tds_rate", "0")
    rows = []
    total = Decimal("0.00")
    auto = True
    for memo in found:
        prefill = payment_service.payment_prefill(config["default_payment_amount"], memo["amount_due"], rate)
        auto = prefill["auto_tds"]
        amount = prefill["amount"]
        tds = payment_service.compute_auto_tds(amount, rate) if auto else Decimal("0.00")
        total += amount
        rows.append({"memo_number": _text(memo.get("memo_number")), "amount": _text(amount), "tds_amount": _text(tds)})
    form = blank_payment_form(config)
    form["amount"] = _text(total)
    form["auto_tds"] = auto
    form["rows"] = _padded(rows)
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


# ---------------------------------------------------------------------------
# Reading a submitted form into the dict a service takes
# ---------------------------------------------------------------------------


def clean_text(post, name, model, label=None):
    """The posted text for ``name``, checked against the model field's length. Blank is ``""``."""
    value = (post.get(name) or "").replace("\r\n", "\n")
    if name not in ("additional_details_left", "additional_details_right", "notes", "payment_details",
                    "dates_of_appearances", "dates_of_conferences", "misc_drafting_description"):
        value = value.strip()
    limit = model._meta.get_field(name).max_length
    if limit is not None and len(value) > limit:
        raise FeesError("INVALID_TEXT", f"{label or name.replace('_', ' ').capitalize()} must be at most {limit} characters.")
    return value


def memo_data_from_post(post):
    """The memo dict for ``memos.create_memo`` / ``update_memo`` from a submitted memo form.

    The form carries counts and rates only; the total is worked out by the service. A blank override means no
    override (``None``).
    """
    matter_id = (post.get("matter_id") or "").strip()
    data = {
        "date": parse_date(post.get("date")),
        "matter_id": int(matter_id) if matter_id.isdigit() else None,
        "custom_memo_number": (post.get("custom_memo_number") or "").strip(),
    }
    for name in MEMO_TEXT_FIELDS:
        data[name] = clean_text(post, name, Memo)
    for name in MEMO_COUNT_FIELDS:
        data[name] = parse_int(post.get(name), name.replace("_", " ").capitalize())
    for name in MEMO_RATE_FIELDS:
        data[name] = parse_decimal(post.get(name), name.replace("_", " ").capitalize()) or Decimal("0")
    for name in MEMO_CUSTOM_FIELDS:
        data[name] = parse_decimal(post.get(name), name.replace("_", " ").capitalize())
    # The signature box is sent (a hidden 0 before the box) only when the profile has a signature
    # image; when absent the memo keeps what it has.
    if "include_signature" in post:
        data["include_signature"] = post.getlist("include_signature")[-1] == "1"
    return data


def payment_data_from_post(post, profile, bank_ids):
    """The payment dict for ``payments.add_payment`` / ``update_payment`` from a submitted payment form.

    ``bank_ids`` are the ids of the profile's own bank accounts. Memo rows are matched by memo number. A single
    row with no amount takes the payment amount and the payment TDS; with several rows each needs an amount.
    ``allocations`` is always present, so an edit with every row blank makes the payment unaccounted.
    """
    amount = parse_decimal(post.get("amount"), "Amount received", required=True)
    rate = parse_decimal(post.get("tds_rate"), "TDS rate") or Decimal("0")
    auto_tds = (post.get("auto_tds") or "") == "1"
    tds_entered = parse_decimal(post.get("tds_amount"), "TDS amount")
    bank = (post.get("bank_account_id") or "").strip()
    if bank and (not bank.isdigit() or int(bank) not in bank_ids):
        raise FeesError("INVALID_PAYMENT", "Choose one of your own bank accounts.")
    data = {
        "amount": amount,
        "tds_rate": rate,
        "auto_tds": auto_tds,
        "tds_amount": tds_entered,
        "date_of_payment": parse_date(post.get("date_of_payment"), "Date of payment"),
        "payee": clean_text(post, "payee", Payment),
        "bank_account_id": int(bank) if bank else None,
        "payment_mode": clean_text(post, "payment_mode", Payment),
        "payment_details": clean_text(post, "payment_details", Payment),
    }
    rows = []
    for i in posted_row_indexes(post):
        number = (post.get(f"alloc_memo_{i}") or "").strip()
        row_amount = parse_decimal(post.get(f"alloc_amount_{i}"), "Memo amount")
        row_tds = parse_decimal(post.get(f"alloc_tds_{i}"), "Memo TDS")
        if not number and row_amount is None and row_tds is None:
            continue
        memo_id = find_memo_id_by_number(profile, number)
        if memo_id is None:
            raise FeesError("INVALID_PAYMENT", f'There is no numbered memo "{number}".')
        rows.append({"memo_id": memo_id, "amount": row_amount, "tds_amount": row_tds})
        if len(rows) > payment_service.MAX_ALLOCATIONS:
            raise FeesError(
                "INVALID_PAYMENT",
                f"A payment can be split over at most {payment_service.MAX_ALLOCATIONS} memos.",
            )
    if len(rows) == 1:
        if rows[0]["amount"] is None and amount is not None:
            rows[0]["amount"] = amount
        if rows[0]["tds_amount"] is None and amount is not None:
            rows[0]["tds_amount"] = payment_service.resolve_tds_amount(amount, rate, auto_tds, tds_entered)
    for row in rows:
        if row["amount"] is None:
            raise FeesError("INVALID_PAYMENT", "Enter an amount for each memo.")
    data["allocations"] = rows
    return data


def echo_form(post, names):
    """The submitted values for ``names`` as a form dict (so a failed save shows what the user typed)."""
    return {name: post.get(name, "") for name in names}


def matter_data_from_post(post):
    """``(name, group_id, firm_id, memo_defaults)`` from a submitted matter form."""
    defaults = {}
    for name in matter_service.MEMO_DEFAULT_FIELDS:
        if name == "addressee_use_firm_name":
            defaults[name] = (post.get(name) or "") == "1"
        else:
            defaults[name] = clean_text(post, name, Matter)
    firm = (post.get("firm_id") or "").strip()
    group = (post.get("group_id") or "").strip()
    return (
        clean_text(post, "name", Matter, "Name"),
        int(group) if group.isdigit() else None,
        int(firm) if firm.isdigit() else None,
        defaults,
    )


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

#: Settings keys that are on/off switches (a form sends a hidden ``0`` before the box, so the last value wins).
SETTINGS_FLAGS = (
    "hide_payment_when_paid",
    "default_lines_enabled",
    "show_status_dots",
    "statistics_enabled",
    "show_bank",
    "memo_signature_default",
)
#: Settings keys that are text or choices (passed through as typed; the service validates them).
SETTINGS_TEXT = (
    "default_court_name",
    "list_default_filter",
    "initial_financial_year",
    "memos_start_year",
    "feebook_start_year",
    "money_unit",
    "money_suffix_thousands",
    "money_suffix_lac",
    "money_suffix_crore",
    "default_payment_amount",
    "export_owner_name",
    "memo_filename_pattern",
    "memo_default_name",
    "memo_default_designation",
    "memo_default_address",
    "memo_default_bank_details",
    "memo_default_pan",
)
#: Settings keys that are numbers (blank resets the field to its default).
SETTINGS_NUMBERS = (
    "default_fees_per_appearance",
    "default_fees_per_conference",
    "default_fees_misc_drafting",
    "default_tds_rate",
    "overdue_days",
)


def settings_data_from_post(post):
    """The partial settings dict for ``settings.update_settings``: only keys present in the form are included."""
    data = {}
    for name in SETTINGS_FLAGS:
        if name in post:
            data[name] = post.getlist(name)[-1] == "1"
    for name in SETTINGS_TEXT:
        if name in post:
            data[name] = (post.get(name) or "").replace("\r\n", "\n")
    for name in SETTINGS_NUMBERS:
        if name in post:
            value = (post.get(name) or "").strip()
            data[name] = value or None
    return data
