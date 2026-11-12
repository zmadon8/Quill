"""How each external file or answer is read, as data an Admin can change (owner request, November 2026).

Every source the program reads has an entry in ``DEFAULTS`` holding exactly the built-in behaviour: the address (with date and symbol
placeholders), the delimiter, the header row, the alias list of each column (the first alias found in the file's header wins), the date
formats, filters such as the NSE series kept, and, for JSON answers, the dotted paths to the fields. An Admin's changes are stored per
source (``DataSourceFormat``) as only the keys that differ, and ``get`` lays them over ``DEFAULTS``.

This is declarative only. Nothing here runs code: addresses are filled in by a whitelist of placeholders (never ``str.format`` with
attributes, never ``eval``), and every stored value is checked by ``validate`` against the type of its built-in value. What cannot be
changed here: a new file structure (nested, binary or multi-sheet files), authentication schemes, and the split and dividend events
of Yahoo.
"""
import copy
import logging
import re
from datetime import date, datetime
from urllib.parse import urlparse

from investments.adapters.base import FormatError

log = logging.getLogger(__name__)

MAX_TEXT = 200
MAX_URL = 500
MAX_ITEMS = 40
MAX_ALIAS = 80

BHAV_DATES = ["%Y-%m-%d", "%d-%m-%Y", "%d-%b-%Y", "%d/%m/%Y", "%Y%m%d"]
DAY_DATES = ["%d-%m-%Y", "%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y"]
SERIES_KEEP = ["EQ", "BE", "BZ", "SM", "ST", "RR", "IV"]


def _equity(url):
    return {
        "url": url,
        "delimiter": ",",
        "header_row": 0,
        "date_formats": list(BHAV_DATES),
        "series_keep": list(SERIES_KEEP),
        "columns": {
            "symbol": ["TckrSymb", "SYMBOL", "SC_NAME"],
            "isin": ["ISIN", "ISIN_CODE"],
            "code": ["FinInstrmId", "SC_CODE"],
            "series": ["SctySrs", "SERIES", "SC_GROUP"],
            "close": ["ClsPric", "CLOSE"],
            "date": ["TradDt", "TIMESTAMP", "TRADING_DATE"],
        },
    }


