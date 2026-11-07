import logging
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import landing, programs, suite, user_trash
from .clear import ClearRefused, clear_preview, clear_profile
from .forms import MyAccountForm, MyDisplayForm, UsernamePasswordResetForm, _client_ip, ProfileForm, SuiteNamesForm, UserCreateForm, UserEditForm
from .models import OfflineLink, Profile, ProfileMembership, PurgeLog, ResetRequest, prune_reset_requests
from .permissions import admin_required
from .profiles import (
    days_left,
    delete_profile,
    get_profile_for,
    name_clash,
    profile_usage,
    request_profile,
    restore_profile,
    retention_days,
    use_profile,
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


RESET_PER_EMAIL = 3  # reset requests per account (username; it was the email address before D91) per hour
RESET_PER_IP = 10  # reset requests per visitor (IP address) per hour
RESET_WINDOW = timedelta(hours=1)


def reset_limited(request, username):
    """True if this account (username) or visitor has asked too often in the last hour; otherwise record this request.

    A request for a name with no account counts the same as one with an account, so the limit cannot be used to tell
    the two apart. (The column is still called ``email_lower``: it held the address before D91.)
    """
    email_lower = "user:" + (username or "").strip().lower()[:240]
    ip = _client_ip(request)
    now = timezone.now()
    prune_reset_requests(now)
    recent = ResetRequest.objects.filter(at__gte=now - RESET_WINDOW)
    if recent.filter(email_lower=email_lower).count() >= RESET_PER_EMAIL or recent.filter(ip=ip).count() >= RESET_PER_IP:
        return True
    ResetRequest.objects.create(email_lower=email_lower, ip=ip, at=now)
    return False


class ForgotPasswordView(auth_views.PasswordResetView):
    """Forgot my password, by USERNAME (D91). The owner chose plain answers: "Email sent", "No recovery email address
    found with this user." or "User not found." (so the page does say whether a username exists; the hourly limits stop
    anyone from trying many names). A disabled account counts as not found. The link works for one hour."""

    form_class = UsernamePasswordResetForm
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
        username = form.cleaned_data["username"].strip()
        if reset_limited(self.request, username):
            form.add_error(None, "Too many requests. Please try again in an hour.")
            return self.form_invalid(form)
        user = User._default_manager.filter(username__iexact=username, is_active=True).first()
        if user is None:
            form.add_error("username", "User not found.")
            return self.form_invalid(form)
        if not (user.email or "").strip() or not user.has_usable_password():
            form.add_error("username", "No recovery email address found with this user.")
            return self.form_invalid(form)
        try:
            return super().form_valid(form)
        except Exception:
            logger.exception("Could not send a password reset email")
            form.add_error(None, "The email could not be sent. Please try again later, or ask the Admin.")
            return self.form_invalid(form)


#: Old ``?tab=`` names from before the sections: "numbers" was the Case Law Diary tab.
SECTION_ALIASES = {"numbers": "diary"}


@login_required
@require_http_methods(["GET", "POST"])
def my_settings(request):
    """My settings: everything that is only mine, in sections with a Save each (the user name in the header opens it).

    Account (email, password), Display (open after login, justify text), Case Law Diary (opening page, number formats,
    date in Word file names: ``diary.UserSettings``) and Fee Register (Opening page, Items per page: ``FeesUserPrefs``
    key ``settings``). The last two show only for a user who can open that program. The program-wide choices (reading,
    Word import, the Fee Register's memos and payments ...) are on each program's own Settings tab.

    A POST names the section it saves (``tab``) and checks only that section's form. A POST naming no section (an
    older form) saves the Account, Display and Case Law Diary fields it carries, as before.
    """
    from diary.forms import DiarySettingsForm, preview_rows  # lazy: diary imports accounts

    profile = request_profile(request)
    fees_profile = request_profile(request, suite.KEY_FEES) if programs.fees_enabled() else None
    sections = ["account", "display"] + (["diary"] if profile else []) + (["fees"] if fees_profile else [])
    posted = SECTION_ALIASES.get(request.POST.get("tab") or "", request.POST.get("tab") or "")
    if posted not in sections:
        posted = ""  # an older form (or a section this user does not have): the legacy fields are saved
    asked = request.POST.get("tab") or request.GET.get("tab") or ""
    tab = posted or SECTION_ALIASES.get(asked, asked)
    if tab not in sections:
        tab = "account"

    post = request.POST if request.method == "POST" else None

    def bound_for(*keys):
        """The POST data for the form of a section: only when that section (or an older, unnamed form) was posted."""
        return post if post is not None and posted in keys else None

    account_form = MyAccountForm(bound_for("account", ""), instance=request.user)
    display_form = MyDisplayForm(bound_for("display", ""), instance=request.user)
    diary_form = (
        DiarySettingsForm(bound_for("diary", ""), user=request.user, profile=profile) if profile else None
    )
    fees_form = None
    if fees_profile:
        from fees.models import FeesSettings
        from fees.personal_form import FeesPersonalForm

        fees_form = FeesPersonalForm(
            bound_for("fees"), prefix="fees", profile=fees_profile, user=request.user,
            fees_settings=FeesSettings.objects.filter(profile=fees_profile).first(),
        )
    if post is not None:
        # Every form of the section is checked so that every error is shown at once; nothing is saved unless all are fine.
        checked = [f for f in (account_form, display_form, diary_form, fees_form) if f is not None and f.is_bound]
        valid = True
        for one in checked:
            valid = one.is_valid() and valid
        if valid:
            for one in checked:
                one.save()
            messages.success(request, "Settings saved.")
            return redirect(reverse("my_settings") + ("" if tab == "account" else f"?tab={tab}"))
    return render(
        request,
        "accounts/my_settings.html",
        {
            "account_form": account_form,
            "display_form": display_form,
            "diary_form": diary_form,
            "fees_form": fees_form,
            "diary_profile": profile,
            "sections": sections,
            "tab": tab,
            "preview": preview_rows(diary_form.effective()) if diary_form is not None else [],
        },
    )


@login_required
@require_POST
def profile_switch(request):
    """Use another of my profiles (round 18, D95): from the header menu or the Home page. Opens its Subjects page."""
    from diary.params import safe_int

    profile = Profile.objects.filter(
        pk=safe_int(request.POST.get("profile", "")), program__in=programs.enabled_program_keys()
    ).first()
    if profile is None or not use_profile(request.user, profile):
        messages.error(request, "You do not have that profile.")
        return redirect(reverse("home") + "?home=1")
    program = programs.get_program(profile.program)
    return redirect(program.landing_url_name if program is not None else "home")


class MyPasswordChangeView(auth_views.PasswordChangeView):
    """Settings > Account > Change my password (D93): the current password, then the new one twice (the usual rules)."""

    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("my_settings")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Your password is changed.")
        return response


@login_required
@require_GET
def format_preview(request):
    """The sample for the formats in the query string (the settings page fetches this as you choose)."""
    from diary.forms import FORMAT_FIELDS, DiarySettingsForm, allowed_formats, preview_rows

    chosen = {}
    profile = get_profile_for(request.user)
    if profile:
        chosen = DiarySettingsForm(user=request.user, profile=profile).current()
    chosen = {name: chosen.get(name) for name in FORMAT_FIELDS}
    allowed = allowed_formats()
    for name in FORMAT_FIELDS:
        value = request.GET.get(name, "")
        if value in allowed[name]:  # junk or not-allowed values leave the saved (or standard) format in place
            chosen[name] = value
    return render(request, "accounts/_format_preview.html", {"preview": preview_rows(chosen)})


def _with_profiles(users):
    """Give each user ``profiles_text``: their live profiles with roles, for example "Main (Editor), Smith (Reader)"."""
    by_user = {}
    for m in ProfileMembership.objects.filter(
        program__in=programs.program_keys(), suspended=False, profile__deleted_at__isnull=True
    ).select_related("profile").order_by("profile__name", "pk"):
        by_user.setdefault(m.user_id, []).append(f"{m.profile.name} ({m.get_role_display()})")
    for u in users:
        u.profiles_text = ", ".join(by_user.get(u.pk, []))
    return users


@admin_required
def user_list(request):
    users = _with_profiles(list(user_trash.live_users().order_by("username")))
    deleted = _with_profiles(list(user_trash.deleted_users().order_by("-deleted_at", "username")))
    for u in deleted:
        u.days_left = user_trash.days_left(u)
    return render(request, "accounts/user_list.html", {
        "users": users,
        "deleted_users": deleted,
        "user_retention_days": user_trash.retention_days(),
    })


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
    target = get_object_or_404(user_trash.live_users(), pk=pk)  # a deleted user is restored first, then edited
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
    """Soft delete (round 18, D94): the user can be restored from Deleted users for USER_RETENTION_DAYS."""
    target = get_object_or_404(user_trash.live_users(), pk=pk)
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
        user_trash.delete_user(target, request.user)
        messages.success(
            request,
            f"User {target.username} deleted. You can restore them from Deleted users for "
            f"{user_trash.retention_days()} days.",
        )
        return redirect("user_list")
    return render(request, "accounts/user_confirm_delete.html", {
        "target": target, "problem": problem, "user_retention_days": user_trash.retention_days(),
    })


@admin_required
@require_POST
def user_restore(request, pk):
    """Bring a deleted user back as they were: profiles, roles, settings and whether they could sign in."""
    target = get_object_or_404(user_trash.deleted_users(), pk=pk)
    user_trash.restore_user(target)
    messages.success(request, f"User {target.username} restored.")
    return redirect("user_list")


@admin_required
@require_http_methods(["GET", "POST"])
def suite_settings(request):
    """Rename the Home page and the programs (Admin only; the names are shared by all users)."""
    form = SuiteNamesForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Names saved.")
        return redirect("settings")
    return render(request, "accounts/settings.html", {"form": form})


def _live_profiles(program=None):
    """Live profiles of every enabled program, or only of ``program`` (the diary-only actions below)."""
    keys = programs.enabled_program_keys() if program is None else [program]
    return Profile.objects.filter(program__in=keys, deleted_at__isnull=True)


@admin_required
def profile_list(request):
    profiles = list(_live_profiles().order_by("name"))
    names = suite.get_names()
    for p in profiles:
        p.member_count, p.subject_count = profile_usage(p)
        p.program_name = names.get(p.program, p.program)
    deleted = list(
        Profile.objects.filter(program__in=programs.program_keys(), deleted_at__isnull=False)
        .select_related("deleted_by")
        .order_by("-deleted_at")
    )
    for p in deleted:
        p.days_left = days_left(p)
        p.member_count, p.subject_count = profile_usage(p)
        p.program_name = names.get(p.program, p.program)
    return render(
        request,
        "accounts/profile_list.html",
        {
            "profiles": profiles,
            "show_program": len(programs.enabled_program_keys()) > 1 or any(p.program != suite.KEY_DIARY for p in profiles + deleted),
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
    """Bring back a deleted profile with its members (a user may have several profiles, so nobody is in the way).

    If a live profile has the same name, the Admin is asked for a new name first.
    """
    target = get_object_or_404(
        Profile, pk=pk, program__in=programs.program_keys(), deleted_at__isnull=False
    )
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
    target = get_object_or_404(_live_profiles(suite.KEY_DIARY), pk=pk)
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


@admin_required
@require_http_methods(["GET", "POST"])
def offline_link_admin(request, pk):
    """Round 21 (D100): make, switch on or off, renew and refresh the secret Offline link of one profile (Admin only)."""
    from diary.offline_link import make_copy  # lazy: diary imports accounts

    target = get_object_or_404(_live_profiles(suite.KEY_DIARY), pk=pk)
    link = OfflineLink.objects.filter(profile=target).select_related("made_by").defer("copy_data").first()
    if request.method == "POST":
        action = request.POST.get("action", "")
        try:
            _offline_link_action(request, target, link, action, make_copy)
        except Exception:
            logger.exception("Offline link action %s failed for profile %s", action, target.pk)
            if action in ("make", "copy", "on", "renew"):
                OfflineLink.objects.filter(profile=target).update(
                    copy_error="The last attempt to save a copy failed. The earlier copy, if any, is kept."
                )
            messages.error(
                request,
                "That did not work and nothing was lost. The earlier saved copy, if any, is kept. Please try again.",
            )
        return redirect("offline_link_admin", pk=target.pk)
    context = {"target": target, "link": link}
    if link is not None:
        context["public_url"] = request.build_absolute_uri(reverse("offline_public", args=[link.token]))
        context["maker"] = link.made_by.username if link.made_by_id else ""
    return render(request, "accounts/offline_link.html", context)


def _offline_link_action(request, target, link, action, make_copy):
    user = request.user
    if action == "make" and link is None:
        link = OfflineLink(profile=target, made_by=user)
        link.new_token()
        link.save()
        make_copy(link, user)
        messages.success(request, "The link is made and the first copy is saved.")
    elif link is None:
        messages.error(request, "There is no link yet. Press Make link first.")
        return
    elif action == "copy":
        make_copy(link, user)
        messages.success(request, "A new copy is saved.")
    elif action == "off":
        OfflineLink.objects.filter(pk=link.pk).update(enabled=False)
        messages.success(request, "The link is switched off. Nobody can download with it now.")
    elif action == "on":
        OfflineLink.objects.filter(pk=link.pk).update(enabled=True)
        if not link.has_copy:
            make_copy(link, user)
        messages.success(request, "The link is switched on again (the same address as before).")
    elif action == "renew":
        link.new_token()
        link.enabled = True
        link.made_by = user
        link.save(update_fields=["token", "token_hash", "enabled", "made_by"])
        if not link.has_copy:
            make_copy(link, user)
        messages.success(request, "A new link is made. The old link has stopped working.")
    else:
        messages.error(request, "Nothing was done.")
        return
    logger.info("Offline link action %s: profile %s, user %s", action, target.pk, user.pk)
