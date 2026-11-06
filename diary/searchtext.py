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
* **Operators** (``parse_search``): AND (the default between words, or written ``AND``), ``OR``, ``NOT`` or a
  leading ``-``, "quoted phrases", ``( )`` grouping, a trailing ``*`` (the word must START with it),
  ``subject:Name`` and ``flag:kind`` (filters on the whole query, see ``Parsed``). AND, OR and NOT must be in
  capitals (``or`` is an ordinary word). A query that cannot be read (stray bracket, ``OR`` with nothing beside
  it, an unknown ``flag:`` kind...) never errors: it is searched as plain words and ``Parsed.notice`` says so.
  Only the positive terms (not under a NOT) are highlighted.
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
    prefix: bool = False  # a word that must start a word of the text (``arbitra*``)


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

    A word term matches anywhere (partial words); a phrase only where it starts and ends at a word edge; a prefix
    term only where it starts at a word edge.
    """
    needle = term.text
    if not needle or not norm:
        return []
    spans = []
    start = norm.find(needle)
    while start != -1:
        end = start + len(needle)
        at_start = start == 0 or norm[start - 1] == " "
        at_end = end == len(norm) or norm[end] == " "
        if (at_start or not (term.phrase or term.prefix)) and (at_end or not term.phrase):
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


def _join_neighbours(norm, spans):
    """Merge spans that overlap or are separated by just one space, so "2018 9 scc 49" is one highlight."""
    joined = []
    for s, e in sorted(spans):
        if joined and (s <= joined[-1][1] or (s == joined[-1][1] + 1 and norm[joined[-1][1]] == " ")):
            joined[-1] = (joined[-1][0], max(e, joined[-1][1]))
        else:
            joined.append((s, e))
    return joined


def _evaluate(node, hits):
    kind = node[0]
    if kind == "term":
        return bool(hits(node[1]))
    if kind == "and":
        return all(_evaluate(n, hits) for n in node[1])
    if kind == "or":
        return any(_evaluate(n, hits) for n in node[1])
    return not _evaluate(node[1], hits)


def match_fields(fields, terms):
    """Match ``terms`` against ``fields`` (a list of (key, text)).

    ``terms`` is a list of Terms (all must match) or a ``Parsed`` query (AND / OR / NOT / grouping).
    Returns None when the record does not match. Otherwise a dict ``{key: [(start, end), ...]}`` of the
    highlight spans in the ORIGINAL text of every field that has a hit for a positive term (empty when there is
    nothing to highlight, e.g. a query that is only NOT or only filters).
    """
    if isinstance(terms, Parsed):
        expr, positive = terms.expr, terms.terms
    else:
        expr = ("and", tuple(("term", t) for t in terms)) if terms else None
        positive = terms
    if expr is None:
        return {}
    norms = [(key, text, normalise(text)) for key, text in fields]
    cache = {}

    def hits(term):
        if term not in cache:
            cache[term] = [key for key, _text, norm in norms if term.text in norm and term_spans(norm, term)]
        return cache[term]

    if not _evaluate(expr, hits):
        return None
    hit_keys = set()
    for term in positive:
        hit_keys.update(hits(term))
    result = {}
    for key, text, norm in norms:
        if key not in hit_keys:
            continue
        mapped_norm, idx_map = normalise_with_map(text)
        spans = []
        for term in positive:
            spans.extend(term_spans(mapped_norm, term))
        if spans:
            result[key] = original_spans(idx_map, _join_neighbours(mapped_norm, spans))
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


# ---------------------------------------------------------------------------------------------------------------
# Operators (docs/DESIGN.md section 10, round "diary-round" 1.8)
# ---------------------------------------------------------------------------------------------------------------

#: What ``flag:`` accepts, and the stored flags each stands for ("review" = the two flags that mean a ruling to
#: look at: Overruled and Doubted).
FLAG_WORDS = {
    "pending": frozenset({"pending"}),
    "review": frozenset({"overruled", "doubted"}),
    "overruled": frozenset({"overruled"}),
    "doubted": frozenset({"doubted"}),
    "other": frozenset({"other"}),
}

NOTICE = ("The operators in this search could not be read (check brackets, OR, NOT and flag:), "
          "so the words were searched plainly. See Search tips.")

_MAX_DEPTH = 20
_FIELD = re.compile(r"^(subject|flag):(.*)$", re.IGNORECASE | re.DOTALL)
_OPERATORS = ("AND", "OR", "NOT")


class Parsed(NamedTuple):
    expr: object  # None when there are no words, else a nested tuple (see ``_evaluate``)
    terms: tuple  # the positive Terms, in order (highlighted and used to rank)
    subjects: tuple  # normalised Subject-name pieces from ``subject:`` (any one may match); empty = no filter
    flags: object  # frozenset of stored flag keys from ``flag:``, or None for no filter
    notice: str  # "" or the short message shown when the query was read as plain words


class _Malformed(Exception):
    pass


def _tokens(query):
    """The tokens of a query: ("(",), (")",), ("op", "AND|OR|NOT"), ("node", expr) and ("field", name, value).

    Never fails: anything odd is kept as a word or dropped (a bare "-" or "*").
    """
    tokens = []
    i, n = 0, len(query)
    while i < n:
        ch = query[i]
        if ch.isspace():
            i += 1
        elif ch in "()":
            tokens.append((ch,))
            i += 1
        elif ch in QUOTES:
            j = i + 1
            while j < n and query[j] not in QUOTES:
                j += 1
            norm = normalise(query[i + 1:j])
            if norm:
                tokens.append(("node", ("term", Term(norm, True))))
            i = j + 1
        else:
            j = i
            while j < n and not query[j].isspace() and query[j] not in "()" and query[j] not in QUOTES:
                j += 1
            chunk = query[i:j]
            i = j
            field_match = _FIELD.match(chunk)
            if field_match and not field_match.group(2) and i < n and query[i] in QUOTES:
                k = i + 1  # subject:"Civil Procedure"
                while k < n and query[k] not in QUOTES:
                    k += 1
                tokens.append(("field", field_match.group(1).lower(), query[i + 1:k]))
                i = k + 1
                continue
            if chunk in _OPERATORS:
                tokens.append(("op", chunk))
                continue
            if chunk == "-" and i < n and (query[i] == "(" or query[i] in QUOTES):
                tokens.append(("op", "NOT"))  # -(a OR b) and -"a phrase"
                continue
            negated = len(chunk) > 1 and chunk[0] == "-"
            if negated:
                chunk = chunk[1:]
            field_match = _FIELD.match(chunk)
            if field_match:
                if negated:
                    tokens.append(("bad",))
                else:
                    tokens.append(("field", field_match.group(1).lower(), field_match.group(2)))
                continue
            prefix = chunk.endswith("*")
            words = normalise(chunk).split(" ") if normalise(chunk) else []
            if not words:
                continue
            nodes = [("term", Term(w, False, prefix and k == len(words) - 1)) for k, w in enumerate(words)]
            node = nodes[0] if len(nodes) == 1 else ("and", tuple(nodes))
            tokens.append(("node", ("not", node) if negated else node))
    return tokens


class _Reader:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self):
        token = self.peek()
        self.pos += 1
        return token

    def is_op(self, name):
        token = self.peek()
        return token is not None and token[0] == "op" and token[1] == name

    def at_end_of_and(self):
        token = self.peek()
        return token is None or token[0] == ")" or (token[0] == "op" and token[1] == "OR")

    def parse_or(self, depth):
        if depth > _MAX_DEPTH:
            raise _Malformed
        parts = [self.parse_and(depth)]
        while self.is_op("OR"):
            self.take()
            parts.append(self.parse_and(depth))
        return parts[0] if len(parts) == 1 else ("or", tuple(parts))

    def parse_and(self, depth):
        items = []
        while not self.at_end_of_and():
            if self.is_op("AND"):
                self.take()
                if not items or self.at_end_of_and():
                    raise _Malformed
                continue
            items.append(self.parse_unary(depth))
        if not items:
            raise _Malformed
        return items[0] if len(items) == 1 else ("and", tuple(items))

    def parse_unary(self, depth):
        token = self.take()
        if token is None:
            raise _Malformed
        if token[0] == "(":
            inner = self.parse_or(depth + 1)
            if self.take() != (")",):
                raise _Malformed
            return inner
        if token[0] == "node":
            return token[1]
        if token[0] == "op" and token[1] == "NOT":
            return ("not", self.parse_unary(depth))
        raise _Malformed


def _positive(node, out, negated=False):
    kind = node[0]
    if kind == "term":
        if not negated:
            out.append(node[1])
    elif kind == "not":
        _positive(node[1], out, not negated)
    else:
        for child in node[1]:
            _positive(child, out, negated)


def _all_terms(node, out):
    if node[0] == "term":
        out.append(node[1])
    elif node[0] == "not":
        _all_terms(node[1], out)
    else:
        for child in node[1]:
            _all_terms(child, out)


def _plain(tokens):
    """The fallback: every word and quoted phrase (a "-word" too) as an AND; operators and brackets are ignored."""
    found = []
    for token in tokens:
        if token[0] == "node":
            _all_terms(token[1], found)
        elif token[0] == "field":
            found.extend(Term(w, False) for w in normalise(token[1] + " " + token[2]).split(" ") if w)
    terms = tuple(Term(t.text, t.phrase) for t in found)
    return Parsed(("and", tuple(("term", t) for t in terms)) if terms else None, terms, (), None, NOTICE)


def parse_search(query):
    """Read ``query`` with the operators. Never raises: a query that cannot be read becomes plain words + a notice."""
    tokens = _tokens(query or "")
    try:
        if any(t[0] == "bad" for t in tokens):
            raise _Malformed
        subjects, flags, rest = [], None, []
        for index, token in enumerate(tokens):
            if token[0] != "field":
                rest.append(token)
                continue
            before = tokens[index - 1] if index else None
            after = tokens[index + 1] if index + 1 < len(tokens) else None
            if any(o is not None and o[0] == "op" and o[1] == "OR" for o in (before, after)):
                raise _Malformed
            if token[1] == "subject":
                piece = normalise(token[2])
                if not piece:
                    raise _Malformed
                subjects.append(piece)
            else:
                kinds = FLAG_WORDS.get(token[2].strip().lower())
                if kinds is None:
                    raise _Malformed
                flags = kinds if flags is None else flags | kinds
        if sum(1 for t in rest if t[0] == "(") != sum(1 for t in rest if t[0] == ")"):
            raise _Malformed
        reader = _Reader(rest)
        expr = reader.parse_or(0) if rest else None
        if reader.peek() is not None:
            raise _Malformed
    except (_Malformed, RecursionError):
        return _plain(tokens)
    positive = []
    if expr is not None:
        _positive(expr, positive)
    return Parsed(expr, tuple(positive), tuple(subjects), flags, "")