DEFAULTS = {
    "nse_eq": _equity("https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip"),
    "bse_eq": _equity("https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{ymd}_F_0000.CSV"),
    "nse_idx": {
        "url": "https://nsearchives.nseindia.com/content/indices/ind_close_all_{dmy}.csv",
        "delimiter": ",",
        "header_row": 0,
        "date_formats": list(BHAV_DATES),
        "columns": {"name": ["Index Name"], "date": ["Index Date"], "close": ["Closing Index Value"]},
    },
    "amfi": {
        "url": "https://www.amfiindia.com/spages/NAVAll.txt",
        "delimiter": ";",
        "min_fields": 6,
        "code_col": 0,
        "isin_col": 1,
        "isin_alt_col": 2,
        "name_from_col": 3,
        "nav_col": -2,
        "date_col": -1,
        "date_formats": list(DAY_DATES),
    },
    "mfapi": {
        "url": "https://api.mfapi.in/mf/{code}",
        "rows_path": ["data"],
        "date_key": "date",
        "nav_key": "nav",
        "name_path": ["meta", "scheme_name"],
        "date_formats": list(DAY_DATES),
    },
    "nse_list": {
        "url": "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
        "delimiter": ",",
        "series_keep": list(SERIES_KEEP),
        "columns": {"symbol": ["SYMBOL"], "name": ["NAME OF COMPANY"], "series": ["SERIES"], "isin": ["ISIN NUMBER"]},
    },
    "yahoo": {
        "url": "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={p1}&period2={p2}&interval=1d&events=div%7Csplit",
        "search_url": "https://query1.finance.yahoo.com/v1/finance/search?q={q}&quotesCount=8&newsCount=0",
        "error_path": ["chart", "error"],
        "results_path": ["chart", "result"],
        "timestamps_path": ["timestamp"],
        "closes_path": ["indicators", "quote", 0, "close"],
        "gmtoffset_path": ["meta", "gmtoffset"],
        "name_path": ["meta", "longName"],
        "name_alt_path": ["meta", "shortName"],
        "currency_path": ["meta", "currency"],
        "exchange_path": ["meta", "exchangeName"],
        "exchange_alt_path": ["meta", "fullExchangeName"],
    },
    "twelvedata": {
        "url": "https://api.twelvedata.com/time_series?symbol={symbol}&exchange={exchange}&interval=1day&start_date={start}&outputsize=5000&apikey={key}",
        "status_path": ["status"],
        "ok_value": "ok",
        "message_path": ["message"],
        "code_path": ["code"],
        "values_path": ["values"],
        "date_key": "datetime",
        "close_key": "close",
        "currency_path": ["meta", "currency"],
        "exchange_path": ["meta", "exchange"],
        "date_formats": list(DAY_DATES),
    },
    "price_import": {
        "columns": {
            "symbol": ["symbol", "isin", "scheme code", "scheme_code", "code", "ticker", "instrument"],
            "date": ["date", "trading date", "nav date"],
            "close": ["close", "closing price", "price", "nav"],
            "basis": ["basis"],
        },
    },
    "statement_import": {
        "columns": {
            "date": ["date", "trade date", "transaction date", "date of transaction", "order date", "nav date"],
            "origin": ["origin", "how acquired", "acquired as", "acquisition type", "acquisition", "transaction origin"],
            "side": ["transaction type", "buy/sell", "buy or sell", "trade type", "side", "action", "type"],
            "kind": ["investment type", "asset type", "instrument type", "security type", "type"],
            "investment": ["isin", "investment code", "code", "scheme code", "symbol", "ticker", "scrip code", "scrip", "scheme", "scheme name",
                           "instrument", "security", "stock", "fund", "name"],
            "label": ["investment name", "name of investment", "security name", "scheme name", "scrip name", "stock name", "fund name",
                      "instrument name", "company name", "name"],
            "portfolio": ["portfolio", "portfolio name"],
            "broker": ["broker", "broker name", "platform"],
            "units": ["units", "quantity", "qty"],
            "price": ["price", "nav", "rate", "trade price", "avg price"],
            "amount": ["amount", "value", "net amount", "trade value"],
            "charges": ["charges", "brokerage", "stamp duty", "fees"],
            "folio": ["folio", "folio number", "folio no"],
        },
    },
}

#: What the Admin pages show for each source: (label, what it reads, what the source is called on a SourceRun).
LABELS = {
    "nse_eq": ("NSE bhavcopy (equities)", "bhavcopy"),
    "nse_idx": ("NSE index closes", "bhavcopy"),
    "bse_eq": ("BSE bhavcopy (equities)", "bhavcopy"),
    "amfi": ("AMFI daily NAV file", "amfi"),
    "mfapi": ("mfapi.in fund history", "amfi"),
    "nse_list": ("NSE list of equities", "nse_list"),
    "yahoo": ("Yahoo prices", "yahoo"),
    "twelvedata": ("Twelve Data prices", "yahoo"),
    "price_import": ("Price history upload columns", ""),
    "statement_import": ("Statement and holdings import columns", ""),
}
#: Where each source is tested from: a file at an address (``url``), an answer from a service (``json``) or an uploaded file only (``upload``).
UPLOAD_ONLY = ("price_import", "statement_import")
KEYS = list(DEFAULTS)

#: The placeholders an address may hold, per source (a whitelist: anything else in braces is refused).
DATE_PLACEHOLDERS = {"yyyy", "yy", "mm", "dd", "ymd", "dmy", "MON", "Mon"}
PLACEHOLDERS = {
    "nse_eq": DATE_PLACEHOLDERS, "bse_eq": DATE_PLACEHOLDERS, "nse_idx": DATE_PLACEHOLDERS,
    "amfi": DATE_PLACEHOLDERS, "nse_list": DATE_PLACEHOLDERS, "mfapi": {"code"},
    "yahoo": {"symbol", "p1", "p2", "q"}, "twelvedata": {"symbol", "exchange", "start", "key"},
}
_BRACES = re.compile(r"\{([^{}]*)\}")


