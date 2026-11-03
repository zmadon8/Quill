import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_GET, require_http_methods

from . import landing, suite
from .clear import ClearRefused, clear_preview, clear_profile
from .forms import MySettingsForm, ProfileForm, SuiteNamesForm, UserCreateForm, UserEditForm
from .models import Profile, ProfileMembership, PurgeLog
from .permissions import admin_required
from .profiles import (
    days_left,
    delete_profile,
    get_profile_for,
    name_clash,
    profile_usage,
    restore_conflicts,
    restore_profile,
    retention_days,
)

User = get_user_model()


logger = logging.getLogger(__name__)


def email_ready():
    """True if this server can send email (the Forgot my password link is hidden otherwise)."""
    from mailer.services import is_configured  # lazy: mailer imports accounts

    return is_configured()


class LandingLoginView(auth_views.LoginView):
    """Sign in, then open a safe ``next`` if there is one, else the user's chosen program, else Home."""

    def get_default_redirect_url(self):
        return landing.landing_url(self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["email_ready"] = email_ready()
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        # Ticked: the session lasts REMEMBER_ME_DAYS. Unticked: it ends when the browser is closed.
        if form.cleaned_data.get("remember_me"):
            self.request.session.set_expiry(settings.REMEMBER_ME_DAYS * 24 * 60 * 60)
        else:
            self.request.session.set_expiry(0)
        return response

    # LoginView.get_success_url uses a safe ``next`` first (host and scheme checked), then this default.


class ForgotPasswordView(auth_views.PasswordResetView):
    """Ask for an email address; if an active account has it, email a one-hour link to choose a new password.

    The answer is always the same page ("if there is an account, a link is on its way") so that nobody can use it to find
    out which addresses are registered. A failure to send is logged, not shown, for the same reason.
    """

    template_name = "registration/password_reset_form.html"
    email_template_name = "registration/password_reset_email.txt"
    subject_template_name = "registration/password_reset_subject.txt"
    success_url = reverse_lazy("password_reset_done")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["email_ready"] = email_ready()
        return context

    def form_valid(self, form):
        if not email_ready():
            form.add_error(None, "Email is not set up on this server. Ask the Admin to set a new password for you.")
            return self.form_invalid(form)
        try:
            return super().form_valid(form)
        except Exception:
            logger.exception("Could not send a password reset email")
            return redirect(self.success_url)


@login_required
@require_http_methods(["GET", "POST"])
def my_settings(request):
    """Every signed-in user: the page to open after login, and (with a diary profile) the number formats."""
    from diary.forms import DiarySettingsForm, preview_rows  # lazy: diary imports accounts

    form = MySettingsForm(request.POST or None, instance=request.user)
    profile = get_profile_for(request.user, suite.KEY_DIARY)
    diary_form = DiarySettingsForm(request.POST or None, user=request.user, profile=profile) if profile else None
    if request.method == "POST":
        # Both forms are checked so that every error is shown at once; nothing is saved unless both are fine.
        valid = form.is_valid()
        if diary_form is not None:
            valid = diary_form.is_valid() and valid
        if valid:
            form.save()
            if diary_form is not None:
                diary_form.save()
            messages.success(request, "Settings saved.")
            return redirect("my_settings")
    return render(
        request,
        "accounts/my_settings.html",
        {
            "form": form,
            "diary_form": diary_form,
            "preview": preview_rows(diary_form.effective()) if diary_form is not None else [],
        },
    )


@login_required
@require_GET
def format_preview(request):
    """The sample for the formats in the query string (the settings page fetches this as you choose)."""
    from diary.forms import FORMAT_FIELDS, DiarySettingsForm, allowed_formats, preview_rows

    chosen = {}
    profile = get_profile_for(request.user, suite.KEY_DIARY)
    if profile:
        chosen = DiarySettingsForm(user=request.user, profile=profile).current()
    chosen = {name: chosen.get(name) for name in FORMAT_FIELDS}
    allowed = allowed_formats()
    for name in FORMAT_FIELDS:
        value = request.GET.get(name, "")
        if value in allowed[name]:  # junk or not-allowed values leave the saved (or standard) format in place
            chosen[name] = value
    return render(request, "accounts/_format_preview.html", {"preview": preview_rows(chosen)})


@admin_required
def user_list(request):
    users = list(User.objects.order_by("username"))
    memberships = {
        m.user_id: m
        for m in ProfileMembership.objects.filter(
            program=suite.KEY_DIARY, profile__deleted_at__isnull=True
        ).select_related("profile")
    }
    for u in users:
        m = memberships.get(u.pk)
        u.diary_profile_name = m.profile.name if m else ""
        u.diary_role_label = m.get_role_display() if m else ""
    return render(request, "accounts/user_list.html", {"users": users})


@admin_required
@require_http_methods(["GET", "POST"])
def user_create(request):
    form = UserCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        messages.success(request, f"User {user.username} created.")
        return redirect("user_list")
    return render(request, "accounts/user_form.html", {"form": form, "title": "New user"})


@admin_required
@require_http_methods(["GET", "POST"])
def user_edit(request, pk):
    target = get_object_or_404(User, pk=pk)
    form = UserEditForm(request.POST or None, instance=target, editing_user=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"User {target.username} updated.")
        return redirect("user_list")
    return render(
        request,
        "accounts/user_form.html",
        {"form": form, "title": f"Edit {target.username}"},
    )


@admin_required
@require_http_methods(["GET", "POST"])
def user_delete(request, pk):
    target = get_object_or_404(User, pk=pk)
    problem = None
    if target.pk == request.user.pk:
        problem = "You cannot delete your own account."
    # No separate "last active Admin" rule is needed here: only an active Admin can reach this
    # view, so deleting any other account always leaves that Admin, and deleting yourself is
    # refused above. (The edit form does need the rule, because there the target may be yourself.)
    if request.method == "POST":
        if problem:
            messages.error(request, problem)
            return redirect("user_list")
        name = target.username
        target.delete()
        messages.success(request, f"User {name} deleted.")
        return redirect("user_list")
    return render(request, "accounts/user_confirm_delete.html", {"target": target, "problem": problem})


@admin_required
@require_http_methods(["GET", "POST"])
def suite_settings(request):
    """Rename the Home page and the programs (Admin only; the names are shared by all users)."""
    names = suite.get_names()
    initial = {"home_name": names[suite.KEY_HOME], "diary_name": names[suite.KEY_DIARY]}
    form = SuiteNamesForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Names saved.")
        return redirect("settings")
    return render(request, "accounts/settings.html", {"form": form})


def _live_profiles():
    return Profile.objects.filter(program=suite.KEY_DIARY, deleted_at__isnull=True)


@admin_required
def profile_list(request):
    profiles = list(_live_profiles().order_by("name"))
    for p in profiles:
        p.member_count, p.subject_count = profile_usage(p)
    deleted = list(
        Profile.objects.filter(program=suite.KEY_DIARY, deleted_at__isnull=False)
        .select_related("deleted_by")
        .order_by("-deleted_at")
    )
    for p in deleted:
        p.days_left = days_left(p)
        p.member_count, p.subject_count = profile_usage(p)
    return render(
        request,
        "accounts/profile_list.html",
        {
            "profiles": profiles,
            "deleted_profiles": deleted,
            "retention_days": retention_days(),
            "purge_logs": PurgeLog.objects.order_by("-ran_at", "-id")[:10],
        },
    )


@admin_required
@require_http_methods(["GET", "POST"])
def profile_create(request):
    form = ProfileForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        profile = form.save()
        messages.success(request, f"Profile {profile.name} created.")
        return redirect("profile_list")
    return render(request, "accounts/profile_form.html", {"form": form, "title": "New profile"})


@admin_required
@require_http_methods(["GET", "POST"])
def profile_edit(request, pk):
    target = get_object_or_404(_live_profiles(), pk=pk)
    form = ProfileForm(request.POST or None, instance=target)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Profile renamed to {target.name}.")
        return redirect("profile_list")
    return render(request, "accounts/profile_form.html", {"form": form, "title": f"Rename {target.name}"})


@admin_required
@require_http_methods(["GET", "POST"])
def profile_delete(request, pk):
    """Soft delete. Refused while the profile has members or live data, unless explicitly confirmed."""
    target = get_object_or_404(_live_profiles(), pk=pk)
    members, subjects = profile_usage(target)
    in_use = bool(members or subjects)
    if request.method == "POST":
        if in_use and request.POST.get("confirm") != "yes":
            messages.error(request, f"Profile {target.name} is in use. Tick the box to confirm, or cancel.")
            return redirect("profile_delete", pk=target.pk)
        name = target.name
        delete_profile(target, request.user)
        messages.success(
            request,
            f"Profile {name} deleted. You can restore it from the Deleted profiles list for {retention_days()} days.",
        )
        return redirect("profile_list")
    return render(
        request,
        "accounts/profile_confirm_delete.html",
        {"target": target, "members": members, "subjects": subjects, "in_use": in_use},
    )


@admin_required
@require_http_methods(["GET", "POST"])
def profile_restore(request, pk):
    """Bring back a deleted profile with its members. Refused if a member now has another profile.

    If a live profile has the same name, the Admin is asked for a new name first.
    """
    target = get_object_or_404(Profile, pk=pk, program=suite.KEY_DIARY, deleted_at__isnull=False)
    conflicts = restore_conflicts(target)
    if conflicts:
        messages.error(
            request,
            f"Profile {target.name} cannot be restored: {', '.join(conflicts)} "
            f"{'has' if len(conflicts) == 1 else 'have'} been given another profile since. "
            "Change their profile on the Users screen first, then try again.",
        )
        return redirect("profile_list")
    if name_clash(target) or (request.method == "POST" and "name" in request.POST):
        form = ProfileForm(request.POST or None, instance=target)
        if request.method == "POST" and form.is_valid():
            form.save()
            restore_profile(target)
            messages.success(request, f"Profile {target.name} restored.")
            return redirect("profile_list")
        return render(
            request,
            "accounts/profile_form.html",
            {
                "form": form,
                "title": f"Restore {target.name}",
                "note": "A profile with this name already exists. Choose a different name for the restored profile.",
            },
        )
    if request.method == "POST":
        restore_profile(target)
        messages.success(request, f"Profile {target.name} restored.")
    return redirect("profile_list")


@admin_required
@require_http_methods(["GET", "POST"])
def profile_clear(request, pk):
    """Delete ALL diary data in a profile (Admin only). Preview first; the profile name must be typed."""
    target = get_object_or_404(_live_profiles(), pk=pk)
    rows = clear_preview(target)
    total = sum(number for _name, number in rows)
    if request.method == "POST":
        if request.POST.get("confirm", "").strip() != target.name:
            messages.error(request, "Nothing was deleted. Type the profile's name exactly to confirm.")
            return redirect("profile_clear", pk=target.pk)
        try:
            counts = clear_profile(target, request.user)
        except ClearRefused as exc:
            messages.error(request, str(exc))
            return redirect("profile_clear", pk=target.pk)
        messages.success(
            request,
            f"All diary data in {target.name} was deleted ({sum(counts.values())} rows). "
            "A backup was taken first (kind: Before clearing profile).",
        )
        return redirect("profile_list")
    return render(request, "accounts/profile_clear.html", {"target": target, "rows": rows, "total": total})
