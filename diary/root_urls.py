"""Suite level URLs that live in the diary app's views: Home, the legacy /programs/ redirect, healthz,
and the permanent redirects from the old root-level diary URLs to /caselaw/ (item 9)."""
from django.urls import path
from django.views.generic import RedirectView

from . import views, views_offline_link, views_suite_search


def _moved(old, name, **kw):
    return path(old, RedirectView.as_view(pattern_name=name, permanent=True, query_string=True), name=f"legacy_{name}", **kw)


urlpatterns = [
    path("", views.home, name="home"),
    path("help/", views.help_page, name="help"),
    # Owner round (2026-11): Search everything (every program the user can open). /search/ is the legacy diary redirect below.
    path("find/", views_suite_search.suite_search, name="suite_search"),
    path("programs/", RedirectView.as_view(pattern_name="home", permanent=False), name="programs_legacy"),
    path("healthz/", views.healthz, name="healthz"),
    # Round 21 (D100): the secret Offline link. Deliberately public (no login); see views_offline_link.
    path("offline/<str:token>/", views_offline_link.offline_public, name="offline_public"),
    path("offline/<str:token>/download/", views_offline_link.offline_download, name="offline_download"),
    _moved("subjects/", "diary_home"),
    _moved("subjects/<int:pk>/", "subject_contents"),
    _moved("subjects/<int:pk>/read/", "read_subject"),
    _moved("topics/<int:pk>/read/", "read_topic"),
    _moved("subtopics/<int:pk>/read/", "read_subtopic"),
    _moved("other-subjects/", "other_subjects"),
    _moved("search/", "search"),
    _moved("review/", "review_list"),
    _moved("import/", "import_word"),
    _moved("profile-settings/", "profile_settings"),
]