def builtin_hosts(key):
    """The hosts of the built-in addresses of ``key`` (the only ones that may receive a secret such as the Twelve Data key)."""
    base = DEFAULTS.get(key, {})
    return {urlparse(v).hostname for name, v in base.items() if (name == "url" or name.endswith("_url")) and isinstance(v, str)} - {None}


def allowed_hosts(key):
    """The hosts an Admin's address may use: the built-in ones, plus those the server owner lists in the environment setting
    ``INVESTMENTS_EXTRA_SOURCE_HOSTS`` (comma-separated; an Admin page cannot write it)."""
    from django.conf import settings

    extra = getattr(settings, "INVESTMENTS_EXTRA_SOURCE_HOSTS", "") or ""
    if isinstance(extra, str):
        extra = extra.split(",")
    return builtin_hosts(key) | {h.strip().lower() for h in extra if h.strip()}
_SPACES = re.compile(r"[\s_]+")


class Format(dict):
    """A merged format. ``custom`` names the top-level keys an Admin has changed."""

    custom = frozenset()


# ---------------------------------------------------------------- reading and saving

def merge(key, cleaned):
    """The built-in format of ``key`` with the (validated) ``cleaned`` values laid over it."""
    out = Format(copy.deepcopy(DEFAULTS[key]))
    for name, value in cleaned.items():
        if isinstance(out.get(name), dict):
            out[name].update(value)
        else:
            out[name] = value
    out.custom = frozenset(cleaned)
    return out


def get(key):
    """The format of ``key``: the built-in one with the Admin's stored changes laid over it. Never raises: without a database (a plain unit
    test) or with a stored value that no longer validates, the built-in format is used."""
    stored = stored_config(key)
    if stored:
        cleaned, errors = validate(key, stored)
        if not errors:
            return merge(key, cleaned)
    return Format(copy.deepcopy(DEFAULTS[key]))


def stored_config(key):
    from django.db import DatabaseError, transaction

    from investments.models import DataSourceFormat

    try:
        with transaction.atomic():                       # a savepoint: a failed query must not poison the caller's transaction
            return dict(DataSourceFormat.objects.filter(key=key).values_list("config", flat=True).first() or {})
    except (DatabaseError, AssertionError) as exc:       # AssertionError: a pure unit test (SimpleTestCase) forbids database access
        if not isinstance(exc, AssertionError):
            log.warning("Stored format of %s could not be read (%s); the built-in format is used for this call.", key, exc)
        return {}


def save(key, submitted, user=None):
    """Validate a complete submitted format, store only what differs from the built-in one. Returns ``(merged, errors)``."""
    cleaned, errors = validate(key, submitted)
    if errors:
        return None, errors
    from investments.models import DataSourceFormat

    changed = {}
    for name, value in cleaned.items():
        default = DEFAULTS[key].get(name)
        if isinstance(default, dict):
            sub = {k: v for k, v in value.items() if default.get(k) != v}
            if sub:
                changed[name] = sub
        elif value != default:
            changed[name] = value
    if changed:
        DataSourceFormat.objects.update_or_create(key=key, defaults={"config": changed, "updated_by": user if getattr(user, "pk", None) else None})
    else:
        DataSourceFormat.objects.filter(key=key).delete()
    return get(key), []


def customised():
    """The keys of the sources an Admin has changed."""
    from investments.models import DataSourceFormat

    return [row.key for row in DataSourceFormat.objects.all() if row.config]


def reset(key):
    from investments.models import DataSourceFormat

    DataSourceFormat.objects.filter(key=key).delete()


# ---------------------------------------------------------------- validation

def _is_path_name(name):
    return name.endswith("_path")


def _text(value, label, errors, limit=MAX_TEXT):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        errors.append(f"{label}: text of 1 to {limit} characters is needed.")
        return None
    if any(ord(c) < 32 for c in value):
        errors.append(f"{label}: control characters are not allowed.")
        return None
    return value.strip()


