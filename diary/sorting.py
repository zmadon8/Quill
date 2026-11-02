"""Alphabetical order of Subjects, Topics and Sub-topics (docs/DESIGN.md decision log, "Alphabetical headings").

Pure Python, no Django. The rule, in the owner's words: numbers sort as numbers ("S. 9" before "S. 11"),
capitals are ignored, and leading quotes and brackets are ignored.

The key of a name is built in three steps:

1. Normalise: Unicode compatibility form (NFKD), accents dropped, ``casefold`` (so capitals do not
   matter), runs of white space become one space, and anything at the START that is not a letter or
   a digit (quotes, brackets, dashes, spaces) is removed.
2. Split into runs of digits and runs of anything else. A digit run is compared as a number, so
   "Section 4" < "Section 45" and "S. 9" < "S. 11". A number sorts before text at the same place,
   and a name that is a prefix of another sorts first ("Section 2" < "Section 2(1)" < "Section 2A").
3. Ties (same name apart from capitals or punctuation at the start) are broken by the full original
   name, then by id, so the order is always the same.

Not handled on purpose: a leading "The" or "Re:" is not ignored; "Sections" sorts after "Section"
(they are different words); Roman numerals are letters.
"""
import re
import unicodedata

_PARTS = re.compile(r"([0-9]+)")
_SPACES = re.compile(r"\s+")

#: Token kinds. A number sorts before text where both could stand.
_NUMBER, _TEXT = 0, 1


def normalise(name):
    """The name as compared: accents dropped, case folded, spaces collapsed, leading punctuation removed."""
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _SPACES.sub(" ", text.casefold()).strip()
    start = 0
    while start < len(text) and not text[start].isalnum():
        start += 1
    return text[start:]


def natural_tokens(name):
    """``name`` normalised and cut into ('number', int) and ('text', str) tokens, as comparable tuples."""
    tokens = []
    for part in _PARTS.split(normalise(name)):
        if not part:
            continue
        if part.isdigit() and part.isascii():
            tokens.append((_NUMBER, int(part), ""))
        else:
            tokens.append((_TEXT, 0, part))
    return tuple(tokens)


def sort_key(name, pk=0):
    """The full sort key of one heading: natural tokens, then the original name, then the id."""
    return (natural_tokens(name), name or "", pk or 0)


def heading_key(obj):
    """Sort key of a Subject, Topic or Sub-topic (anything with ``name`` and ``pk``)."""
    return sort_key(obj.name, obj.pk)


def sort_headings(objs):
    """The Subjects, Topics or Sub-topics in ``objs`` in alphabetical order (a new list)."""
    return sorted(objs, key=heading_key)
