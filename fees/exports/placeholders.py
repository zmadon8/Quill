"""The Word placeholder map and the accepted tag set (design 8.2, B 7.1).

``build_placeholder_map(memo, settings)`` is a straight port of ``buildBaseMap`` plus
``withShortAliases`` from ``exportService.ts``. ``memo`` is the dict ``memos.get_memo`` returns (snake
case keys, ``Decimal`` money). Every long tag (``LINE_16_NUM_APPEARANCES``) is also exposed under its
short alias (``L16``), and each section flag (``SHOW_APPEARANCES``) under ``IF_APP`` and so on.

The map also carries the five memo-constant text tags taken from the ``FeesSettings`` memo defaults
(R-SET-7): ``MEMO_NAME``/``M1``, ``MEMO_DESIGNATION``/``M2``, ``MEMO_ADDRESS``/``M3``,
``MEMO_BANK_DETAILS``/``M4``, ``MEMO_PAN``/``M5``. The signature tag ``MEMO_SIGNATURE``/``MSIG`` is in
the map with an empty string and in the accepted tag set so upload validation lets it through; the real
work (an inline picture) is done by ``fees.exports.word`` (design 8.4).

Payment data is never in the map, and neither are the internal lines 3, 4 and 25 to 30.

The flag and count rules use ``memo_fees`` helpers where totals are needed; this module only reads the
values ``get_memo`` has already resolved.
"""

import re
from collections.abc import Mapping

from fees.services.fees_in_words import fees_in_words
from fees.services.money import format_currency, format_date

#: Section flag, long name to short alias (``FLAG_ALIASES`` in ``templateTags.mjs``).
FLAG_ALIASES = {
    "SHOW_APPEARANCES": "IF_APP",
    "SHOW_CONFERENCES": "IF_CONF",
    "SHOW_MISC": "IF_MISC",
    "SHOW_PLAINTIFF": "IF_PL",
    "SHOW_DEFENDANT": "IF_DEF",
    "SHOW_CLIENT": "IF_CLIENT",
}

#: Memo-constant text tags: long name, short name, ``FeesSettings`` field.
MEMO_TAGS = (
    ("MEMO_NAME", "M1", "memo_default_name"),
    ("MEMO_DESIGNATION", "M2", "memo_default_designation"),
    ("MEMO_ADDRESS", "M3", "memo_default_address"),
    ("MEMO_BANK_DETAILS", "M4", "memo_default_bank_details"),
    ("MEMO_PAN", "M5", "memo_default_pan"),
)

#: The signature tag, long and short (design 8.4). Not a text substitution.
SIGNATURE_TAGS = ("MEMO_SIGNATURE", "MSIG")

#: Every long line tag the map carries (lines 3, 4 and 25 to 30 are internal and excluded).
LINE_TAGS = (
    "LINE_1_DATE",
    "LINE_2_MEMO_NUMBER",
    "LINE_5_ADDRESSEE_1",
    "LINE_6_ADDRESSEE_2",
    "LINE_7_MATTER_NAME",
    "LINE_8_COURT_NAME",
    "LINE_9_ADD_LEFT",
    "LINE_10_ADD_RIGHT",
    "LINE_11_PLAINTIFF",
    "LINE_12_PLAINTIFF_TYPE",
    "LINE_13_DEFENDANT",
    "LINE_14_DEFENDANT_TYPE",
    "LINE_15_CLIENT",
    "LINE_16_NUM_APPEARANCES",
    "L16W",
    "LINE_17_DATES_APPEARANCES",
    "LINE_18_FEES_PER_APP",
    "LINE_18A_FEES_APPEARANCES",
    "LINE_19_NUM_CONFERENCES",
    "L19W",
    "LINE_20_DATES_CONFERENCES",
    "LINE_21_FEES_PER_CONF",
    "LINE_21A_FEES_CONFERENCES",
    "LINE_22_MISC_DESC",
    "LINE_23_FEES_MISC",
    "LINE_24_TOTAL_FEES",
    "LINE_24A_TOTAL_FEES_WORDS",
)

_LINE_PREFIX = re.compile(r"^LINE_(\d+[A-Z]?)_")


def line_short_name(long_name):
    """``LINE_16_NUM_APPEARANCES`` to ``L16``; ``None`` when ``long_name`` has no ``LINE_n_`` prefix."""
    match = _LINE_PREFIX.match(long_name)
    return f"L{match.group(1)}" if match else None


def _build_tag_sets():
    text = set()
    for long_name in LINE_TAGS:
        text.add(long_name)
        short = line_short_name(long_name)
        if short:
            text.add(short)
    for long_name, short, _field in MEMO_TAGS:
        text.update((long_name, short))
    text.update(SIGNATURE_TAGS)
    flags = set(FLAG_ALIASES) | set(FLAG_ALIASES.values())
    return frozenset(text), frozenset(flags)


#: Plain ``{{TAG}}`` names the upload validation accepts, and the flag names allowed in ``{{#F}}``/``{{/F}}``.
TEXT_TAGS, FLAG_TAGS = _build_tag_sets()


def is_known_tag(name):
    """Whether ``name`` (a tag with any section prefix, whitespace trimmed) is accepted (design 8.1)."""
    if name in TEXT_TAGS:
        return True
    return name[:1] in ("#", "/") and name[1:].strip() in FLAG_TAGS


