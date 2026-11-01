from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .forms import UserCreateForm, UserEditForm
from .permissions import admin_required

User = get_user_model()


@admin_required
def user_list(request):
    users = User.objects.order_by("username")
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
    elif target.is_superuser and target.is_active:
        others = User.objects.filter(is_superuser=True, is_active=True).exclude(pk=target.pk)
        if not others.exists():
            problem = "This is the last active Admin and cannot be deleted."
    if request.method == "POST":
        if problem:
            messages.error(request, problem)
            return redirect("user_list")
        name = target.username
        target.delete()
        messages.success(request, f"User {name} deleted.")
        return redirect("user_list")
    return render(request, "accounts/user_confirm_delete.html", {"target": target, "problem": problem})
