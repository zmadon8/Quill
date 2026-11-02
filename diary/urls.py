from django.urls import path
from django.views.generic import RedirectView

from . import views, views_edit, views_export, views_history, views_inline, views_item, views_note, views_trash

# Mounted at /caselaw/ by config/urls.py. No app namespace: URL names stay global so every {% url %} and reverse() is unchanged.
urlpatterns = [
    path("subjects/", views.subjects, name="diary_home"),
    # /caselaw/home/ was never deployed; kept as a harmless alias of the Subjects page (D24).
    path("home/", RedirectView.as_view(pattern_name="diary_home", permanent=True, query_string=True), name="home_alias"),
    path("other-subjects/", views.other_subjects, name="other_subjects"),
    path("search/", views.search, name="search"),
    path("subjects/<int:pk>/", views.subject_contents, name="subject_contents"),
    path("subjects/<int:pk>/read/", views.read_subject, name="read_subject"),
    path("topics/<int:pk>/read/", views.read_topic, name="read_topic"),
    path("subtopics/<int:pk>/read/", views.read_subtopic, name="read_subtopic"),
    path("review/", views.review_list, name="review_list"),
    path("import/", views.import_word, name="import_word"),
    path("edit/add/", views_edit.add, name="edit_add"),
    path("edit/inline/add/", views_inline.add_form, name="edit_inline_add"),
    path("edit/inline/card/", views_inline.edit_card, name="edit_inline_card"),
    path("edit/rename/", views_edit.rename, name="edit_rename"),
    path("edit/delete/", views_edit.delete, name="edit_delete"),
    path("edit/move/", views_edit.move, name="edit_move"),
    path("edit/move-to/", views_edit.move_to, name="edit_move_to"),
    path("edit/landing/", views_edit.landing, name="edit_landing"),
    path("edit/item/<int:pk>/", views_item.item_editor, name="edit_item"),
    path("edit/item/<int:pk>/convert/", views_item.item_convert, name="edit_item_convert"),
    path("edit/note/<int:pk>/", views_note.note_editor, name="edit_note"),
    path("edit/note-link/", views_note.note_link, name="edit_note_link"),
    path("edit/note-pick/", views_note.note_pick, name="edit_note_pick"),
    path("edit/review/", views_item.review, name="edit_review"),
    path("edit/undo/", views_history.undo, name="edit_undo"),
    path("trash/", views_trash.trash, name="trash"),
    path("trash/restore/", views_trash.restore, name="trash_restore"),
    path("trash/delete-permanently/", views_trash.permanent_delete, name="trash_permanent"),
    path("history/<str:kind>/<int:pk>/", views_history.history, name="history"),
    path("history/<str:kind>/<int:pk>/<int:version>/", views_history.history_version, name="history_version"),
    path("history/restore/", views_history.history_restore, name="history_restore"),
    path("export/", views_export.export_page, name="export"),
    path("export/download/", views_export.export_download, name="export_download"),
    path("profile-settings/", views.profile_settings, name="profile_settings"),
]
