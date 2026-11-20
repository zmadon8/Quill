"""The page table, navigation and shared view helpers for the Investments program (plan 23 and 25.2, mockups/index.html).

``PAGES`` has one row per page of the mockups. Phase 0 serves every row as an empty shell showing its empty-state text,
so the whole menu works; a later phase replaces a row's view with the real one (the URL name stays the same).

Navigation is five top entries (Home, Holdings, Reports, Catalogue, History), each with an optional second row of links.
Alerts is a tab of Reports, and Dividends sits inside Corporate Actions as a third row (owner round 2026-11).
"""
from collections import namedtuple

from django.urls import reverse

from accounts.models import ROLE_EDITOR
from accounts.profiles import request_memberships, request_role
from accounts.suite import KEY_INVESTMENTS

Page = namedtuple("Page", "slug path title group sub empty admin")

#: Top navigation: (key, label, url name of its first page).
TOP = (
    ("overview", "Home", "investments_dashboard"),
    ("holdings", "Holdings", "investments_holdings"),
    ("reports", "Reports", "investments_performance"),
    ("catalogue", "Catalogue", "investments_admin_catalogue"),
    ("history", "History", "investments_history"),
)

_NO_DATA = "Nothing here yet."


def _p(slug, path, title, group, sub=None, empty=_NO_DATA, admin=False):
    return Page(slug, path, title, group, sub, empty, admin)


PAGES = (
    _p("dashboard", "dashboard/", "Dashboard", "overview", None, "No holdings yet. Add an investment, then record your first purchase."),
    _p("start", "start/", "Getting started", "overview", None, "A new profile starts here: add a broker, add an investment, record a purchase."),
    _p("search", "search/", "Search", "overview", None, "Type at least two letters to search investments, folios, brokers and transactions."),
    # Holdings: investments
    _p("holdings", "holdings/", "Investments", "holdings", "Investments", "No investments yet. Add an investment to begin."),
    _p("add_1", "holdings/add/", "New Investment", "holdings", "New Investment", "Choose what kind of investment this is."),
    _p("add_2", "holdings/add/details/", "Add investment: details", "holdings", "New Investment", "Search by company name or code."),
    # Holdings: transactions
    _p("transactions", "transactions/", "Transactions", "holdings", "Transactions", "No transactions yet. Add a purchase or an opening balance."),
    _p("txn_new_buy", "transactions/buy/", "Add a purchase", "holdings", "Transactions", "Record what you bought."),
    _p("txn_new_sell", "transactions/sell/", "Add a sale", "holdings", "Transactions", "Record what you sold."),
    _p("txn_opening", "transactions/opening/", "Opening Balance", "holdings", "Transactions", "For holdings bought before you started using the program."),
    _p("txn_transfer", "transactions/transfer/", "Transfer", "holdings", "Transactions", "Move holdings between brokers, folios or portfolios, keeping dates and cost."),
    _p("txn_switch", "transactions/switch/", "Fund switch", "holdings", "Transactions", "A sale of one fund and a purchase of another, linked."),
    _p("txn_to_confirm", "transactions/to-complete/", "To complete", "holdings", "Transactions", "Nothing to complete. Tentative entries and pending SIP entries appear here."),
    _p("import_statement", "transactions/import/", "Import a Statement", "holdings", "Transactions", "Load trades from a broker or fund house file, then review them before saving."),
    # Holdings: other
    _p("dividends", "dividends/", "Dividends", "holdings", "Corporate Actions", "No dividends recorded yet."),
    _p("dividend_new", "dividends/new/", "Add a dividend", "holdings", "Corporate Actions", "Record a dividend you received."),
    _p("corporate_actions", "corporate-actions/", "Corporate Actions", "holdings", "Corporate Actions", "No splits or bonuses recorded."),
    _p("brokers", "brokers/", "Brokers", "holdings", "Brokers", "No brokers yet. Add one in Settings > Brokers."),
    # Reports
    _p("performance", "reports/performance/", "Performance", "reports", "Performance", "No performance figures yet. They appear once you have purchases and prices."),
    _p("charts", "reports/charts/", "Charts", "reports", "Charts", "No data to chart yet."),
    _p("value", "reports/value/", "Total Portfolio Value", "reports", "Total Portfolio Value", "No holdings to value yet."),
    _p("annual", "reports/annual/", "Annual Report", "reports", "Annual Report", "No transactions in this financial year."),
    _p("profit_loss", "reports/profit-loss/", "Profit / Loss", "reports", "Profit / Loss", "No sales yet."),
    _p("alerts", "alerts/", "Alerts and guardrails", "reports", "Alerts", "No alerts. Set thresholds under Alert settings on this page."),
    _p("reports", "reports/", "Other Reports", "reports", "Other Reports", "Pick a report."),
    _p("report_yearly", "reports/yearly/", "Year-by-year returns", "reports", "Other Reports", "No completed financial years yet."),
    _p("report_compare_brokers", "reports/compare-brokers/", "Compare brokers", "reports", "Other Reports", "Needs holdings with at least two brokers."),
    _p("history", "history/", "History", "history", None, "No changes recorded yet."),
    # Settings
    _p("settings", "settings/", "Settings: General", "settings", "General", "Settings."),
    _p("settings_brokers", "settings/brokers/", "Settings: Brokers", "settings", "Brokers", "Add the brokers and platforms you use."),
    _p("settings_display", "settings/display/", "Settings: Display", "settings", "Display", "Display choices."),
    _p("settings_insights", "settings/insights/", "Settings: Insights", "settings", "Insights", "Choose which insights to show."),
    _p("settings_indices", "settings/indices/", "Settings: Indices", "settings", "Indices", "The indices investments are compared with."),
    _p("settings_email", "settings/email-reports/", "Settings: Email reports", "settings", "Email reports", "Weekly, monthly, quarterly and annual report emails."),
    # Catalogue (owner round 2026-11): the shared catalogue, price history and price sources are a page of their own, not Settings.
    _p("admin_catalogue", "catalogue/", "Investment catalogue", "catalogue", "Catalogue", "No shared investments yet."),
    _p("admin_price_history", "catalogue/price-history/", "Admin: Price history", "catalogue", "Price history", "Pruning, the price archive and pinned prices are set up in a later release.", admin=True),
    _p("admin_prices", "catalogue/price-sources/", "Admin: Price sources", "catalogue", "Price sources", "Price sources are set up in a later release.", admin=True),
    _p("admin_upload", "catalogue/price-upload/", "Admin: Upload price history", "catalogue", "Price sources", "Price history upload is set up in a later release.", admin=True),
)

