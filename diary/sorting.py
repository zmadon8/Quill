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

Owner answers (round 7), applied to the sort key only; the displayed name never changes:

* a leading "The", "Re:" or "Re " is ignored ("In re X" is not touched: only the very start counts);
* a leading list marker such as "(a):" is ignored, so "(a): Freedom of Expression" sorts under F. The
  marker is deliberately narrow: a bracketed letter, number or Roman numeral, then an optional ":", "."
  or ")", then spaces. Bare "a." or "1." prefixes are NOT markers (a number is a number: "1. Intro" is 1);
* the whole words "Sections", "Orders" and "Rules" count as "Section", "Order" and "Rule", so
  "Sections 9 & 17" sorts between "Section 8" and "Section 10", by its first number.

Not handled on purpose: Roman numerals outside a bracketed marker are letters.
"""
import re
import unicodedata

_PARTS = re.compile(r"([0-9]+)")
_SPACES = re.compile(r"\s+")
#: "(a)", "[2]", "(iv):", "(b)." ... after case folding. A letter, 1-3 digits or a Roman numeral in brackets,
#: then an optional ":" "." ")" and spaces. Only stripped when a name remains after it.
_MARKER = re.compile(r"^[(\[]\s*(?:[a-z]|[0-9]{1,3}|[ivx]{2,5})\s*[)\]]"
                     r"[:.)]?\s+|^[(\[]\s*(?:[a-z]|[0-9]{1,3})\s*[)\]][:.)]\s*")
#: A leading "the ", "re:" or "re " (whole words, only at the very start).
_LEAD_WORD = re.compile(r"^(?:the\s+|re\s*:\s*|re\s+)")
_PLURALS = re.compile(r"\b(section|order|rule)s\b")

#: Token kinds. A number sorts before text where both could stand.
_NUMBER, _TEXT = 0, 1


def normalise(name):
    """The name as compared: accents dropped, case folded, spaces collapsed, leading punctuation removed."""
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _SPACES.sub(" ", text.casefold()).strip()
    text = _strip_leading(text)
    while True:
        rest = _MARKER.sub("", text, count=1)
        rest = _strip_leading(_LEAD_WORD.sub("", rest, count=1))
        if not rest or rest == text:
            break
        text = rest
    return _PLURALS.sub(r"\1", text)


def _strip_leading(text):
    """Drop what is at the START and is not a letter or a digit; brackets stay so a marker can be seen."""
    start = 0
    while start < len(text) and not text[start].isalnum() and text[start] not in "([":
        start += 1
    text = text[start:]
    # A bracket that is not a list marker is punctuation too: "(Zed)" -> "zed)".
    if text and text[0] in "([" and not _MARKER.match(text):
        text = text[1:]
        return _strip_leading(text)
    return text


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
