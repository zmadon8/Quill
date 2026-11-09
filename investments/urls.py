from django.urls import path

from . import pages, views

# Mounted at /investments/ by config/urls.py. No app namespace: URL names are global and start with ``investments_``,
# like the Fee Register's ``fees_`` names (accounts.context_processors.current_program_key relies on the prefix).
urlpatterns = [path("", views.landing, name="investments_landing")] + [
    path(page.path, views.SHELL_VIEWS[page.slug], name=pages.url_name(page.slug)) for page in pages.PAGES
]
