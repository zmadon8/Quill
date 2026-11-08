"""The downloadable Word Template Tags reference (owner item 2.5).

``build_tag_reference()`` returns the bytes of a small ``.docx`` that lists every tag the memo template
accepts: a table per group with the long name, the short name, what it fills in and an example. It is
built from the real tag sets in ``placeholders`` (``LINE_TAGS``, ``MEMO_TAGS``, ``SIGNATURE_TAGS``,
``FLAG_ALIASES``) and the wording in ``placeholders.TAG_DOCS``, so it cannot drift from the renderer.
The layout follows ``docs/fee_register_port/templates/Template Tags Reference.docx``.

Only the standard library is used: the file is written with ``zipfile`` as plain WordprocessingML (no
styles part, direct formatting only), so it opens in Word and LibreOffice. Pure function, no database.
"""
import io
import zipfile
from xml.sax.saxutils import escape

from fees.exports.placeholders import (
    FLAG_ALIASES,
    MEMO_TAGS,
    SIGNATURE_TAGS,
    TAG_DOCS,
    line_short_name,
)

__all__ = ["GROUPS", "FILE_NAME", "names_for", "build_tag_reference"]

FILE_NAME = "Template Tags Reference.docx"

#: ``(heading, intro or "", keys of TAG_DOCS)`` in page order.
GROUPS = (
    ("Memo details", "", ("LINE_1_DATE", "LINE_2_MEMO_NUMBER")),
    (
        "Addressee and matter",
        "",
        (
            "LINE_5_ADDRESSEE_1",
            "LINE_6_ADDRESSEE_2",
            "LINE_7_MATTER_NAME",
            "LINE_8_COURT_NAME",
            "LINE_9_ADD_LEFT",
            "LINE_10_ADD_RIGHT",
        ),
    ),
    (
        "Parties",
        "",
        (
            "LINE_11_PLAINTIFF",
            "LINE_12_PLAINTIFF_TYPE",
            "LINE_13_DEFENDANT",
            "LINE_14_DEFENDANT_TYPE",
            "LINE_15_CLIENT",
        ),
    ),
    (
        "Appearances",
        "",
        (
            "LINE_16_NUM_APPEARANCES",
            "L16W",
            "LINE_17_DATES_APPEARANCES",
            "LINE_18_FEES_PER_APP",
            "LINE_18A_FEES_APPEARANCES",
        ),
    ),
    (
        "Conferences",
        "",
        (
            "LINE_19_NUM_CONFERENCES",
            "L19W",
            "LINE_20_DATES_CONFERENCES",
            "LINE_21_FEES_PER_CONF",
            "LINE_21A_FEES_CONFERENCES",
        ),
    ),
    (
        "Drafting, miscellaneous and totals",
        "",
        (
            "LINE_22_MISC_DESC",
            "LINE_23_FEES_MISC",
            "LINE_24_TOTAL_FEES",
            "LINE_24A_TOTAL_FEES_WORDS",
        ),
    ),
    (
        "Your details and signature",
        "These come from Settings, not from the memo. The signature is printed only when the memo's "
        "signature box is ticked and a signature image has been uploaded.",
        ("MEMO_NAME", "MEMO_DESIGNATION", "MEMO_ADDRESS", "MEMO_BANK_DETAILS", "MEMO_PAN", "MEMO_SIGNATURE"),
    ),
    (
        "Show-or-hide sections",
        "Wrap a line in a pair of these tags and the whole block disappears when it does not apply. "
        "Put the opening tag (with #) at the start of the row or paragraph and the closing tag "
        "(with /) at its end.",
        (
            "SHOW_APPEARANCES",
            "SHOW_CONFERENCES",
            "SHOW_MISC",
            "SHOW_PLAINTIFF",
            "SHOW_DEFENDANT",
            "SHOW_CLIENT",
        ),
    ),
)

_COLUMNS = ("Long name", "Short name", "What it fills in", "Example")
_WIDTHS = (2700, 1500, 3700, 2000)  # twentieths of a point; about 9900 in all
_HEADER_FILL = "D9E2F3"

_MEMO_SHORT = {long_name: short for long_name, short, _field in MEMO_TAGS}
_MEMO_SHORT[SIGNATURE_TAGS[0]] = SIGNATURE_TAGS[1]


