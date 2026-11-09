"""Investments views. Phase 0 serves every page as an empty shell; later phases replace rows of ``pages.PAGES``."""
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse

from . import pages, scope
from .decorators import inv_admin, inv_reader


def landing(request):
    """/investments/ opens the first page the person can see (the Dashboard unless it is hidden)."""
    from accounts.permissions import program_role
    from accounts.suite import KEY_INVESTMENTS

    if not request.user.is_authenticated:
        from django.contrib.auth.views import redirect_to_login

        return redirect_to_login(request.get_full_path())
    if program_role(request.user, KEY_INVESTMENTS) is None:
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied
    return redirect(reverse("investments_dashboard"))


def _shell(request, slug):
    page = pages.BY_SLUG.get(slug)
    if page is None:
        raise Http404
    profile = scope.for_profile(request)
    context = pages.render_context(request, profile, {"page": page, "page_title_text": page.title})
    return render(request, "investments/shell.html", context)


def _make_view(slug):
    page = pages.BY_SLUG[slug]
    base = inv_admin(inv_reader(lambda request: _shell(request, slug))) if page.admin else inv_reader(
        lambda request: _shell(request, slug)
    )
    base.__name__ = f"shell_{slug}"
    return base


#: slug to view; ``urls.py`` builds one URL per page from this.
SHELL_VIEWS = {page.slug: _make_view(page.slug) for page in pages.PAGES}