BY_SLUG = {p.slug: p for p in PAGES}

#: Pages reached by id or as a step of another page: url name suffix -> (top group, second-row label). They share the menu
#: state of the page they belong to. (`investments_<suffix>` is the URL name.)
EXTRA = {
    "investment": ("holdings", "Investments"), "added": ("holdings", "New Investment"), "inv_delete": ("holdings", "Investments"),
    "txn_edit": ("holdings", "Transactions"), "txn_complete": ("holdings", "Transactions"), "txn_refused": ("holdings", "Transactions"),
    "broker_detail": ("holdings", "Brokers"), "admin_catalogue_item": ("catalogue", "Catalogue"), "report": ("reports", "Other Reports"),
    "profit_loss_year": ("reports", "Profit / Loss"),
    "dividend_edit": ("holdings", "Corporate Actions"), "corporate_action_edit": ("holdings", "Corporate Actions"),
    "admin_source_formats": ("catalogue", "Price sources"), "admin_source_format": ("catalogue", "Price sources"),
}


def url_name(slug):
    return f"investments_{slug}"


def url_of(slug):
    return reverse(url_name(slug))


#: The second row under the header, per top entry: (label, first page slug), in this order.
SUB_ROWS = {
    "holdings": (
        ("Investments", "holdings"), ("Transactions", "transactions"), ("New Investment", "add_1"),
        ("Corporate Actions", "corporate_actions"), ("Brokers", "brokers"),
    ),
    "reports": (
        ("Performance", "performance"), ("Charts", "charts"), ("Total Portfolio Value", "value"),
        ("Annual Report", "annual"), ("Profit / Loss", "profit_loss"), ("Alerts", "alerts"), ("Other Reports", "reports"),
    ),
    "settings": (
        ("General", "settings"), ("Brokers", "settings_brokers"),
        ("Display", "settings_display"), ("Insights", "settings_insights"), ("Indices", "settings_indices"),
        ("Email reports", "settings_email"),
    ),
    "catalogue": (
        ("Catalogue", "admin_catalogue"), ("Price history", "admin_price_history"), ("Price sources", "admin_prices"),
    ),
}

