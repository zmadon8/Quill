"""Reading versions that earlier releases saved in the edit history.

Backups of earlier releases are no longer converted (only the newest backup, made by the current release, has to restore), but
the edit history of a record can still hold a version saved long ago (the newest version of every record is always kept). Two
small rules let such a version be restored or shown:

* ``merge``: a version saved before "For review" was merged into the Flags (D88) carries ``needs_review`` and ``review_note``;
  restoring it folds that mark into the flag, so nothing of it is lost (``services.core.apply_snapshot``,
  ``services.history.restore_version``), and the Word import uses the same rule for its marks.
* ``old_snapshot_citation``: a version saved before citations became Cases (10d) holds its one citation in the Item; restoring it
  writes that text into Case (a).

No models and nothing from the service layer are imported.
"""

NONE, OTHER = "none", "other"
REVIEW = "For review"
SEP = " \u00b7 "


def _tidy(text):
    return " ".join((text or "").split())


def merge(flag, flag_text, needs_review, review_note):
    """(flag, flag text) once a For review mark (with ``review_note``) is folded in; unchanged when not marked.

    * no flag: the flag becomes Other, its text the note (or "For review" when there is none);
    * a flag already set: it is kept and " \u00b7 For review: <note>" (or " \u00b7 For review") is added after its text.

    Spaces and line breaks in the note become single spaces (a flag text is one line).
    """
    flag = flag or NONE
    if not needs_review:
        return flag, flag_text or ""
    note = _tidy(review_note)
    if flag == NONE:
        return OTHER, note or REVIEW
    mark = f"{REVIEW}: {note}" if note else REVIEW
    text = _tidy(flag_text)
    return flag, f"{text}{SEP}{mark}" if text else mark


def old_snapshot_citation(snapshot):
    """The old ``citation`` of a version-history snapshot that must become Case (a), else None.

    Before the merge (10d) and for Nested Items the citation lived in the Item; an empty value means
    "nothing to map", never "clear Case (a)".
    """
    citation = snapshot.get("citation") or ""
    return citation if citation != "" else None
