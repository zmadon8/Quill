"""Service layer for editing the diary (Milestone 3a). No views, no templates.

Every function takes ``profile`` and ``user`` first, works only inside that profile, runs in one
transaction, bumps record versions and writes VersionHistory. See docs/DESIGN.md sections 5.4 to
5.7, 6 and 9.
"""
from .core import ActionResult, Ctx, action_group, snapshot
from .errors import (
    Conflict,
    ConfirmationRequired,
    NameClash,
    NotFound,
    ParentInTrash,
    PermanentDeleteRefused,
    Refused,
    ServiceError,
    UndoWarning,
    ValidationFailed,
)
from .history import history_for, restore_version
from .moves import move, move_to_new_heading, new_heading_options, preview_delete, preview_move, preview_move_to_new_heading, shift
from .links import add_link, purge_link, retarget_link, shift_link
from .records import create, edit, set_landing
from .trash import delete, permanent_delete, restore
from .undo import group_summary, undo_group

__all__ = [
    "ActionResult", "Conflict", "ConfirmationRequired", "Ctx", "NameClash", "NotFound", "ParentInTrash",
    "PermanentDeleteRefused", "Refused", "ServiceError", "UndoWarning", "ValidationFailed",
    "action_group", "add_link", "create", "delete", "edit", "group_summary", "history_for",
    "move", "move_to_new_heading", "new_heading_options", "permanent_delete", "preview_delete", "preview_move",
    "preview_move_to_new_heading",
    "purge_link", "restore", "restore_version", "retarget_link", "set_landing", "shift", "shift_link", "snapshot", "undo_group",
]
