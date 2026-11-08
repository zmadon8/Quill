"""The stdlib Word renderer (design 8.1).

``render(prepared, mapping)`` fills a prepared template (the output of ``template_prep.prepare``) with a
placeholder map (``placeholders.build_placeholder_map``) and returns a ``TemporaryFile`` holding the
``.docx``, positioned at the start. For each of ``word/document.xml``, ``word/header*.xml`` and
``word/footer*.xml``:

1. Sections ``{{#FLAG}} ... {{/FLAG}}``. A true flag strips the two markers. A false flag drops the
   enclosing table row (``w:tr``) when the opening marker sits in one, from the row holding the opening
   marker to the row holding the closing marker. Outside a table it drops the enclosing paragraphs the
   same way. A flag the map does not carry counts as false.
2. Tags ``{{TAG}}`` become ``xml.sax.saxutils.escape(value)``, with each ``\\n`` turned into a Word line
   break (``</w:t><w:br/><w:t xml:space="preserve">``). A tag the map does not carry, or whose value is
   not text, renders as nothing. ``MEMO_SIGNATURE``/``MSIG`` has the value ``""`` here, so without a
   signature picture it is removed; with one it becomes an inline picture (see ``render``).
3. Every other zip entry is streamed across unchanged.

Reads are bounded by ``docx_zip`` (design 8.1 limits). Memory is a few times the size of
``document.xml``. Any unreadable template raises ``FeesError("INVALID_TEMPLATE")``; any other failure
raises ``FeesError("EXPORT_FAILED")``.
"""

import re
import tempfile
import zipfile
from xml.sax.saxutils import escape

from fees.errors import FeesError
from fees.exports import docx_zip
from fees.exports.template_prep import MERGE_PART

_LINE_BREAK = '</w:t><w:br/><w:t xml:space="preserve">'
_OPEN_SECTION = re.compile(r"\{\{\s*#\s*([A-Za-z0-9_]+)\s*\}\}")
_TAG = re.compile(r"\{\{([^{}<>]*)\}\}")
_ILLEGAL_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")
_MAX_SECTIONS = 2000

_UNIT_TOKENS = {
    "tr": re.compile(r"<w:tr[\s>]|</w:tr>"),
    "p": re.compile(r"<w:p[\s>]|</w:p>"),
}


def xml_text(value):
    """``value`` as safe WordprocessingML text, with newlines as Word line breaks."""
    text = _ILLEGAL_XML.sub("", str(value)).replace("\r\n", "\n").replace("\r", "\n")
    return escape(text).replace("\n", _LINE_BREAK)


def _enclosing(xml, pos, unit):
    """``(start, end)`` of the innermost ``<w:tr>`` (``unit`` "tr") or ``<w:p>`` ("p") around ``pos``."""
    stack = []
    for match in _UNIT_TOKENS[unit].finditer(xml):
        if match.group(0).startswith("</"):
            if stack:
                start = stack.pop()
                if start <= pos < match.end():
                    return start, match.end()
        else:
            stack.append(match.start())
    return None


def apply_sections(xml, flags):
    """Resolves every ``{{#FLAG}}...{{/FLAG}}`` section in ``xml`` (step 1 of the module doc)."""
    for _ in range(_MAX_SECTIONS):
        opening = _OPEN_SECTION.search(xml)
        if opening is None:
            break
        name = opening.group(1)
        closing = re.compile(r"\{\{\s*/\s*" + re.escape(name) + r"\s*\}\}").search(xml, opening.end())
        if closing is None:
            xml = xml[: opening.start()] + xml[opening.end():]
        elif flags.get(name) is True:
            xml = (
                xml[: opening.start()]
                + xml[opening.end() : closing.start()]
                + xml[closing.end():]
            )
        else:
            first = last = None
            for unit in ("tr", "p"):
                first = _enclosing(xml, opening.start(), unit)
                if first is not None:
                    last = _enclosing(xml, closing.start(), unit)
                    break
            if first is not None and last is not None and last[1] >= first[1]:
                xml = xml[: first[0]] + xml[last[1]:]
            else:
                xml = xml[: opening.start()] + xml[closing.end():]
    return xml


def substitute_tags(xml, mapping):
    """Replaces every ``{{TAG}}`` in ``xml`` by its escaped text value (step 2 of the module doc)."""

    def replace(match):
        value = mapping.get(match.group(1).strip())
        return xml_text(value) if isinstance(value, str) else ""

    return _TAG.sub(replace, xml)


