"""Read-only reader for a .docx file (standard library only). The file is never modified."""
import hashlib
import io
import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

#: Run properties that carry no information we need (complex-script duplicates of bold/italic).
_IGNORED_RUN_PROPS = {"b", "i", "u", "bCs", "iCs", "szCs", "lang", "noProof", "rFonts"}
#: Heading runs are bold and large by style; that is not "other formatting" worth reporting there.
_IGNORED_ON_HEADINGS = {"sz", "szCs", "color", "rFonts"}
#: Elements inside a run that are not plain text. They are reported, never silently dropped.
_RUN_PARTS_OK = {"rPr", "t", "lastRenderedPageBreak"}


class DocxError(Exception):
    """The file is not a readable Word document, or lacks a part the importer needs."""


@dataclass
class Run:
    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False


@dataclass
class Paragraph:
    index: int  # 0-based position among all paragraphs of the file
    style: str
    num_id: str  # "" when the paragraph is not a list entry
    list_format: str  # Word's numFmt of the list entry ("decimal", "lowerRoman", ...), "" if none
    text: str
    runs: list = field(default_factory=list)
    other_formatting: list = field(default_factory=list)  # e.g. ["color", "sz"] on any run
    odd_parts: list = field(default_factory=list)  # tabs, line breaks, fields and so on inside runs


def _on(element):
    """A toggle property such as <w:b/> is on unless its value is 0, false, off or none."""
    if element is None:
        return False
    return element.get(W + "val") not in ("0", "false", "off", "none")


def _numbering_formats(numbering_root):
    """numId -> {ilvl: numFmt}."""
    abstract = {}
    for a in numbering_root.findall(W + "abstractNum"):
        levels = {}
        for lvl in a.findall(W + "lvl"):
            fmt = lvl.find(W + "numFmt")
            levels[lvl.get(W + "ilvl")] = fmt.get(W + "val") if fmt is not None else ""
        abstract[a.get(W + "abstractNumId")] = levels
    out = {}
    for n in numbering_root.findall(W + "num"):
        abstract_id = n.find(W + "abstractNumId").get(W + "val")
        out[n.get(W + "numId")] = abstract.get(abstract_id, {})
    return out


def read_docx(data):
    """Parse the bytes of a .docx. Returns (paragraphs, notes) where notes is a dict of facts about the file."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        document = ET.fromstring(archive.read("word/document.xml"))
        numbering = (
            ET.fromstring(archive.read("word/numbering.xml")) if "word/numbering.xml" in archive.namelist() else None
        )
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        raise DocxError("This is not a readable Word (.docx) file.") from exc
    formats = _numbering_formats(numbering) if numbering is not None else {}

    paragraphs = []
    for index, p in enumerate(document.iter(W + "p")):
        style_el = p.find(W + "pPr/" + W + "pStyle")
        style = style_el.get(W + "val") if style_el is not None else "Normal"
        num_pr = p.find(W + "pPr/" + W + "numPr")
        num_id = list_format = ""
        if num_pr is not None:
            id_el = num_pr.find(W + "numId")
            lvl_el = num_pr.find(W + "ilvl")
            num_id = id_el.get(W + "val") if id_el is not None else ""
            level = lvl_el.get(W + "val") if lvl_el is not None else "0"
            list_format = formats.get(num_id, {}).get(level, "")
        para = Paragraph(index=index, style=style, num_id=num_id, list_format=list_format, text="")
        heading = style.startswith("Heading")
        ignored = _IGNORED_RUN_PROPS | (_IGNORED_ON_HEADINGS if heading else set())
        pieces = []
        for r in p.iter(W + "r"):
            props = r.find(W + "rPr")
            bold = italic = underline = False
            if props is not None:
                bold = _on(props.find(W + "b"))
                italic = _on(props.find(W + "i"))
                underline = _on(props.find(W + "u"))
                for prop in props:
                    name = prop.tag.replace(W, "")
                    if name not in ignored and name not in para.other_formatting:
                        para.other_formatting.append(name)
            text = ""
            for part in r:
                name = part.tag.replace(W, "")
                if name == "t":
                    text += part.text or ""
                elif name == "tab":
                    text += "\t"
                    para.odd_parts.append("tab")
                elif name in ("br", "cr"):
                    text += "\n"
                    para.odd_parts.append("line break")
                elif name not in _RUN_PARTS_OK:
                    para.odd_parts.append(name)
            if text:
                pieces.append(Run(text, bold, italic, underline))
        para.runs = pieces
        para.text = "".join(run.text for run in pieces)
        paragraphs.append(para)

    notes = {
        "tables": len(list(document.iter(W + "tbl"))),
        "images": len(list(document.iter(W + "drawing"))) + len(list(document.iter(W + "pict"))),
        "footnote_references": len(list(document.iter(W + "footnoteReference"))),
    }
    return paragraphs, notes


def file_digest(data):
    return hashlib.sha256(data).hexdigest()