def names_for(key):
    """``(long name, short name)`` for a ``TAG_DOCS`` key, as plain tag names.

    A line tag's short name is ``L`` plus its number; ``L16W`` and ``L19W`` have no long name (``None``).
    """
    if key in _MEMO_SHORT:
        return key, _MEMO_SHORT[key]
    if key in FLAG_ALIASES:
        return key, FLAG_ALIASES[key]
    short = line_short_name(key)
    if short:
        return key, short
    return None, key


def _tag(name, flag=False):
    if name is None:
        return "(none)"
    return "{{#%s}}" % name if flag else "{{%s}}" % name


def _run(text, bold=False, size=None):
    props = ""
    if bold:
        props += "<w:b/>"
    if size:
        props += '<w:sz w:val="%d"/>' % size
    rpr = "<w:rPr>%s</w:rPr>" % props if props else ""
    return '<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % (rpr, escape(text))


def _para(text, bold=False, size=None, after=120):
    return '<w:p><w:pPr><w:spacing w:before="0" w:after="%d"/></w:pPr>%s</w:p>' % (
        after,
        _run(text, bold, size),
    )


def _cell(text, width, bold=False, fill=None):
    shade = '<w:shd w:val="clear" w:color="auto" w:fill="%s"/>' % fill if fill else ""
    return '<w:tc><w:tcPr><w:tcW w:w="%d" w:type="dxa"/>%s</w:tcPr>%s</w:tc>' % (
        width,
        shade,
        _para(text, bold=bold, after=0),
    )


def _row(values, bold=False, fill=None, header=False):
    props = "<w:trPr><w:tblHeader/></w:trPr>" if header else ""
    cells = "".join(_cell(v, w, bold, fill) for v, w in zip(values, _WIDTHS))
    return "<w:tr>%s%s</w:tr>" % (props, cells)


def _table(rows):
    border = "".join(
        '<w:%s w:val="single" w:sz="4" w:space="0" w:color="808080"/>' % side
        for side in ("top", "left", "bottom", "right", "insideH", "insideV")
    )
    grid = "".join('<w:gridCol w:w="%d"/>' % w for w in _WIDTHS)
    head = _row(_COLUMNS, bold=True, fill=_HEADER_FILL, header=True)
    return (
        '<w:tbl><w:tblPr><w:tblW w:w="%d" w:type="dxa"/><w:tblBorders>%s</w:tblBorders>'
        '<w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid>%s</w:tblGrid>%s%s</w:tbl>'
        % (sum(_WIDTHS), border, grid, head, "".join(rows))
    )


def _table_rows(keys):
    rows = []
    for key in keys:
        long_name, short_name = names_for(key)
        description, example = TAG_DOCS[key]
        flag = key in FLAG_ALIASES
        rows.append(
            _row(
                (
                    _tag(long_name, flag),
                    _tag(short_name, flag),
                    description,
                    example,
                )
            )
        )
    return rows


def _document_xml():
    body = [
        _para("Fee Register: Word Template Tags", bold=True, size=36, after=200),
        _para(
            "Put these tags in your memo template (a .docx file). When a memo is exported to Word, each "
            "tag is replaced with that memo's value. Tags are written with double curly braces, exactly "
            "as shown, for example {{L7}}."
        ),
        _para(
            "Every line has a short name made of L and the line number, and a long name. Both work, and "
            "you can mix them in one template."
        ),
    ]
    for heading, intro, keys in GROUPS:
        body.append(_para(heading, bold=True, size=28, after=80))
        if intro:
            body.append(_para(intro))
        body.append(_table(_table_rows(keys)))
        body.append(_para("", after=160))
    sect = (
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1000" w:right="900" w:bottom="1000" w:left="900" '
        'w:header="500" w:footer="500" w:gutter="0"/></w:sectPr>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>%s%s</w:body></w:document>" % ("".join(body), sect)
    )


_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)
_ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="word/document.xml"/></Relationships>'
)


def build_tag_reference():
    """The tag reference as ``.docx`` bytes."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _ROOT_RELS)
        archive.writestr("word/document.xml", _document_xml())
    return out.getvalue()
