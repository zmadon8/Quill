from django.urls import path

from . import views

urlpatterns = [
    path("backups/", views.backup_list, name="backup_list"),
    path("backups/now/", views.backup_now, name="backup_now"),
    path("backups/restore/", views.restore_upload, name="restore_upload"),
    path("backups/<int:pk>/download/", views.backup_download, name="backup_download"),
    path("backups/<int:pk>/restore/", views.restore_preview, name="restore_preview"),
]