_SIGNATURE_TAG = re.compile(r"\{\{\s*(?:MEMO_SIGNATURE|MSIG)\s*\}\}")

_NS_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_NS_PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
_NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_PKG_RELS = "http://schemas.openxmlformats.org/package/2006/relationships"
_REL_IMAGE = _NS_R + "/image"
_EMU_PER_PIXEL = 9525
_MAX_WIDTH_EMU = 6 * 360000  # 6 cm
_MAX_HEIGHT_EMU = 25 * 36000  # 2.5 cm
_SIGNATURE_REL_ID = "rIdMemoSignature"
_DOCUMENT_PART = "word/document.xml"
_RELS_PART = "word/_rels/document.xml.rels"
_CONTENT_TYPES_PART = "[Content_Types].xml"


class Signature:
    """A signature picture to embed: ``content_type``, ``extension`` (png or jpeg), ``data`` bytes and
    the pixel ``width`` and ``height`` (from ``images.inspect_image``)."""

    def __init__(self, content_type, extension, data, width, height):
        self.content_type = content_type
        self.extension = extension
        self.data = data
        self.width = width
        self.height = height

    def extent(self):
        """``(cx, cy)`` in EMU: the natural size scaled down (never up) to fit 6 cm by 2.5 cm."""
        cx = self.width * _EMU_PER_PIXEL
        cy = self.height * _EMU_PER_PIXEL
        scale = min(1.0, _MAX_WIDTH_EMU / cx, _MAX_HEIGHT_EMU / cy)
        return max(1, int(cx * scale)), max(1, int(cy * scale))


def drawing_xml(signature, rel_id, doc_pr_id):
    """The inline ``w:drawing`` for the picture, closing and reopening the surrounding ``w:t``."""
    cx, cy = signature.extent()
    return (
        "</w:t><w:drawing>"
        f'<wp:inline xmlns:wp="{_NS_WP}" distT="0" distB="0" distL="0" distR="0">'
        f'<wp:extent cx="{cx}" cy="{cy}"/>'
        f'<wp:docPr id="{doc_pr_id}" name="Signature {doc_pr_id}"/>'
        f'<a:graphic xmlns:a="{_NS_A}">'
        f'<a:graphicData uri="{_NS_PIC}">'
        f'<pic:pic xmlns:pic="{_NS_PIC}">'
        '<pic:nvPicPr><pic:cNvPr id="0" name="Signature"/><pic:cNvPicPr/></pic:nvPicPr>'
        f'<pic:blipFill><a:blip xmlns:r="{_NS_R}" r:embed="{rel_id}"/>'
        "<a:stretch><a:fillRect/></a:stretch></pic:blipFill>"
        f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
        "</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing>"
        '<w:t xml:space="preserve">'
    )


def embed_signature_tags(xml, signature, rel_id):
    """Replaces each signature tag in ``xml`` by a picture run; returns ``(xml, count)``."""
    counter = [0]

    def replace(_match):
        counter[0] += 1
        return drawing_xml(signature, rel_id, 9000 + counter[0])

    return _SIGNATURE_TAG.sub(replace, xml), counter[0]


def render_xml(xml, mapping, signature=None, rel_id=None):
    """Sections, then the signature picture, then tags, for one XML part.

    Returns the text; with a ``signature`` use ``render_document_xml`` to also learn the picture count.
    """
    return render_document_xml(xml, mapping, signature, rel_id)[0]


def render_document_xml(xml, mapping, signature=None, rel_id=None):
    """Like ``render_xml`` but returns ``(xml, pictures_embedded)``."""
    xml = apply_sections(xml, mapping)
    count = 0
    if signature is not None and rel_id:
        xml, count = embed_signature_tags(xml, signature, rel_id)
    return substitute_tags(xml, mapping), count


def _unique_name(existing, stem, extension):
    name = f"word/media/{stem}.{extension}"
    number = 1
    while name in existing:
        number += 1
        name = f"word/media/{stem}{number}.{extension}"
    return name


def _add_relationship(rels_xml, target):
    """Adds the image relationship to the text of ``document.xml.rels`` (or makes a new one)."""
    entry = (
        f'<Relationship Id="{_SIGNATURE_REL_ID}" Type="{_REL_IMAGE}" Target="{target}"/>'
    )
    if rels_xml is None:
        return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{_NS_PKG_RELS}">{entry}</Relationships>'
    rels_xml = re.sub(r'<Relationship\b[^>]*\bId="' + _SIGNATURE_REL_ID + r'"[^>]*/>', "", rels_xml)
    if "</Relationships>" in rels_xml:
        return rels_xml.replace("</Relationships>", entry + "</Relationships>", 1)
    return re.sub(r"<Relationships\b([^>]*)/>", r"<Relationships\1>" + entry + "</Relationships>", rels_xml, 1)


