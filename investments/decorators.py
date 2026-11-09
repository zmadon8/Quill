"""Role decorators for the Investments views (plan section 20), the same arrangement as ``fees.decorators``."""
from functools import wraps

from accounts.permissions import admin_required, program_editor_required, program_reader_required
from accounts.suite import KEY_INVESTMENTS

inv_reader = program_reader_required(KEY_INVESTMENTS)
inv_editor = program_editor_required(KEY_INVESTMENTS)
#: Suite Admin only (price sources, catalogue, deleting an investment that has records).
inv_admin = admin_required

_READ_METHODS = ("GET", "HEAD")


def inv_read_write(view):
    """GET and HEAD for any role in the program; every other method for an Editor only."""
    reader_view = inv_reader(view)
    editor_view = inv_editor(view)

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.method in _READ_METHODS:
            return reader_view(request, *args, **kwargs)
        return editor_view(request, *args, **kwargs)

    return wrapper
