"""The Undo list of the current session (docs/DESIGN.md decision M3-21).

Each action an Editor makes is one Undo group (a shared ``group`` on its history rows). The session keeps
the group ids, newest last, with the profile they belong to, so Undo reaches only this session's own
actions in the signed-in profile. The service layer re-checks that the actions are the user's own.
"""
import uuid

from .models import VersionHistory
from .services import group_summary

SESSION_KEY = "diary_undo_groups"
KEEP = 30

KIND_WORDS = {
    "create": "Added", "edit": "Edited", "delete": "Deleted", "restore": "Restored", "move": "Moved",
    "reorder": "Reordered", "convert": "Changed the type of",
}
RECORD_WORDS = {
    "subject": "Subject", "topic": "Topic", "subtopic": "Sub-topic", "section": "Section", "item": "Item",
    "case": "Case", "note": "Note", "notelink": "Note link",
}


def remember(request, group):
    """Add ``group`` to this session's Undo list, if the action wrote anything (a rolled back one wrote nothing)."""
    if not VersionHistory.objects.filter(profile=request.profile, group=group).exists():
        return
    entries = [e for e in request.session.get(SESSION_KEY, []) if e["group"] != str(group)]
    entries.append({"group": str(group), "profile": request.profile.pk})
    request.session[SESSION_KEY] = entries[-KEEP:]


def forget(request, group):
    request.session[SESSION_KEY] = [e for e in request.session.get(SESSION_KEY, []) if e["group"] != str(group)]


def groups(request):
    """Group ids (strings) of this profile in this session, newest first."""
    return [e["group"] for e in reversed(request.session.get(SESSION_KEY, [])) if e["profile"] == request.profile.pk]


def parse(value):
    """A group id from the form, or None when it is not one."""
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def describe(profile, group):
    """A short sentence for the Undo button, such as "Deleted 3 records"."""
    summary = group_summary(profile, group)
    kind = summary["kinds"][0] if summary["kinds"] else "edit"
    records = summary["records"]
    if "create" in summary["kinds"]:
        # Adding in the middle first shifts the later siblings; the action is still an add of what was created.
        kind = "create"
        made = VersionHistory.objects.filter(profile=profile, group=group, change_kind="create")
        created = set(made.values_list("record_type", "record_id"))
        records = [r for r in records if r in created]
    words = KIND_WORDS.get(kind, "Changed")
    if len(records) == 1:
        return f"{words} 1 {RECORD_WORDS.get(records[0][0], 'record')}"
    return f"{words} {len(records)} records"


def latest(request):
    """{'group', 'text'} for the newest action of this session in this profile, or None."""
    found = groups(request)
    if not found:
        return None
    return {"group": found[0], "text": describe(request.profile, found[0])}
