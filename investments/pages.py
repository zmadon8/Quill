"""The page table, navigation and shared view helpers for the Investments program (plan 23 and 25.2, mockups/index.html).

``PAGES`` has one row per page of the mockups. Phase 0 serves every row as an empty shell showing its empty-state text,
so the whole menu works; a later phase replaces a row's view with the real one (the URL name stays the same).

Navigation is five top entries (Overview, Holdings, Reports, Alerts, Settings), each with an optional second row of
links, exactly as in the mockups. A page can be hidden from the menu in Settings > Pages (plan 23) except Settings itself.
"""
from collections import namedtuple

from django.urls import reverse

from accounts.models import ROLE_EDITOR
from accounts.profiles import request_memberships, request_role
from accounts.suite import KEY_INVESTMENTS

Page = namedtuple("Page", "slug path title group sub empty admin hideable")

#: Top navigation: (key, label, url name of its first page).
TOP = (
    ("overview", "Overview", "investments_dashboard"),
    ("holdings", "Holdings", "investments_holdings"),
    ("reports", "Reports", "investments_performance"),
    ("alerts", "Alerts", "investments_alerts"),
    ("settings", "Settings", "investments_settings"),
)

_NO_DATA = "Nothing here yet."


def _p(slug, path, title, group, sub=None, empty=_NO_DATA, admin=False, hideable=True):
    return Page(slug, path, title, group, sub, empty, admin, hideable)


