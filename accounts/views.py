from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from . import suite
from .forms import ProfileForm, SuiteNamesForm, UserCreateForm, UserEditForm
from .models import Profile, ProfileMembership
from .permissions import admin_required
from .profiles import profile_usage

User = get_user_model()


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
    return render(request, "accounts/profile_list.html", {"profiles": profiles})


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
        ProfileMembership.objects.filter(profile=target).delete()
        target.deleted_at = timezone.now()
        target.save(update_fields=["deleted_at", "updated_at"])
        messages.success(request, f"Profile {name} deleted.")
        return redirect("profile_list")
    return render(
        request,
        "accounts/profile_confirm_delete.html",
        {"target": target, "members": members, "subjects": subjects, "in_use": in_use},
    )