def short_tag(name):
    """Port of ``shortTag``: maps one tag (with an optional ``#`` ``/`` ``^`` prefix) to its short name."""
    tag = name.strip()
    prefix = tag[0] if tag[:1] in ("#", "/", "^") else ""
    core = tag[1:].strip() if prefix else tag
    short = line_short_name(core)
    if short:
        return prefix + short
    if core in FLAG_ALIASES:
        return prefix + FLAG_ALIASES[core]
    return tag


def _count_with_noun(count, one, many):
    if count and count > 0:
        return f"{count} {one if count == 1 else many}"
    return ""


def _setting(settings, field):
    if settings is None:
        return ""
    if isinstance(settings, Mapping):
        value = settings.get(field)
    else:
        value = getattr(settings, field, "")
    return value or ""


def _money(value):
    return format_currency(value) if value else ""


def _text(value):
    return "" if value is None else str(value)


def _base_map(memo):
    num_app = memo.get("num_appearances") or 0
    num_conf = memo.get("num_conferences") or 0
    show_app = num_app > 0 or (memo.get("fees_per_appearance") or 0) > 0
    show_conf = num_conf > 0 or (memo.get("fees_per_conference") or 0) > 0
    show_misc = (memo.get("fees_misc_drafting") or 0) > 0 or bool(memo.get("misc_drafting_description"))
    plaintiff = memo.get("plaintiff_name") or ""
    defendant = memo.get("defendant_name") or ""
    client = memo.get("client") or ""
    total = memo.get("total_fees") or 0
    return {
        "LINE_1_DATE": format_date(memo["date"]) if memo.get("date") else "",
        "LINE_2_MEMO_NUMBER": _text(memo.get("memo_number")),
        "LINE_5_ADDRESSEE_1": _text(memo.get("addressee_line1")),
        "LINE_6_ADDRESSEE_2": _text(memo.get("addressee_line2")),
        # The Short Name (when set) is what appears in the Word export.
        "LINE_7_MATTER_NAME": _text(memo.get("matter_short_name") or memo.get("matter_name")),
        "LINE_8_COURT_NAME": _text(memo.get("court_name")),
        "LINE_9_ADD_LEFT": _text(memo.get("additional_details_left")),
        "LINE_10_ADD_RIGHT": _text(memo.get("additional_details_right")),
        "LINE_11_PLAINTIFF": _text(plaintiff),
        "LINE_12_PLAINTIFF_TYPE": _text(memo.get("plaintiff_type")),
        "LINE_13_DEFENDANT": _text(defendant),
        "LINE_14_DEFENDANT_TYPE": _text(memo.get("defendant_type")),
        "LINE_15_CLIENT": _text(client),
        "SHOW_APPEARANCES": show_app,
        "SHOW_CONFERENCES": show_conf,
        "SHOW_MISC": show_misc,
        "SHOW_PLAINTIFF": bool(plaintiff.strip()),
        "SHOW_DEFENDANT": bool(defendant.strip()),
        "SHOW_CLIENT": bool(client.strip()),
        "LINE_16_NUM_APPEARANCES": str(num_app) if num_app else "",
        "L16W": _count_with_noun(num_app, "Appearance", "Appearances"),
        "LINE_17_DATES_APPEARANCES": _text(memo.get("dates_of_appearances")),
        "LINE_18_FEES_PER_APP": _money(memo.get("fees_per_appearance")),
        "LINE_18A_FEES_APPEARANCES": _money(memo.get("fees_appearances")),
        "LINE_19_NUM_CONFERENCES": str(num_conf) if num_conf else "",
        "L19W": _count_with_noun(num_conf, "Conference", "Conferences"),
        "LINE_20_DATES_CONFERENCES": _text(memo.get("dates_of_conferences")),
        "LINE_21_FEES_PER_CONF": _money(memo.get("fees_per_conference")),
        "LINE_21A_FEES_CONFERENCES": _money(memo.get("fees_conferences")),
        "LINE_22_MISC_DESC": _text(memo.get("misc_drafting_description")),
        # Line 23 is the raw miscellaneous / drafting fee (B 7.1).
        "LINE_23_FEES_MISC": _money(memo.get("fees_misc_drafting")),
        "LINE_24_TOTAL_FEES": format_currency(total),
        "LINE_24A_TOTAL_FEES_WORDS": fees_in_words(max(total, 0)),
    }


def build_placeholder_map(memo, settings=None):
    """The full ``tag -> value`` map for one memo: strings for text tags, bools for section flags.

    ``memo`` is the ``memos.get_memo`` dict; ``settings`` is the ``FeesSettings`` row or the dict from
    ``settings.get_settings`` (only the five ``memo_default_*`` fields are read).
    """
    base = _base_map(memo)
    for long_name, _short, field in MEMO_TAGS:
        base[long_name] = _text(_setting(settings, field))
    base[SIGNATURE_TAGS[0]] = ""
    out = dict(base)
    for key, value in base.items():
        short = line_short_name(key)
        if short:
            out[short] = value
        elif key in FLAG_ALIASES:
            out[FLAG_ALIASES[key]] = value
    for long_name, short, _field in MEMO_TAGS:
        out[short] = base[long_name]
    out[SIGNATURE_TAGS[1]] = ""
    return out