PAGES = (
    _p("dashboard", "dashboard/", "Dashboard", "overview", None, "No holdings yet. Add an investment, then record your first purchase."),
    _p("start", "start/", "Getting started", "overview", None, "A new profile starts here: add a broker, add an investment, record a purchase.", hideable=False),
    _p("search", "search/", "Search", "overview", None, "Type at least two letters to search investments, folios, brokers and transactions.", hideable=False),
    # Holdings: investments
    _p("holdings", "holdings/", "Investments", "holdings", "Investments", "No investments yet. Add an investment to begin."),
    _p("add_1", "holdings/add/", "Add investment: type", "holdings", "Investments", "Choose what kind of investment this is."),
    _p("add_2", "holdings/add/share/", "Add investment: find a share", "holdings", "Investments", "Search by company name or code."),
    _p("add_2_fund", "holdings/add/fund/", "Add investment: find a fund plan", "holdings", "Investments", "Search by fund name, then pick the exact plan and option."),
    _p("add_3", "holdings/add/confirm/", "Add investment: confirm", "holdings", "Investments", "Check the name, code and latest price, then confirm."),
    _p("add_4", "holdings/add/details/", "Add investment: details", "holdings", "Investments", "Add folios, links and notes, then record a purchase."),
    _p("add_alt", "holdings/add/alternative/", "Add an alternative investment", "holdings", "Investments", "For anything without a public price: a deposit, PPF, property or gold."),
    _p("inv_share", "holdings/example/share/", "One investment: a share", "holdings", "Investments", "Open an investment from the Investments list."),
    _p("inv_fund", "holdings/example/fund/", "One investment: a mutual fund", "holdings", "Investments", "Open an investment from the Investments list."),
    _p("inv_alt", "holdings/example/alternative/", "One investment: alternative", "holdings", "Investments", "Open an investment from the Investments list."),
    _p("inv_foreign", "holdings/example/foreign/", "One investment: foreign", "holdings", "Investments", "Open an investment from the Investments list."),
    _p("inv_delete", "holdings/example/delete/", "Delete an investment", "holdings", "Investments", "Open an investment from the Investments list.", admin=True),
    # Holdings: transactions
    _p("transactions", "transactions/", "Transactions", "holdings", "Transactions", "No transactions yet. Add a purchase or an opening balance."),
    _p("txn_new_buy", "transactions/buy/", "Add a purchase", "holdings", "Transactions", "Record what you bought."),
    _p("txn_new_sell", "transactions/sell/", "Add a sale", "holdings", "Transactions", "Record what you sold."),
    _p("txn_edit_refused", "transactions/refused/", "An edit that is refused", "holdings", "Transactions", "Shown when a change would leave a broker or folio with negative units."),
    _p("txn_opening", "transactions/opening/", "Opening balance", "holdings", "Transactions", "For holdings bought before you started using the program."),
    _p("txn_transfer", "transactions/transfer/", "Transfer", "holdings", "Transactions", "Move holdings between brokers, folios or portfolios, keeping dates and cost."),
    _p("txn_switch", "transactions/switch/", "Fund switch", "holdings", "Transactions", "A sale of one fund and a purchase of another, linked."),
    _p("txn_new_awaiting", "transactions/awaiting/", "Add a purchase awaiting allotment", "holdings", "Transactions", "Paid, but the units and NAV are not known yet."),
    _p("txn_complete", "transactions/complete/", "Complete a purchase awaiting allotment", "holdings", "Transactions", "Nothing is waiting for allotment."),
    _p("txn_to_confirm", "transactions/to-complete/", "To complete", "holdings", "Transactions", "Nothing to complete. Purchases awaiting allotment and pending SIP entries appear here."),
    _p("import_statement", "transactions/import/", "Import a statement", "holdings", "Transactions", "Load trades from a broker or fund house file, then review them before saving."),
    # Holdings: other
    _p("dividends", "dividends/", "Dividends", "holdings", "Dividends", "No dividends recorded yet."),
    _p("dividend_new", "dividends/new/", "Add a dividend", "holdings", "Dividends", "Record a dividend you received."),
    _p("corporate_actions", "corporate-actions/", "Corporate actions", "holdings", "Corporate actions", "No splits or bonuses recorded."),
    _p("brokers", "brokers/", "Brokers", "holdings", "Brokers", "No brokers yet. Add one in Settings > Brokers."),
    _p("broker_detail", "brokers/example/", "One broker", "holdings", "Brokers", "Open a broker from the Brokers list."),
    # Reports
    _p("performance", "reports/performance/", "Performance", "reports", "Performance", "No performance figures yet. They appear once you have purchases and prices."),
    _p("charts", "reports/charts/", "Charts", "reports", "Charts", "No data to chart yet."),
    _p("value", "reports/value/", "Total Portfolio Value", "reports", "Total Portfolio Value", "No holdings to value yet."),
    _p("annual", "reports/annual/", "Annual Report", "reports", "Annual Report", "No transactions in this financial year."),
    _p("reports", "reports/", "Other reports", "reports", "Other reports", "Pick a report."),
    _p("report_yearly", "reports/yearly/", "Year-by-year returns", "reports", "Other reports", "No completed financial years yet."),
    _p("report_compare_brokers", "reports/compare-brokers/", "Compare brokers", "reports", "Other reports", "Needs holdings with at least two brokers."),
    _p("history", "history/", "History", "reports", "History", "No changes recorded yet."),
    # Alerts
    _p("alerts", "alerts/", "Alerts and guardrails", "alerts", None, "No alerts. Set thresholds in Settings > Alerts."),
    # Settings
    _p("settings", "settings/", "Settings: General", "settings", "General", "Settings.", hideable=False),
    _p("settings_brokers", "settings/brokers/", "Settings: Brokers", "settings", "Brokers", "Add the brokers and platforms you use.", hideable=False),
    _p("settings_alerts", "settings/alerts/", "Settings: Alerts", "settings", "Alerts", "Alert thresholds.", hideable=False),
    _p("settings_display", "settings/display/", "Settings: Display", "settings", "Display", "Display choices.", hideable=False),
    _p("settings_pages", "settings/pages/", "Settings: Pages", "settings", "Pages", "Choose which pages show in the menu.", hideable=False),
    _p("settings_insights", "settings/insights/", "Settings: Insights", "settings", "Insights", "Choose which insights to show.", hideable=False),
    _p("admin_prices", "settings/price-sources/", "Admin: Price sources", "settings", "Price sources", "Price sources are set up in a later release.", admin=True, hideable=False),
    _p("admin_upload", "settings/price-upload/", "Admin: Upload price history", "settings", "Price sources", "Price history upload is set up in a later release.", admin=True, hideable=False),
    _p("admin_price_history", "settings/price-history/", "Admin: Price history", "settings", "Price history", "Pruning, the price archive and pinned prices are set up in a later release.", admin=True, hideable=False),
    _p("admin_catalogue", "settings/catalogue/", "Admin: Investment catalogue", "settings", "Catalogue", "The catalogue is set up in a later release.", admin=True, hideable=False),
    _p("admin_catalogue_item", "settings/catalogue/example/", "Admin: one investment", "settings", "Catalogue", "Open an investment from the catalogue.", admin=True, hideable=False),
)

