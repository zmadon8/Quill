from django.urls import path

from . import views, views_edit

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
    path("edit/add/", views_edit.add, name="edit_add"),
    path("edit/rename/", views_edit.rename, name="edit_rename"),
    path("edit/delete/", views_edit.delete, name="edit_delete"),
    path("edit/move/", views_edit.move, name="edit_move"),
    path("edit/move-to/", views_edit.move_to, name="edit_move_to"),
    path("edit/landing/", views_edit.landing, name="edit_landing"),
    path("profile-settings/", views.profile_settings, name="profile_settings"),
]
