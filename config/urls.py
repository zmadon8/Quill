from django.urls import include, path
from django.views.generic import RedirectView

# Django's default 404 template is used when templates/404.html is missing; see diary/not_found.py.
handler404 = "diary.not_found.not_found"

urlpatterns = [
    path("", include("accounts.urls")),
    path("", include("diary.root_urls")),
    # /caselaw and /caselaw/ go to the Subjects page, /caselaw/subjects/ (permanent, as the owner asked).
    path("caselaw", RedirectView.as_view(pattern_name="diary_home", permanent=True, query_string=True)),
    path("caselaw/", RedirectView.as_view(pattern_name="diary_home", permanent=True, query_string=True)),
    path("caselaw/", include("diary.urls")),
    path("", include("backups.urls")),
]