BY_SLUG = {p.slug: p for p in PAGES}


def url_name(slug):
    return f"investments_{slug}"


def url_of(slug):
    return reverse(url_name(slug))


#: The second row under the header, per top entry: (label, first page slug), in this order.
SUB_ROWS = {
    "holdings": (
        ("Investments", "holdings"), ("Transactions", "transactions"), ("Dividends", "dividends"),
        ("Corporate actions", "corporate_actions"), ("Brokers", "brokers"),
    ),
    "reports": (
        ("Performance", "performance"), ("Charts", "charts"), ("Total Portfolio Value", "value"),
        ("Annual Report", "annual"), ("Other reports", "reports"), ("History", "history"),
    ),
    "settings": (
        ("General", "settings"), ("Brokers", "settings_brokers"), ("Alerts", "settings_alerts"),
        ("Display", "settings_display"), ("Pages", "settings_pages"), ("Insights", "settings_insights"),
        ("Price sources", "admin_prices"), ("Price history", "admin_price_history"), ("Catalogue", "admin_catalogue"),
    ),
}

#: Pages hidden from the menu by the profile's choice (plan 23). Phase 1 reads InvestmentSettings; Phase 0 hides none.
def hidden_slugs(settings_row=None):
    if settings_row is None:
        return set()
    return {s for s in (getattr(settings_row, "hidden_pages", None) or []) if s in BY_SLUG and BY_SLUG[s].hideable}


def current_slug(request):
    match = getattr(request, "resolver_match", None)
    name = (match.url_name or "") if match else ""
    return name[len("investments_"):] if name.startswith("investments_") else ""


def navigation(request, is_admin, hidden=frozenset()):
    """``(top, sub)``: the header entries and the second row for the current page, each a list of dicts."""
    slug = current_slug(request)
    page = BY_SLUG.get(slug)
    group = page.group if page else "overview"
    top = []
    for key, label, name in TOP:
        first = name[len("investments_"):]
        # An entry whose first page is hidden opens the first visible page of its group.
        target = first
        if first in hidden:
            target = next((p.slug for p in PAGES if p.group == key and p.slug not in hidden), first)
        top.append({"key": key, "name": label, "url": url_of(target), "on": key == group})
    sub = []
    for label, first in SUB_ROWS.get(group, ()):
        row_pages = [p for p in PAGES if p.group == group and p.sub == label]
        if first in hidden or (row_pages and row_pages[0].admin and not is_admin):
            continue
        on = bool(page and page.sub == label)
        sub.append({"name": label, "url": url_of(first), "on": on, "admin": bool(row_pages and row_pages[0].admin)})
    return top, sub


def render_context(request, profile, extra=None):
    """The context every Investments page needs: header entries, role and the user's other profiles."""
    from accounts.programs import investments_enabled  # noqa: F401  (kept for clarity: the middleware already guards)

    is_admin = bool(getattr(request.user, "is_admin", False))
    top, sub = navigation(request, is_admin)
    context = {
        "inv_profile": profile,
        "inv_tools": profile is not None,
        "inv_nav": top,
        "inv_sub": sub,
        "can_edit": request_role(request, KEY_INVESTMENTS) == ROLE_EDITOR,
        "inv_other_profiles": [m.profile for m in request_memberships(request, KEY_INVESTMENTS)[1:]],
    }
    context.update(extra or {})
    return context
