"""Text matching for Global Search (docs/DESIGN.md section 10). Pure Python, no Django.

The rules, in the owner's words: case does not matter, punctuation does not matter, partial words match,
a quoted phrase must match as whole words in order.

* **Normalising**: every character that is not a letter or a digit and is not "&" is a separator; a run of
  separators becomes one space; the ends are stripped; letters are lower-cased. So "(2018) 9 SCC 49"
  becomes "2018 9 scc 49", and curly and straight quotes vanish alike ("Smith's" and "Smith\u2019s" both
  become "smith s"). "&" is kept as a letter, so "L&T" stays "l&t" and "&" never matches "and".
* **Index map**: ``normalise_with_map`` also returns, for every normalised character, the index of the
  original character it came from (a collapsed space maps to the start of its separator run). It is how a
  match in the normalised text is shown highlighted in the original.
* **Terms**: unquoted words are substring terms (partial words). A double-quoted phrase (straight or curly
  double quotes) is one phrase term that must match whole words in sequence. An unterminated quote makes a
  phrase to the end of the query.
* **A record matches** when every term matches in at least one of its fields; a phrase never spans fields.
"""
from typing import NamedTuple

import re

#: A run of "word" characters of the lower-cased text: letters, digits, "&" and combining marks (so a
#: letter keeps its accent mark when lower-casing expands it, e.g. "\u0130" -> "i" + U+0307).
_WORD = re.compile(r"(?:[^\W_]|[&\u0300-\u036f])+")

#: The double quotes that open or close a phrase.
QUOTES = '"\u201c\u201d\u201e\u201f\u00ab\u00bb'


class Term(NamedTuple):
    text: str  # already normalised
    phrase: bool


def _lowered(text):
    """(lower-cased text, origin) where ``origin[i]`` is the original index of lowered char ``i``.

    ``origin`` is None when lower-casing kept the length (nearly always): then indexes are the same.
    """
    low = text.lower()
    if len(low) == len(text):
        return low, None
    out, origin = [], []
    for i, ch in enumerate(text):
        part = ch.lower()
        out.append(part)
        origin.extend([i] * len(part))
    return "".join(out), origin


def normalise(text):
    """The text as compared: lower-case, separators collapsed to one space, ends stripped."""
    if not text:
        return ""
    low, _ = _lowered(text)
    return " ".join(m.group() for m in _WORD.finditer(low))


def normalise_with_map(text):
    """(normalised text, idx_map) with ``idx_map[i]`` the index into ``text`` of normalised char ``i``."""
    if not text:
        return "", []
    low, origin = _lowered(text)
    pieces, idx_map = [], []
    previous_end = None
    for m in _WORD.finditer(low):
        start, end = m.span()
        if previous_end is not None:
            pieces.append(" ")
            idx_map.append(previous_end if origin is None else origin[previous_end])
        pieces.append(m.group())
        idx_map.extend(range(start, end) if origin is None else origin[start:end])
        previous_end = end
    return "".join(pieces), idx_map


def parse_query(query):
    """The list of Terms of a query string (empty when it holds no letters or digits)."""
    terms = []
    buffer = []
    in_quote = False

    def flush(phrase):
        norm = normalise("".join(buffer))
        buffer.clear()
        if not norm:
            return
        if phrase:
            terms.append(Term(norm, True))
        else:
            terms.extend(Term(word, False) for word in norm.split(" "))

    for ch in query or "":
        if ch in QUOTES:
            flush(in_quote)
            in_quote = not in_quote
        else:
            buffer.append(ch)
    flush(in_quote)
    return terms


def term_spans(norm, term):
    """(start, end) of every match of ``term`` in the normalised text ``norm``.

    A word term matches anywhere (partial words); a phrase only where it starts and ends at a word edge.
    """
    needle = term.text
    if not needle or not norm:
        return []
    spans = []
    start = norm.find(needle)
    while start != -1:
        end = start + len(needle)
        if not term.phrase or (
            (start == 0 or norm[start - 1] == " ") and (end == len(norm) or norm[end] == " ")
        ):
            spans.append((start, end))
        start = norm.find(needle, end)
    return spans


def original_spans(idx_map, spans):
    """Map spans of the normalised text back to (start, end) of the original text, merged and sorted."""
    mapped = sorted((idx_map[s], idx_map[e - 1] + 1) for s, e in spans if e > s)
    merged = []
    for s, e in mapped:
        if merged and s <= merged[-1][1]:
            if e > merged[-1][1]:
                merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return merged


def match_fields(fields, terms):
    """Match ``terms`` against ``fields`` (a list of (key, text)).

    Returns None when the record does not match (some term found in no field). Otherwise a dict
    ``{key: [(start, end), ...]}`` of the highlight spans in the ORIGINAL text of every field that has a hit
    (empty when ``terms`` is empty: everything matches, nothing is highlighted).
    """
    if not terms:
        return {}
    norms = [(key, text, normalise(text)) for key, text in fields]
    hit_keys = set()
    for term in terms:
        found = False
        for key, _text, norm in norms:
            if term.text in norm and term_spans(norm, term):
                found = True
                hit_keys.add(key)
        if not found:
            return None
    result = {}
    for key, text, norm in norms:
        if key not in hit_keys:
            continue
        mapped_norm, idx_map = normalise_with_map(text)
        spans = []
        for term in terms:
            spans.extend(term_spans(mapped_norm, term))
        if spans:
            result[key] = original_spans(idx_map, spans)
    return result


def contains_whole_query(fields, terms):
    """True when the terms, joined by one space, appear together in one field (used to rank results)."""
    joined = " ".join(t.text for t in terms)
    return any(joined in normalise(text) for _key, text in fields)


def snippet(original, spans, width=90):
    """A short excerpt of ``original`` around the first span, as a list of (text, highlighted) segments.

    About ``width`` characters each side, cut at word boundaries, with an ellipsis where text was cut.
    Without spans the excerpt is the beginning of the text. The caller escapes the text.
    """
    length = len(original)
    if spans:
        first_start, first_end = spans[0]
        start = max(0, first_start - width)
        end = min(length, first_end + width)
    else:
        first_start = first_end = 0
        start, end = 0, min(length, 2 * width)
    # Move the cut points to word boundaries, never past the first span.
    if start > 0:
        while start < first_start and not original[start - 1].isspace():
            start += 1
    if end < length:
        while end > first_end and not original[end].isspace():
            end -= 1
    if not spans and end < length and end == first_end:
        end = min(length, 2 * width)  # one very long word: cut it rather than show nothing
    text_start, text_end = start, end
    segments = []
    position = text_start
    for s, e in spans:
        if e <= text_start or s >= text_end:
            continue
        s, e = max(s, text_start), min(e, text_end)
        if s > position:
            segments.append((original[position:s], False))
        segments.append((original[s:e], True))
        position = e
    if position < text_end:
        segments.append((original[position:text_end], False))
    if not segments:
        segments = [("", False)]
    if text_start > 0:
        segments.insert(0, ("\u2026", False))
    if text_end < length:
        segments.append(("\u2026", False))
    return segments
