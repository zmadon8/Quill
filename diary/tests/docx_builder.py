"""Builds small .docx files in memory for the importer tests (standard library only)."""
import io
import zipfile
from xml.sax.saxutils import escape

NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

#: kind -> (style, numFmt or None)
KINDS = {
    "subject": ("Heading1", "upperRoman"),
    "topic": ("Heading2", "upperLetter"),
    "subtopic": ("ListParagraph", "decimal"),
    "item": ("ListParagraph", "lowerRoman"),
    "section": ("ListParagraph", "lowerLetter"),
    "blank": ("Normal", None),
    "bullet": ("ListParagraph", "bullet"),
}


def _run(text, bold=False, italic=False, extra=""):
    props = ("<w:b/>" if bold else "") + ("<w:i/>" if italic else "") + extra
    rpr = f"<w:rPr>{props}</w:rPr>" if props else ""
    return f'<w:r>{rpr}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def make_docx(lines):
    """``lines`` is a list of (kind, text) or (kind, text, list_key) or (kind, [(text, bold, italic), ...]).

    Lines of one kind with the same ``list_key`` (default: the kind) share one Word list.
    """
    list_ids = {}
    formats = {}
    body = []
    for line in lines:
        kind, content = line[0], line[1]
        key = line[2] if len(line) > 2 else kind
        style, fmt = KINDS[kind]
        ppr = f'<w:pStyle w:val="{style}"/>'
        if fmt:
            num_id = list_ids.setdefault((kind, key), len(list_ids) + 1)
            formats[num_id] = fmt
            ppr += f'<w:numPr><w:ilvl w:val="0"/><w:numId w:val="{num_id}"/></w:numPr>'
        if isinstance(content, str):
            runs = _run(content) if content else ""
        else:
            runs = "".join(_run(*part) for part in content)
        body.append(f"<w:p><w:pPr>{ppr}</w:pPr>{runs}</w:p>")
    document = f'<?xml version="1.0" encoding="UTF-8"?><w:document {NS}><w:body>{"".join(body)}</w:body></w:document>'
    abstracts = "".join(
        f'<w:abstractNum w:abstractNumId="{n}"><w:lvl w:ilvl="0"><w:numFmt w:val="{fmt}"/><w:lvlText w:val="%1"/></w:lvl>'
        "</w:abstractNum>"
        for n, fmt in formats.items()
    )
    nums = "".join(
        f'<w:num w:numId="{n}"><w:abstractNumId w:val="{n}"/></w:num>' for n in formats
    )
    numbering = f'<?xml version="1.0" encoding="UTF-8"?><w:numbering {NS}>{abstracts}{nums}</w:numbering>'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document)
        archive.writestr("word/numbering.xml", numbering)
    return buffer.getvalue()


#: A small file that exercises every rule.
SMALL = [
    ("subject", "Arbitration"),
    ("topic", "Scope:"),
    ("subtopic", "Reference:"),
    ("item", "Clean proposition - Alpha v Beta [(2010) 1 SCC 1]"),
    ("item", "Only a case name"),
    ("item", "Two dashes - here - Gamma [(2011) 2 SCC 2]"),
    ("item", [("Italic start - ", False, False), ("Delta [(2012) 3 SCC 3]", False, True)]),
    ("topic", "Direct items"),
    ("item", "Direct one - Eps [(2013) 4 SCC 4]"),
    ("item", "Direct two - Zeta [(2014) 5 SCC 5]", "second list"),
    ("blank", ""),
    ("subject", "Miscellaneous"),
    ("topic", "Stamp Act"),
    ("subtopic", "Duty"),
    ("item", "Stamp item - Eta [(2015) 6 SCC 6]"),
    ("topic", "Tender"),
    ("item", "Tender item - Broken [(2019) 1 SCC 1"),
    ("subject", "Procedure"),
    ("topic", "Letters Patent"),
    ("subtopic", "Clause 12"),
    ("section", "Ex Parte"),
    ("item", "Under a - Theta [(2016) 7 SCC 7]", "after a"),
    ("section", "Determining"),
    ("item", "Under b one - Iota [(2017) 8 SCC 8]", "after b"),
    ("item", "Under b two - Kappa [(2018) 9 SCC 9]", "after b"),
]
