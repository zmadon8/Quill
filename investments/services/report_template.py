"""The wording of the report emails (owner round 2026-11), which the profile can edit on Investments > Settings > Email reports.

A template is plain text with tags:

* ``{{tag}}`` is replaced by a value (``TAGS``: the name, what it gives, an example);
* ``{{#block}} ... {{/block}}`` is kept only when the block applies (``BLOCKS``), and ``{{^block}} ... {{/block}}`` only when it does not.

Values are put in once and never read again as tags, so a portfolio named "{{x}}" stays as typed. Blank lines left behind by a block that
was dropped are tidied (never more than one blank line in a row). A blank template means the standard wording (``DEFAULT_SUBJECT``,
``DEFAULT_BODY``). Pure Python: no Django, so it is quick to test.
"""
import re

#: name -> (what it gives, example). In the order the settings page lists them, under the headings of ``TAG_GROUPS``.
TAG_GROUPS = [
    ("Who and when", [
        ("recipient_name", "The recipient's full name (else their user name)", "Ziyad Madon"),
        ("recipient_first_name", "The first word of the recipient's name", "Ziyad"),
        ("site_name", "The website's name", "Madon.co.in"),
        ("profile_name", "The Investments profile's name", "Family"),
        ("report_type", "Weekly, Monthly, Quarterly or Annual", "Monthly"),
        ("report_type_lower", "The same in small letters", "monthly"),
        ("period_start", "First day of the period", "1 Oct 2026"),
        ("period_end", "Last day of the period (the holdings and values are as on this day)", "31 Oct 2026"),
        ("fy_label", "The financial year the period ends in", "2026-27"),
        ("fy_start", "1 April of that financial year", "1 Apr 2026"),
        ("sent_on", "The day the email is sent", "1 Nov 2026"),
    ]),
    ("The period", [
        ("growth", "\"grew by 2.14%\" or \"fell by 0.80%\": the return over the period (money-weighted, not a yearly rate)", "grew by 2.14%"),
        ("growth_pct", "The same as a bare figure, with a minus sign for a fall", "2.14%"),
        ("index_name", "The Default Index", "Nifty 50"),
        ("index_growth", "How the Default Index moved over the period", "grew by 1.02%"),
        ("index_growth_pct", "The same as a bare figure", "1.02%"),
        ("alpha_pct", "Your return less the Index's, in percentage points", "1.12%"),
        ("opening_value", "Market value the day before the period began", "Rs. 46,25,000"),
        ("total_value", "Market value at the end of the period", "Rs. 48,12,550.40"),
        ("value_change", "Change in market value over the period (includes money put in or taken out)", "Rs. 1,87,550.40"),
        ("invested", "Purchases in the period", "Rs. 1,50,000"),
        ("sold", "Sales in the period", "Rs. 82,500"),
        ("net_invested", "Purchases less sales", "Rs. 67,500"),
        ("short_gain", "Short-term capital gains", "Rs. 4,210.55"),
        ("long_gain", "Long-term capital gains", "Rs. 18,750"),
        ("total_gain", "Short and long term capital gains together", "Rs. 22,960.55"),
        ("interest_income", "Other income (gains on investments whose Capital Gains is off)", "Rs. 0"),
        ("dividends", "Dividends received", "Rs. 3,200"),
        ("unrealised_gain", "Gain on what is still held, at the end of the period", "Rs. 6,40,300"),
    ]),
    ("The financial year so far (1 April to the end of the period; on the annual email, the year itself)", [
        ("fy_growth", "Return over the year so far", "grew by 7.81%"),
        ("fy_growth_pct", "The same as a bare figure", "7.81%"),
        ("fy_index_growth", "How the Default Index moved over the year so far", "grew by 5.12%"),
        ("fy_index_growth_pct", "The same as a bare figure", "5.12%"),
        ("fy_alpha_pct", "Your return less the Index's", "2.69%"),
        ("fy_opening_value", "Market value on 31 March", "Rs. 42,10,000"),
        ("fy_invested", "Purchases in the year so far", "Rs. 9,25,000"),
        ("fy_sold", "Sales in the year so far", "Rs. 4,10,000"),
        ("fy_net_invested", "Purchases less sales", "Rs. 5,15,000"),
        ("fy_short_gain", "Short-term capital gains", "Rs. 21,340.10"),
        ("fy_long_gain", "Long-term capital gains", "Rs. 96,500"),
        ("fy_total_gain", "Short and long term together", "Rs. 1,17,840.10"),
        ("fy_interest_income", "Other income so far this financial year", "Rs. 12,480"),
        ("fy_dividends", "Dividends received", "Rs. 18,900"),
    ]),
    ("Portfolios and attachments", [
        ("portfolio_list", "One numbered line per portfolio with its market value (\"1. Equity: Rs. 31,05,200;\"), the last ending with a full stop",
         "1. Equity - Self: Rs. 31,05,200;\n2. Mutual Funds: Rs. 14,58,350.40."),
        ("portfolio_count", "How many portfolios", "2"),
        ("attachment_list", "The names of the attached files, one per line", "Family Holdings and Transactions 2026-10-31.xlsx"),
    ]),
]
TAGS = {name: (what, example) for _heading, rows in TAG_GROUPS for name, what, example in rows}

#: Blocks: name -> when it is kept.
BLOCKS = {
    "if_index": "a Default Index is set",
    "if_portfolios": "the profile has at least one portfolio",
    "if_year": "the financial year so far is a different span from the period (not on the annual email, nor for a period starting 1 April)",
    "if_year_start": "the period starts on 1 April and is not the annual one (so its figures are also the year's)",
    "if_annual": "this is the annual email (the Annual Report is attached)",
    "if_provisional": "some figures are provisional (tentative purchases valued at cost, or a nearest available price)",
}

