from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("other-subjects/", views.other_subjects, name="other_subjects"),
    path("search/", views.search, name="search"),
    path("subjects/<int:pk>/", views.subject_contents, name="subject_contents"),
    path("subjects/<int:pk>/read/", views.read_subject, name="read_subject"),
    path("topics/<int:pk>/read/", views.read_topic, name="read_topic"),
    path("subtopics/<int:pk>/read/", views.read_subtopic, name="read_subtopic"),
    path("healthz/", views.healthz, name="healthz"),
]
