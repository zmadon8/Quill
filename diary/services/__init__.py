"""Service layer for editing the diary (Milestone 3a). No views, no templates.

Every function takes ``profile`` and ``user`` first, works only inside that profile, runs in one
transaction, bumps record versions and writes VersionHistory. See docs/DESIGN.md sections 5.4 to
5.7, 6 and 9.
"""
from .conversions import build_plan, convert_item, join_cases, preview_conversion
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
from .moves import move, preview_delete, preview_move, shift
from .records import add_link, create, edit, set_landing
from .trash import delete, permanent_delete, restore
from .undo import group_summary, undo_group

__all__ = [
    "ActionResult", "Conflict", "ConfirmationRequired", "Ctx", "NameClash", "NotFound", "ParentInTrash",
    "PermanentDeleteRefused", "Refused", "ServiceError", "UndoWarning", "ValidationFailed",
    "action_group", "add_link", "build_plan", "convert_item", "create", "delete", "edit", "group_summary", "history_for",
    "join_cases", "move", "permanent_delete", "preview_conversion", "preview_delete", "preview_move",
    "restore", "restore_version", "set_landing", "shift", "snapshot", "undo_group",
]