def check_url(key, value, label="Address"):
    """The address, or an error text. http(s) only; only the placeholders of this source are allowed."""
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_URL:
        return None, f"{label}: an address of up to {MAX_URL} characters is needed."
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or any(c in value for c in " \r\n\t"):
        return None, f"{label}: only http:// or https:// addresses are allowed (no spaces)."
    host = (parsed.hostname or "").lower()
    if "@" in parsed.netloc or host not in allowed_hosts(key):
        return None, (f"{label}: the host '{host or parsed.netloc}' is not allowed for this source. Allowed: {', '.join(sorted(allowed_hosts(key)))}. "
                      "The server owner can add a host in the setting INVESTMENTS_EXTRA_SOURCE_HOSTS.")
    allowed = PLACEHOLDERS.get(key, set())
    if "key" in _BRACES.findall(value) and host not in builtin_hosts(key):
        return None, f"{label}: {{key}} (the server's secret) can only be used with the built-in host."
    for name in _BRACES.findall(value):
        if name not in allowed:
            return None, f"{label}: {{{name}}} is not a placeholder this source can use (allowed: {', '.join('{' + p + '}' for p in sorted(allowed)) or 'none'})."
    rest = _BRACES.sub("", value)
    if "{" in rest or "}" in rest:
        return None, f"{label}: unbalanced braces."
    return value, None


def _date_format(value, label, errors):
    text = _text(value, label, errors, 20)
    if text is None:
        return None
    try:
        probe = datetime(2001, 2, 3).strftime(text)
        if "%" not in text or datetime.strptime(probe, text).date() != date(2001, 2, 3):
            raise ValueError(text)
    except (ValueError, TypeError):
        errors.append(f"{label}: '{text}' is not a date format that reads a full date (for example %Y-%m-%d or %d-%b-%Y).")
        return None
    return text


def _str_list(value, label, errors, kind="text"):
    if not isinstance(value, list) or len(value) > MAX_ITEMS:
        errors.append(f"{label}: a list of up to {MAX_ITEMS} items is needed.")
        return None
    out = []
    for item in value:
        clean = _date_format(item, label, errors) if kind == "date" else _text(item, label, errors, MAX_ALIAS)
        if clean is None:
            return None
        out.append(clean)
    return out


def _path(value, label, errors):
    if not isinstance(value, list) or not 1 <= len(value) <= 10:
        errors.append(f"{label}: a path of 1 to 10 steps is needed.")
        return None
    out = []
    for step in value:
        if isinstance(step, bool) or not isinstance(step, (str, int)) or (isinstance(step, str) and (not step.strip() or len(step) > 60)) \
                or (isinstance(step, int) and not 0 <= step <= 1000):
            errors.append(f"{label}: each step is a field name or a list position (0 or more).")
            return None
        out.append(step.strip() if isinstance(step, str) else step)
    return out


def validate(key, config):
    """``(cleaned, errors)``. Unknown keys, wrong types, over-long values, non-http(s) addresses and unlisted placeholders are refused."""
    if key not in DEFAULTS:
        return {}, [f"Unknown source '{key}'."]
    if not isinstance(config, dict):
        return {}, ["The format must be a set of named values."]
    base = DEFAULTS[key]
    errors, out = [], {}
    for name, value in config.items():
        if name not in base:
            errors.append(f"'{name}' is not a setting of this source.")
            continue
        default = base[name]
        if isinstance(default, dict):
            if not isinstance(value, dict):
                errors.append(f"{name}: a set of named lists is needed.")
                continue
            sub = {}
            for field, aliases in value.items():
                if field not in default:
                    errors.append(f"{name}: '{field}' is not a column of this source.")
                    continue
                cleaned = _str_list(aliases, f"{name}.{field}", errors)
                if cleaned is not None:
                    sub[field] = cleaned
            out[name] = sub
        elif name == "url" or name.endswith("_url"):
            cleaned, error = check_url(key, value, name)
            if error:
                errors.append(error)
            else:
                out[name] = cleaned
        elif _is_path_name(name):
            cleaned = _path(value, name, errors)
            if cleaned is not None:
                out[name] = cleaned
        elif name == "delimiter":
            if value in ("\t", "\\t", "tab"):
                out[name] = "\t"
            elif isinstance(value, str) and len(value) == 1 and value not in ' \r\n"' and ord(value) >= 32:
                out[name] = value
            else:
                errors.append("delimiter: one character is needed (a comma, semicolon, pipe, or tab written as \\t).")
        elif isinstance(default, bool):
            errors.append(f"{name}: not changeable.")
        elif isinstance(default, int):
            if isinstance(value, bool) or not isinstance(value, int) or not -60 <= value <= 200:
                errors.append(f"{name}: a whole number between -60 and 200 is needed.")
            elif name == "header_row" and value < 0:
                errors.append("header_row: 0 or more is needed.")
            else:
                out[name] = value
        elif isinstance(default, list):
            cleaned = _str_list(value, name, errors, "date" if name == "date_formats" else "text")
            if cleaned is not None and name == "date_formats" and not cleaned:
                errors.append("date_formats: at least one format is needed.")
            elif cleaned is not None:
                out[name] = cleaned
        else:
            cleaned = _text(value, name, errors)
            if cleaned is not None:
                out[name] = cleaned
    return out, errors


