"""The History tab: the last 100 actions in the open profile, by any user, with who did them.

Any Fee Register role may read it (Reader or Editor), like every other list. It has no Restore: the log is
a short account of what was done, and a deleted memo or payment is brought back from a backup.
"""
from django.urls import reverse
from django.views.decorators.http import require_safe

from fees import scope
from fees.decorators import fees_reader
from fees.models import Firm, Matter, Memo
from fees.pages import render_page
from fees.services import history

#: object type -> (model, url name) for the types that have a page of their own.
_LINKS = {"memo": (Memo, "fees_memo_detail"), "firm": (Firm, "fees_firm_detail"), "matter": (Matter, "fees_matter_detail")}


def _rows(profile):
    """The latest lines with a display name for the user and a link to the record while it still exists."""
    rows = history.recent(profile)
    alive = {}
    for kind, (model, _name) in _LINKS.items():
        ids = {r.object_id for r in rows if r.object_type == kind and r.object_id and r.action != "delete"}
        alive[kind] = set(model.objects.filter(profile=profile, pk__in=ids).values_list("pk", flat=True)) if ids else set()
    for row in rows:
        row.who = (row.user.get_full_name() or row.user.get_username()) if row.user_id else "System"
        row.what = history.ACTION_LABELS.get(row.action, row.action.capitalize())
        row.kind = history.OBJECT_LABELS.get(row.object_type, row.object_type)
        link = _LINKS.get(row.object_type)
        row.url = reverse(link[1], args=[row.object_id]) if link and row.object_id in alive[row.object_type] else None
    return rows


@require_safe
@fees_reader
def history_page(request):
    profile, _settings = scope.context(request)
    return render_page(request, "fees/history.html", {"rows": _rows(profile), "limit": history.LIMIT})
