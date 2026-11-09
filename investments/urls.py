from django.urls import path

from . import pages, views, views_holdings as vh, views_misc as vm, views_catalogue as vc, views_prices as vp, views_txn as vt

# Mounted at /investments/ by config/urls.py. No app namespace: URL names are global and start with ``investments_``,
# like the Fee Register's ``fees_`` names (accounts.context_processors.current_program_key relies on the prefix).
#
# ``REAL`` replaces the empty shell of a page in ``pages.PAGES`` with its real view (the URL name stays the same).
REAL = {
    "dashboard": views.dashboard,
    "start": views.start,
    "holdings": vh.holdings_list,
    "add_1": vh.add_1,
    "add_2": vh.add_2,
    "transactions": vt.transactions_list,
    "txn_new_buy": lambda request: vt.txn_form(request, "buy"),
    "txn_new_sell": lambda request: vt.txn_form(request, "sell"),
    "txn_new_awaiting": lambda request: vt.txn_form(request, "awaiting_buy"),
    "txn_opening": vt.txn_opening,
    "txn_transfer": vt.txn_transfer,
    "txn_switch": vt.txn_switch,
    "txn_to_confirm": vt.to_complete,
    "brokers": vm.brokers_list,
    "history": vm.history_list,
    "settings": vm.settings_general,
    "settings_brokers": vm.settings_brokers,
    "settings_pages": vm.settings_pages,
    "admin_prices": vp.price_sources,
    "admin_upload": vp.price_upload,
    "admin_catalogue": vc.catalogue_list,
}

urlpatterns = [path("", views.landing, name="investments_landing")]
for _page in pages.PAGES:
    urlpatterns.append(path(_page.path, REAL.get(_page.slug) or views.SHELL_VIEWS[_page.slug], name=pages.url_name(_page.slug)))

urlpatterns += [
    # a redemption awaiting its units (no mockup of its own; same form as the awaiting purchase)
    path("transactions/awaiting-redemption/", lambda request: vt.txn_form(request, "awaiting_sell"), name="investments_txn_new_awaiting_sell"),
    path("transactions/available/", views.available_units, name="investments_available_units"),
    path("transactions/<int:pk>/edit/", vt.txn_edit, name="investments_txn_edit"),
    path("transactions/<int:pk>/delete/", vt.txn_delete, name="investments_txn_delete"),
    path("transactions/<int:pk>/complete/", vt.txn_complete, name="investments_txn_complete"),
    path("transactions/<int:pk>/cancel/", vt.txn_cancel, name="investments_txn_cancel"),
    path("transactions/<int:pk>/confirm/", vt.txn_confirm, name="investments_txn_confirm"),
    path("transfers/<int:pk>/delete/", vt.transfer_delete, name="investments_transfer_delete"),
    path("switches/<int:pk>/delete/", vt.switch_delete, name="investments_switch_delete"),
    path("holdings/<int:pk>/", vh.investment, name="investments_investment"),
    path("holdings/<int:pk>/added/", vh.added, name="investments_added"),
    path("holdings/<int:pk>/price/", vh.investment_price, name="investments_investment_price"),
    path("holdings/<int:pk>/price/<int:price_id>/delete/", vh.investment_price_delete, name="investments_investment_price_delete"),
    path("holdings/<int:pk>/value/", vh.investment_altvalue, name="investments_investment_altvalue"),
    path("holdings/<int:pk>/folio/", vh.investment_folio, name="investments_investment_folio"),
    path("holdings/<int:pk>/details/", vh.investment_details, name="investments_investment_details"),
    path("holdings/<int:pk>/shared/", vh.investment_shared, name="investments_investment_shared"),
    path("holdings/<int:pk>/delete/", vh.inv_delete, name="investments_inv_delete"),
    path("brokers/<int:pk>/", vm.broker_detail, name="investments_broker_detail"),
    path("history/<int:pk>/restore/", vm.history_restore, name="investments_history_restore"),
    path("settings/portfolios/", vm.portfolio_action, name="investments_portfolio_action"),
    path("settings/brokers/action/", vm.broker_action, name="investments_broker_action"),
    path("prices/update/", vp.update_prices, name="investments_update_prices"),
    path("settings/catalogue/new/", vc.catalogue_new, name="investments_admin_catalogue_new"),
    path("settings/catalogue/<int:pk>/", vc.catalogue_item, name="investments_admin_catalogue_item"),
    path("settings/catalogue/<int:pk>/action/", vc.catalogue_action, name="investments_admin_catalogue_action"),
    path("prefs/selection/", views.set_selection, name="investments_set_selection"),
    path("prefs/money/", views.set_money_mode, name="investments_set_money_mode"),
]
