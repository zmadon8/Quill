from django.urls import path

from . import views

urlpatterns = [
    path("backups/email/", views.backup_email, name="backup_email"),
]
