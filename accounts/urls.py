from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views
from .forms import ThrottledAuthenticationForm

urlpatterns = [
    path(
        "login/",
        views.LandingLoginView.as_view(
            template_name="registration/login.html",
            authentication_form=ThrottledAuthenticationForm,
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    # Forgot my password: ask for the email address, the link in the email, choose a new password.
    path("password-reset/", views.ForgotPasswordView.as_view(), name="password_reset"),
    path(
        "password-reset/sent/",
        auth_views.PasswordResetDoneView.as_view(template_name="registration/password_reset_done.html"),
        name="password_reset_done",
    ),
    path(
        "password-reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="registration/password_reset_confirm.html",
            success_url=reverse_lazy("password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetCompleteView.as_view(template_name="registration/password_reset_complete.html"),
        name="password_reset_complete",
    ),
    path("my-settings/", views.my_settings, name="my_settings"),
    path("my-settings/password/", views.MyPasswordChangeView.as_view(), name="password_change"),
    path("my-settings/preview/", views.format_preview, name="format_preview"),
    path("settings/", views.suite_settings, name="settings"),
    path("profiles/", views.profile_list, name="profile_list"),
    path("profiles/new/", views.profile_create, name="profile_create"),
    path("profiles/<int:pk>/edit/", views.profile_edit, name="profile_edit"),
    path("profiles/<int:pk>/delete/", views.profile_delete, name="profile_delete"),
    path("profiles/<int:pk>/clear/", views.profile_clear, name="profile_clear"),
    path("profiles/<int:pk>/offline-link/", views.offline_link_admin, name="offline_link_admin"),
    path("profiles/<int:pk>/restore/", views.profile_restore, name="profile_restore"),
    path("users/", views.user_list, name="user_list"),
    path("users/new/", views.user_create, name="user_create"),
    path("users/<int:pk>/edit/", views.user_edit, name="user_edit"),
    path("users/<int:pk>/delete/", views.user_delete, name="user_delete"),
    path("users/<int:pk>/restore/", views.user_restore, name="user_restore"),
    path("profiles/switch/", views.profile_switch, name="profile_switch"),
    path("profiles/access/", views.admin_profile_access, name="admin_profile_access"),
]