def _add_content_type(types_xml, extension, content_type):
    """Adds a ``Default`` for ``extension`` to ``[Content_Types].xml`` unless one exists."""
    if re.search(r'<Default\b[^>]*\bExtension="' + re.escape(extension) + '"', types_xml, re.I):
        return types_xml
    entry = f'<Default Extension="{extension}" ContentType="{content_type}"/>'
    return re.sub(r"(<Types\b[^>]*>)", lambda m: m.group(1) + entry, types_xml, 1)


def _decode(raw):
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise docx_zip.DocxError("A part of the Word template is not valid text.") from None


def render(prepared, mapping, signature=None):
    """Renders ``prepared`` with ``mapping``; returns a ``TemporaryFile`` at position 0.

    With a ``Signature`` and at least one signature tag in ``word/document.xml``, the picture is added as
    a ``word/media/`` part, ``word/_rels/document.xml.rels`` gets the relationship, ``[Content_Types].xml``
    gets a ``Default`` for the extension if needed, and each tag becomes a ``w:drawing`` run. A tag in a
    header or footer is removed (those parts have their own relationships). With no signature, or no tag
    in the document, no part is added.
    """
    try:
        zf = docx_zip.open_zip(bytes(prepared))
    except docx_zip.DocxError as exc:
        raise FeesError("INVALID_TEMPLATE", exc.message) from None
    budget = docx_zip.Budget()
    out_file = tempfile.TemporaryFile()
    try:
        try:
            rendered = {}
            pictures = 0
            infos = list(zf.infolist())
            existing = {info.filename for info in infos}
            media_name = (
                _unique_name(existing, "memo_signature", signature.extension) if signature else None
            )
            rel_target = media_name[len("word/"):] if media_name else None
            for info in infos:
                if MERGE_PART.match(info.filename):
                    raw = docx_zip.read_part(zf, info, budget)
                    text = _decode(raw)
                    if info.filename == _DOCUMENT_PART:
                        text, pictures = render_document_xml(text, mapping, signature, _SIGNATURE_REL_ID)
                    else:
                        text = render_xml(text, mapping)
                    rendered[info.filename] = text
            if _DOCUMENT_PART not in rendered:
                raise docx_zip.DocxError("The file is not a Word template (word/document.xml is missing).")
            if pictures:
                by_name = {info.filename: info for info in infos}
                rels_info = by_name.get(_RELS_PART)
                rels_xml = None
                if rels_info is not None:
                    rels_xml = _decode(
                        docx_zip.read_part(zf, rels_info, budget, docx_zip.MAX_SMALL_PART_BYTES)
                    )
                rendered[_RELS_PART] = _add_relationship(rels_xml, rel_target)
                types_info = by_name.get(_CONTENT_TYPES_PART)
                if types_info is not None:
                    types_xml = _decode(
                        docx_zip.read_part(zf, types_info, budget, docx_zip.MAX_SMALL_PART_BYTES)
                    )
                    rendered[_CONTENT_TYPES_PART] = _add_content_type(
                        types_xml, signature.extension, signature.content_type
                    )
            with zipfile.ZipFile(out_file, "w", zipfile.ZIP_DEFLATED) as out:
                for info in infos:
                    if info.filename.endswith("/"):
                        continue
                    if info.filename in rendered:
                        out.writestr(docx_zip.new_info(info), rendered[info.filename].encode("utf-8"))
                    else:
                        docx_zip.copy_part(zf, info, out, budget)
                if pictures:
                    if _RELS_PART not in existing:
                        out.writestr(_RELS_PART, rendered[_RELS_PART].encode("utf-8"))
                    budget.consume(len(signature.data))
                    out.writestr(media_name, signature.data)
        except docx_zip.DocxError as exc:
            raise FeesError("INVALID_TEMPLATE", exc.message) from None
        except FeesError:
            raise
        except Exception as exc:  # noqa: BLE001 - any renderer fault is one user-facing error
            raise FeesError("EXPORT_FAILED", f"Failed to render template: {exc}") from None
    except BaseException:
        out_file.close()
        raise
    finally:
        zf.close()
    out_file.seek(0)
    return out_file