#: A third row under a second-row tab: tab label -> ((label, first page slug), ...). The pages of each are listed in THIRD.
THIRD_ROWS = {
    "Corporate Actions": (("Actions", "corporate_actions"), ("Dividends", "dividends")),
}
#: url name suffix -> its third-row label.
THIRD = {
    "corporate_actions": "Actions", "corporate_action_edit": "Actions",
    "dividends": "Dividends", "dividend_new": "Dividends", "dividend_edit": "Dividends",
}


def third_row(request, sub_label):
    """The third row (a list of dicts) for the current page, or [] when its tab has none."""
    slug = current_slug(request)
    current = THIRD.get(slug)
    return [{"name": label, "url": url_of(first), "on": label == current} for label, first in THIRD_ROWS.get(sub_label or "", ())]


def menu_slugs():
    """The pages a header entry or a sub-tab opens. Their name is already on screen, underlined, so (as in the Fee Register)
    their own title is kept only for screen readers."""
    return ({name[len("investments_"):] for _k, _l, name in TOP} | {first for rows in SUB_ROWS.values() for _l, first in rows}
            | {first for rows in THIRD_ROWS.values() for _l, first in rows})


def current_slug(request):
    match = getattr(request, "resolver_match", None)
    name = (match.url_name or "") if match else ""
    return name[len("investments_"):] if name.startswith("investments_") else ""


def _on_settings_page(request):
    """True on a Settings page: its pages are listed down the left (as Backup's sections are) instead of in the row under the header."""
    slug = current_slug(request)
    page = BY_SLUG.get(slug)
    extra = EXTRA.get(slug)
    return (page.group if page else (extra[0] if extra else "overview")) == "settings"


def navigation(request, is_admin):
    """``(top, sub)``: the header entries and the second row for the current page, each a list of dicts."""
    slug = current_slug(request)
    page = BY_SLUG.get(slug)
    extra = EXTRA.get(slug)
    group = page.group if page else (extra[0] if extra else "overview")
    sub_label = page.sub if page else (extra[1] if extra else None)
    top = []
    for key, label, name in TOP:
        first = name[len("investments_"):]
        top.append({"key": key, "name": label, "url": url_of(first), "on": key == group})
    sub = []
    for label, first in SUB_ROWS.get(group, ()):
        row_pages = [p for p in PAGES if p.group == group and p.sub == label]
        if row_pages and row_pages[0].admin and not is_admin:
            continue
        on = sub_label == label
        sub.append({"name": label, "url": url_of(first), "on": on, "admin": bool(row_pages and row_pages[0].admin)})
    return top, sub


def render_context(request, profile, extra=None):
    """The context every Investments page needs: header entries, role, the profile's settings and the user's other profiles."""
    from investments.services import core, masters

    is_admin = bool(getattr(request.user, "is_admin", False))
    settings_row = core.get_settings(profile, create=False) if profile is not None else None
    top, sub = navigation(request, is_admin)
    on_sub = next((s["name"] for s in sub if s["on"]), None)
    context = {
        "inv_third": third_row(request, on_sub),
        "inv_sub_side": _on_settings_page(request),
        "inv_profile": profile,
        "inv_settings": settings_row,
        "inv_tools": profile is not None,
        "inv_nav": top,
        "inv_sub": sub,
        "inv_title_in_menu": current_slug(request) in menu_slugs(),
        "inv_money_mode": masters.money_preference(request.user, profile) if profile is not None else "auto",
        **_alert_badge(profile),
        "can_edit": request_role(request, KEY_INVESTMENTS) == ROLE_EDITOR,
        "inv_other_profiles": [m.profile for m in request_memberships(request, KEY_INVESTMENTS)[1:]],
    }
    context.update(extra or {})
    return context


def _alert_badge(profile):
    """The nav badge: the count when the alerts are already worked out, else a URL the page asks for it after it has loaded.

    Working the alerts out (``alerts.count``) can mean evaluating every holding, so it must not hold up each page."""
    if profile is None:
        return {"inv_alert_count": 0, "inv_alert_url": ""}
    from django.urls import reverse

    from investments.services import alerts

    count = alerts.peek_count(profile)
    if count is None:
        return {"inv_alert_count": 0, "inv_alert_url": reverse("investments_alert_count")}
    return {"inv_alert_count": count, "inv_alert_url": ""}