# ---------------------------------------------------------------- forms: the fields of a format, flat, and back

def fields(key, merged=None):
    """``[(field name, kind, current value)]`` for the edit form; kind is ``url``, ``text``, ``int``, ``list`` or ``path``. Columns are ``columns.symbol``."""
    merged = merged if merged is not None else get(key)
    out = []
    for name, default in DEFAULTS[key].items():
        if isinstance(default, dict):
            out += [(f"{name}.{sub}", "list", merged[name][sub]) for sub in default]
        elif name == "url" or name.endswith("_url"):
            out.append((name, "url", merged[name]))
        elif _is_path_name(name):
            out.append((name, "path", merged[name]))
        elif isinstance(default, int):
            out.append((name, "int", merged[name]))
        elif isinstance(default, list):
            out.append((name, "list", merged[name]))
        else:
            out.append((name, "text", merged[name]))
    return out


def show(value, kind):
    """A value as the form shows it: aliases comma-separated, a path dotted."""
    if kind == "list":
        return ", ".join(value)
    if kind == "path":
        return ".".join(str(s) for s in value)
    return str(value).replace("\t", "\\t")


def parse_form(key, post):
    """The submitted form as a format dict (not yet validated), or ``(None, errors)`` for a value that cannot even be read."""
    out, errors = {}, []
    for name, kind, _value in fields(key):
        raw = (post.get("f_" + name) or "").strip() if kind != "text" else post.get("f_" + name, "")
        if kind == "list":
            value = [part.strip() for part in raw.replace("\n", ",").split(",") if part.strip()]
        elif kind == "path":
            value = [int(s) if s.isdigit() else s for s in (p.strip() for p in raw.split(".")) if s]
        elif kind == "int":
            try:
                value = int(raw)
            except ValueError:
                errors.append(f"{name}: a whole number is needed.")
                continue
        else:
            value = raw
        if "." in name and kind == "list":
            group, field = name.split(".", 1)
            out.setdefault(group, {})[field] = value
        else:
            out[name] = value
    return (out, errors) if not errors else (None, errors)


# ---------------------------------------------------------------- the pieces the adapters share

def expand(template, day=None, **values):
    """Fill the whitelisted placeholders of an address. Date placeholders come from ``day`` (when given), the others from ``values``."""
    table = dict(values)
    if day is not None:
        table.update({"yyyy": f"{day:%Y}", "yy": f"{day:%y}", "mm": f"{day:%m}", "dd": f"{day:%d}", "ymd": f"{day:%Y%m%d}", "dmy": f"{day:%d%m%Y}",
                      "MON": f"{day:%b}".upper(), "Mon": f"{day:%b}"})
    return _BRACES.sub(lambda m: str(table.get(m.group(1), m.group(0))), template)


def url_for(key, fmt, setting_name="", default_override=""):
    """The address to use: an Admin's stored one, else the environment setting (``setting_name``), else the built-in one."""
    if "url" in fmt.custom:
        return fmt["url"]
    if setting_name:
        from django.conf import settings

        return getattr(settings, setting_name, "") or default_override or fmt["url"]
    return default_override or fmt["url"]


