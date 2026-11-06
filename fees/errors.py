"""Fee Register errors (design section 13).

Services raise ``FeesError(code, message=None, details=None)``. ``code`` is one of the original
error codes (kept so the ported tests and the toast strings line up); ``message`` is the words shown
to the user and ``status`` is the HTTP status a view uses. A view decorator (added in Phase 7) turns a
``FeesError`` into a redirect with a flash message for HTML views, or ``{"ok": false, "error": code,
"details": ...}`` with ``status`` for JSON endpoints. No view depends on this yet.

The status for a code follows requirements R-ER-1 by its suffix (``*_NOT_FOUND`` is 404, ``DUPLICATE_*``
and ``MATTER_ARCHIVED`` are 409, the validation family is 422, ``EXPORT_FAILED`` is 400). The full
message catalogue (a port of ``useToastStore.ts``) lands with the services in later phases; ``MESSAGES``
starts with the handful already named in the brief and design so a caller can fall back to a default.
"""

#: Default HTTP status when a code matches none of the suffix rules below.
DEFAULT_STATUS = 400

#: Codes that do not follow a suffix rule, with their fixed status (R-ER-1).
_EXACT_STATUS = {
    "MATTER_ARCHIVED": 409,
    "GROUP_IN_USE": 409,
    "TOO_MANY_PARTNERS": 422,
    "NO_TEMPLATE": 422,
    "RESTORE_FAILED": 422,
    "IMPORT_FAILED": 422,
    "EXPORT_FAILED": 400,
    "CLEAR_FAILED": 500,
}


def status_for(code):
    """The HTTP status for an error ``code`` (R-ER-1), by exact match first, then by suffix."""
    if code in _EXACT_STATUS:
        return _EXACT_STATUS[code]
    if code.endswith("_NOT_FOUND"):
        return 404
    if code.startswith("DUPLICATE_"):
        return 409
    if code.startswith("INVALID_"):
        return 422
    return DEFAULT_STATUS


#: A minimal catalogue of user-facing messages (the full port of ``useToastStore.ts`` arrives with the
#: services). A code not listed here uses the message passed to ``FeesError`` or a generic fallback.
MESSAGES = {
    "MATTER_ARCHIVED": "This matter is archived, so it cannot get a new memo.",
    "GROUP_IN_USE": "This group still has matters, so it cannot be removed.",
    "TOO_MANY_PARTNERS": "This firm already has the most groups allowed.",
    "NO_TEMPLATE": "No Word template has been uploaded yet.",
    "RESTORE_FAILED": "The backup file could not be read.",
    "IMPORT_FAILED": "The spreadsheet could not be imported.",
    "EXPORT_FAILED": "There is nothing to export.",
    "INVALID_TEMPLATE": "The Word template could not be used.",
    "INVALID_SIGNATURE": "The signature must be a PNG or JPEG image of at most 2 MB.",
    "SIGNATURE_NOT_FOUND": "No signature image has been uploaded yet.",
}


class FeesError(Exception):
    """A business-rule failure in the Fee Register.

    ``code`` is the stable machine code; ``message`` is the words for the user (falls back to the
    catalogue, then to the code); ``status`` is the HTTP status (R-ER-1); ``details`` is optional extra
    data for a JSON response.
    """

    def __init__(self, code, message=None, details=None, status=None):
        self.code = code
        self.message = message or MESSAGES.get(code) or code
        self.status = status if status is not None else status_for(code)
        self.details = details
        super().__init__(f"{code}: {self.message}")
