"""Stdlib helpers for building small ``.docx`` files and tiny images in Word export tests."""

import io
import struct
import zipfile
import zlib

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.'
    'wordprocessingml.document.main+xml"/></Types>'
)
ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
    'officeDocument" Target="word/document.xml"/></Relationships>'
)
DOC_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>'
)
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def paragraph(text):
    return f'<w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


def document_xml(*paragraphs):
    return (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="{W_NS}"><w:body>'
        + "".join(paragraphs)
        + "</w:body></w:document>"
    )


def build_docx(document, extra=None, rels=DOC_RELS, content_types=CONTENT_TYPES):
    """A minimal ``.docx`` as bytes. ``extra`` maps part name to str or bytes; ``rels=None`` omits it."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", ROOT_RELS)
        zf.writestr("word/document.xml", document)
        if rels is not None:
            zf.writestr("word/_rels/document.xml.rels", rels)
        for name, value in (extra or {}).items():
            zf.writestr(name, value)
    return buffer.getvalue()


def _chunk(kind, body):
    crc = zlib.crc32(kind + body) & 0xFFFFFFFF
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)


def png_bytes(width=40, height=20):
    """A valid, small, solid-colour RGB PNG."""
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x20\x40\x80" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(raw))
        + _chunk(b"IEND", b"")
    )


def jpeg_bytes(width=30, height=15):
    """JPEG bytes with a real SOI, a SOF0 header carrying the size, and an EOI (header-only checks)."""
    sof = struct.pack(">BHHB", 8, height, width, 1) + b"\x01\x11\x00"
    return (
        b"\xff\xd8\xff\xe0\x00\x04\x00\x00"
        + b"\xff\xc0"
        + struct.pack(">H", len(sof) + 2)
        + sof
        + b"\xff\xd9"
    )


def read_zip(data):
    """``{name: bytes}`` for a zip given as bytes or a file object."""
    if hasattr(data, "read"):
        data = data.read()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return {name: zf.read(name) for name in zf.namelist()}
