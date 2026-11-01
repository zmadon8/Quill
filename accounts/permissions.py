from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from .models import ROLE_EDITOR
from .profiles import get_membership_for


def _role_required(check):
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not check(request.user):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


def program_role(user, program):
    """The user's role ("editor" or "reader") in ``program``, or None if they have no profile there.

    Admin is not a role here: an Admin works inside a program with the role of their own membership.
    """
    membership = get_membership_for(user, program)
    return membership.role if membership else None


def program_editor_required(program):
    """Decorator: signed-in users whose role in ``program`` is Editor; anyone else gets 403."""
    return _role_required(lambda user: program_role(user, program) == ROLE_EDITOR)


def program_reader_required(program):
    """Decorator: signed-in users with any role (Editor or Reader) in ``program``; others get 403."""
    return _role_required(lambda user: program_role(user, program) is not None)


#: Anonymous users go to login; signed-in users who fail the check get 403.
admin_required = _role_required(lambda user: user.is_admin)  # suite-wide Admin flag
reader_required = _role_required(lambda user: True)  # any signed-in user (same as login_required)