DEFAULT_SUBJECT = "{{site_name}}: {{report_type_lower}} investments report, {{period_start}} to {{period_end}}"

DEFAULT_BODY = """Dear {{recipient_name}},

During the period {{period_start}} to {{period_end}}, your investments {{growth}}, whereas the Index{{#if_index}} ({{index_name}}){{/if_index}} {{index_growth}}.
{{#if_year}}During the financial year {{fy_label}} so far ({{fy_start}} to {{period_end}}), your investments {{fy_growth}}, whereas the Index{{#if_index}} ({{index_name}}){{/if_index}} {{fy_index_growth}}.
{{/if_year}}
{{#if_portfolios}}The total market value of your investments is {{total_value}}, and that of the individual portfolios is as follows:
{{portfolio_list}}{{/if_portfolios}}{{^if_portfolios}}The total market value of your investments is {{total_value}}.{{/if_portfolios}}

During this period you bought investments for {{invested}} and sold investments for {{sold}}. Short-term capital gains: {{short_gain}}; long-term capital gains: {{long_gain}}; other income: {{interest_income}}.
{{#if_year}}During the financial year {{fy_label}} so far ({{fy_start}} to {{period_end}}), you bought investments for {{fy_invested}} and sold investments for {{fy_sold}}. Short-term capital gains: {{fy_short_gain}}; long-term capital gains: {{fy_long_gain}}; other income: {{fy_interest_income}}.
{{/if_year}}{{#if_year_start}}This period is the start of the financial year {{fy_label}}, so these are also the figures for the year so far.
{{/if_year_start}}
Attached to this email is an excel sheet containing your holdings as on date, and a list of your transactions.
{{#if_annual}}Also attached is the Annual Report for the financial year {{fy_label}}, as an excel sheet.
{{/if_annual}}{{#if_provisional}}
Some figures are provisional (tentative purchases are valued at cost, or a price is the nearest one available).
{{/if_provisional}}
Regards,
{{site_name}}
"""

MAX_LENGTH = 10000
_TOKEN = re.compile(r"\{\{\s*([#^/]?)\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


class TemplateError(ValueError):
    """The template cannot be used; the message says why, in plain words."""


def _parse(text):
    """``[node]``: a node is ``("text", str)``, ``("tag", name)`` or ``("block", name, inverted, [node])``. Raises ``TemplateError``."""
    root = []
    stack = [("", False, root)]
    pos = 0
    for match in _TOKEN.finditer(text):
        literal = text[pos:match.start()]
        if "{{" in literal or "}}" in literal:
            raise TemplateError("There is a {{ or }} that is not part of a tag. A tag looks like {{growth}}.")
        if literal:
            stack[-1][2].append(("text", literal))
        kind, name = match.group(1), match.group(2)
        if kind in ("#", "^"):
            if name not in BLOCKS:
                raise TemplateError(f"{{{{{kind}{name}}}}} is not a known block. The blocks are: {', '.join(BLOCKS)}.")
            children = []
            stack[-1][2].append(("block", name, kind == "^", children))
            stack.append((name, kind == "^", children))
        elif kind == "/":
            if len(stack) == 1 or stack[-1][0] != name:
                raise TemplateError(f"{{{{/{name}}}}} closes a block that is not open." if len(stack) == 1
                                    else f"{{{{/{name}}}}} closes the wrong block: {{{{/{stack[-1][0]}}}}} is needed first.")
            stack.pop()
        else:
            if name not in TAGS:
                raise TemplateError(f"{{{{{name}}}}} is not a known tag. The list of tags is below the box.")
            stack[-1][2].append(("tag", name))
        pos = match.end()
    rest = text[pos:]
    if "{{" in rest or "}}" in rest:
        raise TemplateError("There is a {{ or }} that is not part of a tag. A tag looks like {{growth}}.")
    if rest:
        stack[-1][2].append(("text", rest))
    if len(stack) > 1:
        raise TemplateError(f"{{{{#{stack[-1][0]}}}}} is never closed: add {{{{/{stack[-1][0]}}}}} where it should end.")
    return root


def validate(text):
    """An error message for ``text``, or "" when it can be used (a blank template is fine: it means the standard wording)."""
    if len(text or "") > MAX_LENGTH:
        return f"The wording may be at most {MAX_LENGTH:,} characters."
    try:
        _parse(text or "")
    except TemplateError as exc:
        return str(exc)
    return ""


def _render(nodes, values, flags, out):
    for node in nodes:
        if node[0] == "text":
            out.append(node[1])
        elif node[0] == "tag":
            out.append(str(values.get(node[1], "")))
        else:
            _name, inverted, children = node[1], node[2], node[3]
            if bool(flags.get(_name)) != inverted:
                _render(children, values, flags, out)


def render(text, values, flags, single_line=False):
    """``text`` with its tags filled in from ``values`` and its blocks kept or dropped by ``flags``."""
    out = []
    _render(_parse(text), values, flags, out)
    result = "".join(out)
    if single_line:
        return " ".join(result.split())
    result = re.sub(r"[ \t]+\n", "\n", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip("\n") + "\n"


def subject_of(row_text):
    return (row_text or "").strip() or DEFAULT_SUBJECT


def body_of(row_text):
    return row_text if (row_text or "").strip() else DEFAULT_BODY
