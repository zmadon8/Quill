from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied


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


#: Anonymous users go to login; signed-in users who fail the check get 403.
admin_required = _role_required(lambda user: user.is_admin)
editor_required = _role_required(lambda user: user.is_editor)  # Editor or Admin
reader_required = _role_required(lambda user: True)  # any signed-in user (same as login_required)
