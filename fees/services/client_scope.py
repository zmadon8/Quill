"""The Client filter shared by the lists (owner round 2026-11): ``client_id`` is a client's id, or ``BLANK`` for matters with no client.

A matter's client is on the matter only, so memos, allocations and the rest reach it through their matter (``prefix`` is the path to the
matter's ``client`` field, for example ``"matter__"`` for memos or ``"memo__matter__"`` for allocations). No import of other fee modules,
so every list service can use it."""

#: The ``client`` URL value (and ``client_id`` filter value) for "No client".
BLANK = "blank"


def parse(value):
    """The ``client`` URL value as a filter value: an id, ``BLANK``, or ``None`` (no filter)."""
    text = str(value or "").strip()
    if text == BLANK:
        return BLANK
    return int(text) if text.isdigit() else None


def narrow(qs, client_id, prefix):
    """``qs`` narrowed to ``client_id`` (``None`` leaves it as it is)."""
    if client_id is None:
        return qs
    if client_id == BLANK:
        return qs.filter(**{f"{prefix}client__isnull": True})
    return qs.filter(**{f"{prefix}client_id": client_id})
