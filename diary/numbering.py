"""Generated numbering (docs/DESIGN.md section 4). Pure Python, no Django."""

BULLET = "\u2022"

ITEM_FORMATS = (
    "A", "a", "1", "I", "i", "(A)", "(i)", "(a)", "(1)", "bullet", "none",
)
SECTION_FORMATS = ITEM_FORMATS + ("Section 1",)

ITEM = "item"
SECTION = "section"
NOTE = "note"

_ROMAN = (
    (1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
    (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"),
)


def letters(n, upper=False):
    """1 -> a, 26 -> z, 27 -> aa, 28 -> ab, 53 -> ba. Never fails for n >= 1."""
    if n < 1:
        return str(n)
    out = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out = chr(97 + rem) + out
    return out.upper() if upper else out


def roman(n, upper=False):
    """Roman numerals up to 3999; plain numbers beyond (and below 1)."""
    if n < 1 or n > 3999:
        return str(n)
    out = ""
    for value, sym in _ROMAN:
        while n >= value:
            out += sym
            n -= value
    return out.upper() if upper else out


def format_number(n, fmt):
    """Format position n (1-based) in a format key from ITEM_FORMATS/SECTION_FORMATS."""
    if fmt == "none":
        return ""
    if fmt == "bullet":
        return BULLET
    if fmt == "Section 1":
        return f"Section {n}"
    wrapped = fmt.startswith("(") and fmt.endswith(")")
    core = fmt[1:-1] if wrapped else fmt
    if core == "A":
        text = letters(n, upper=True)
    elif core == "a":
        text = letters(n)
    elif core == "1":
        text = str(n)
    elif core == "I":
        text = roman(n, upper=True)
    elif core == "i":
        text = roman(n)
    else:
        raise ValueError(f"Unknown number format: {fmt!r}")
    return f"({text})" if wrapped else text


def number_siblings(count, fmt):
    """Labels for a plain run of count siblings (Topics, Sub-topics)."""
    return [format_number(i, fmt) for i in range(1, count + 1)]


def number_children(kinds, item_format="(1)", section_format="(a)"):
    """Labels for the ordered children of one container.

    kinds: sequence of "item", "section" or "note".
    Sections are numbered 1..n in their own run. Items share
    one run that restarts after each Section. Notes get "" and are not counted.
    """
    labels = []
    section_no = 0
    item_no = 0
    for kind in kinds:
        if kind == SECTION:
            section_no += 1
            item_no = 0
            labels.append(format_number(section_no, section_format))
        elif kind == ITEM:
            item_no += 1
            labels.append(format_number(item_no, item_format))
        elif kind == NOTE:
            labels.append("")
        else:
            raise ValueError(f"Unknown child kind: {kind!r}")
    return labels


def multi_item_labels(count):
    """Multi-Item citations: (a), (b), (c) inside the item."""
    return number_siblings(count, "(a)")


def display_label(label):
    """A label as the reading page shows it: 'A' -> 'A.', '1' -> '1.', 'Section 1' -> 'Section 1.'.

    Labels already closed by a bracket ('(a)'), a bullet or nothing are returned unchanged.
    """
    label = str(label or "")
    if label and label[-1].isalnum():
        return label + "."
    return label
