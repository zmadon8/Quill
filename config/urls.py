from django.urls import include, path
from django.views.generic import RedirectView

# Browser page requests go Home; anything else gets templates/404.html. See diary/not_found.py.
handler404 = "diary.not_found.not_found"

urlpatterns = [
    path("", include("accounts.urls")),
    path("", include("diary.root_urls")),
    # /caselaw and /caselaw/ go to the Subjects page, /caselaw/subjects/ (permanent, as the owner asked).
    path("caselaw", RedirectView.as_view(pattern_name="diary_home", permanent=True, query_string=True)),
    path("caselaw/", RedirectView.as_view(pattern_name="diary_home", permanent=True, query_string=True)),
    path("caselaw/", include("diary.urls")),
    # /fees and /fees/ open the Fee Register (the user's chosen first page); the landing page itself is a temporary redirect because the
    # first page depends on the user's setting.
    path("fees", RedirectView.as_view(pattern_name="fees_landing", permanent=True, query_string=True)),
    path("fees/", include("fees.urls")),
    # /investments and /investments/ open the Investments program (plan section 15.1).
    path("investments", RedirectView.as_view(pattern_name="investments_landing", permanent=False, query_string=True)),
    path("investments/", include("investments.urls")),
    path("", include("backups.urls")),
    path("", include("mailer.urls")),
]
