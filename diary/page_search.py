"""The Case Law Diary's own pages, for search (owner round 2026-11: "In search for each of the sub-programs, include search for Pages").

A fixed list, matched on the title or the description, case-insensitive. Pages the person cannot open are left out."""
import re

from django.urls import reverse

#: (title, what it is, URL name, who: "all" / "editor" / "admin").
PAGES = (
    ("Subjects", "The Index of Subjects", "diary_home", "all"),
    ("Other Subjects", "Subjects kept apart from the main list", "other_subjects", "all"),
    ("Search", "Search the diary", "search", "all"),
    ("Flags", "Items and Sections that are flagged (for review, overruled, doubted)", "flags", "all"),
    ("Hyperlinks", "Citations with a web link, and those without", "flag_links", "all"),
    ("History", "Your edits, and restoring an earlier version", "diary_history", "all"),
    ("Trash", "Deleted Subjects, Topics, Items and Notes", "trash", "editor"),
    ("Export", "The diary as a Word file or an Offline copy", "export", "all"),
    ("Settings", "How the diary is shown and exported", "profile_settings", "all"),
    ("Import", "Load a diary from a Word file", "import_word", "admin"),
    ("Help", "How the diary works, and the shortcuts", "help", "all"),
)


def _page_matches(query, title, what):
    """A page matches when a word of its title starts with ``query`` (or the title holds it whole), or, from three letters on, a word of
    its description starts with it. Word starts keep a two-letter query from finding half the pages."""
    q = " ".join(re.findall(r"\w+", query.casefold())) or query.casefold()
    words = re.findall(r"\w+", title.casefold())
    if q in " ".join(words) and (" " in q or any(w.startswith(q) for w in words)):
        return True
    return len(q) >= 3 and any(w.startswith(q) for w in re.findall(r"\w+", what.casefold()))


def page_results(query, can_edit=True, is_admin=False):
    """``[{"title", "what", "url"}]`` for the pages whose title or description holds ``query``."""
    q = (query or "").strip()
    if len(q) < 2:
        return []
    out = []
    for title, what, url_name, who in PAGES:
        if (who == "editor" and not can_edit) or (who == "admin" and not is_admin):
            continue
        if _page_matches(q, title, what):
            out.append({"title": title, "what": what, "url": reverse(url_name)})
    return out
