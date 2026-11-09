"""The error type the Investments services raise (the same arrangement as ``fees.errors``)."""


class InvestmentsError(Exception):
    """A refused action. ``code`` is a stable machine word, ``message`` is plain language for the person, ``status`` the HTTP
    status a view should use (400 bad input, 403 not allowed, 404 not found, 409 clash or conflict) and ``details`` any
    extra data (for example the conflicting sales for a refused edit)."""

    def __init__(self, code, message, status=400, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details or {}


def not_found(what="record"):
    return InvestmentsError("NOT_FOUND", f"That {what} was not found.", 404)


def forbidden(message="You do not have permission to do that."):
    return InvestmentsError("FORBIDDEN", message, 403)