def norm(text):
    """A header or alias for comparing: no BOM, no stray spaces, lower case, runs of spaces and underscores as one space."""
    return _SPACES.sub(" ", str(text).replace("\ufeff", "").strip().lower())


def match_columns(headers, columns):
    """``{field: index or None}``: the first alias of each field found among the headers (case, spacing, underscores and a BOM ignored)."""
    seen = {}
    for i, header in enumerate(headers):
        seen[norm(header)] = i
    return {field: next((seen[norm(a)] for a in aliases if norm(a) in seen), None) for field, aliases in columns.items()}


def require(key, label, index, required, headers, columns=None):
    """Raise :class:`FormatError` naming the missing columns (and the headers seen) when a required one was not found."""
    missing = [f for f in required if index.get(f) is None]
    if missing:
        wanted = "; ".join(f"{f} (one of {', '.join((columns or {}).get(f, []))})" if columns else f for f in missing)
        seen = [str(h).replace("\ufeff", "").strip() for h in headers][:15]
        raise FormatError(f"{label}: no column found for {wanted}. Headers seen: {', '.join(seen) or 'none'}.", key=key, missing=missing, headers=seen)


def dig(obj, path, default=None):
    """Follow a path of field names and list positions into parsed JSON; ``default`` when any step is missing."""
    for step in path:
        if isinstance(step, int) and isinstance(obj, list):
            obj = obj[step] if -len(obj) <= step < len(obj) else None
        elif isinstance(step, str) and isinstance(obj, dict):
            obj = obj.get(step)
        else:
            return default
        if obj is None:
            return default
    return obj


def parse_day(text, formats):
    for fmt in formats:
        try:
            return datetime.strptime(str(text).strip(), fmt).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------- failures that must be seen

def failure(inst_id, name, exc, prefix=""):
    """A ``SourceRun.failures`` entry. A :class:`FormatError` carries ``fmt`` (the source key) so it surfaces on the alerts page."""
    entry = {"id": inst_id, "name": name, "error": f"{prefix}{exc}"}
    if isinstance(exc, FormatError):
        entry["fmt"] = exc.key
    return entry


def record_failure(source, name, exc, trigger="cron"):
    """A ``SourceRun`` for a list or file read that failed on its own (no investment involved)."""
    from django.utils import timezone

    from investments.models import SourceRun

    now = timezone.now()
    return SourceRun.objects.create(source=source, trigger=trigger, started=now, finished=now, failures=[failure(0, name, exc)], message=str(exc)[:300])


def clear_failure(source, trigger="cron"):
    """A clean ``SourceRun`` after a list read that worked, when the source's newest run had failures (so its alert goes away)."""
    from django.utils import timezone

    from investments.models import SourceRun

    last = SourceRun.objects.filter(source=source).exclude(finished=None).order_by("-finished", "-id").first()
    if last is not None and last.failures:
        now = timezone.now()
        SourceRun.objects.create(source=source, trigger=trigger, started=now, finished=now)


def problems():
    """The format problems still standing: from the newest finished run of each source, the failures that name a format.
    ``[{key, label, source, name, error, when}]``. A later clean run of that source clears them."""
    from investments.models import SourceRun

    latest = {}
    for run in SourceRun.objects.exclude(finished=None).order_by("-finished", "-id")[:300]:
        latest.setdefault(run.source, run)
    out = []
    for source, run in sorted(latest.items()):
        for item in run.failures or []:
            key = item.get("fmt")
            if key in DEFAULTS:
                out.append({"key": key, "label": LABELS[key][0], "source": source, "name": item.get("name", ""), "error": item.get("error", ""), "when": run.finished})
    return out


def last_runs():
    """``{format key: newest finished SourceRun}`` for the status column of the formats page."""
    from investments.models import SourceRun

    latest = {}
    for run in SourceRun.objects.exclude(finished=None).order_by("-finished", "-id")[:300]:
        latest.setdefault(run.source, run)
    return {key: latest.get(label[1]) for key, label in LABELS.items() if label[1]}


__all__ = ["DEFAULTS", "get", "save", "reset", "validate", "match_columns", "require"]
