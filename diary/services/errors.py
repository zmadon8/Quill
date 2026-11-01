"""Errors raised by the service layer. Views turn these into messages or pages."""


class ServiceError(Exception):
    """Base class. ``message`` is plain language that can be shown to the user."""

    def __init__(self, message="", **details):
        super().__init__(message)
        self.message = message
        self.details = details


class NotFound(ServiceError):
    """The record does not exist in this profile (another profile's id is treated the same way)."""


class Refused(ServiceError):
    """A rule forbids the action. ``reasons`` lists every reason found."""

    def __init__(self, message="", reasons=None, **details):
        super().__init__(message, **details)
        self.reasons = list(reasons) if reasons else [message]


class ValidationFailed(Refused):
    """The values given are not acceptable (for example a blank or duplicate name)."""


class Conflict(ServiceError):
    """Stale save: the record changed since the editor opened it (section 9.2).

    Carries both versions: ``mine`` (what the editor tried to save) and ``theirs`` (the stored
    snapshot), plus the version numbers.
    """

    def __init__(self, record_type, record_id, expected_version, current_version, theirs, mine=None):
        super().__init__(
            "This record was changed by someone else (or in another tab) after you opened it.",
            record_type=record_type,
            record_id=record_id,
        )
        self.record_type = record_type
        self.record_id = record_id
        self.expected_version = expected_version
        self.current_version = current_version
        self.theirs = theirs
        self.mine = mine or {}


class NameClash(ServiceError):
    """A restored record's name is taken; the caller must supply a new name (rename-on-restore)."""

    def __init__(self, record_type, record_id, name, suggestion):
        super().__init__(f"The name {name!r} is already used. Choose a new name.")
        self.record_type = record_type
        self.record_id = record_id
        self.name = name
        self.suggestion = suggestion


class ParentInTrash(ServiceError):
    """The record's parent (or an ancestor) is in Trash. ``chain`` is [(type, id, label)], top first."""

    def __init__(self, chain):
        super().__init__("The place this was in is in the Trash. Restore the parent chain too?")
        self.chain = chain


class PermanentDeleteRefused(Refused):
    """Incoming Note links exist. ``links`` is a list of dicts describing each one."""

    def __init__(self, links):
        super().__init__(
            "Other Notes link to this. Decide what to do with each link first; nothing was deleted.",
            links=links,
        )
        self.links = links


class ConfirmationRequired(ServiceError):
    """The action has warnings that must be accepted first (for example comments being flattened)."""

    def __init__(self, warnings):
        super().__init__("Please confirm: " + " ".join(warnings))
        self.warnings = list(warnings)


class UndoWarning(ServiceError):
    """Records changed after the action being undone. ``changed`` lists them; repeat with force=True."""

    def __init__(self, changed):
        super().__init__("Some records have changed since this action. Undo anyway?")
        self.changed = changed
