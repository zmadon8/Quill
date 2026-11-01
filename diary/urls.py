from django.urls import path

from . import views

# Mounted at /caselaw/ by config/urls.py. No app namespace: URL names stay global so every {% url %} and reverse() is unchanged.
urlpatterns = [
    path("subjects/", views.subjects, name="subjects"),
    path("other-subjects/", views.other_subjects, name="other_subjects"),
    path("search/", views.search, name="search"),
    path("subjects/<int:pk>/", views.subject_contents, name="subject_contents"),
    path("subjects/<int:pk>/read/", views.read_subject, name="read_subject"),
    path("topics/<int:pk>/read/", views.read_topic, name="read_topic"),
    path("subtopics/<int:pk>/read/", views.read_subtopic, name="read_subtopic"),
    path("review/", views.review_list, name="review_list"),
    path("import/", views.import_word, name="import_word"),
    path("profile-settings/", views.profile_settings, name="profile_settings"),
]
