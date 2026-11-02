"""Suite level URLs that live in the diary app's views: Home, the legacy /programs/ redirect, healthz,
and the permanent redirects from the old root-level diary URLs to /caselaw/ (item 9)."""
from django.urls import path
from django.views.generic import RedirectView

from . import views


def _moved(old, name, **kw):
    return path(old, RedirectView.as_view(pattern_name=name, permanent=True, query_string=True), name=f"legacy_{name}", **kw)


urlpatterns = [
    path("", views.home, name="home"),
    path("help/", views.help_page, name="help"),
    path("programs/", RedirectView.as_view(pattern_name="home", permanent=False), name="programs_legacy"),
    path("healthz/", views.healthz, name="healthz"),
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
