"""Signature image checks by header only (design 8.4, R-SET-8). Stdlib only, no image library.

``inspect_image(data)`` reads the PNG or JPEG header and returns ``(content_type, extension, width,
height)`` in pixels, or ``None`` when ``data`` is neither a PNG nor a JPEG or the header is damaged or
gives a size outside 1 to ``MAX_PIXELS`` on either side. It never decodes pixels.
"""

import struct

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MAX_PIXELS = 20000


def _png_size(data):
    if len(data) < 24 or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def _jpeg_size(data):
    count = len(data)
    pos = 2
    while pos + 4 <= count:
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker = data[pos + 1]
        if marker == 0xFF:
            pos += 1
            continue
        if marker == 0x01 or 0xD0 <= marker <= 0xD9:
            pos += 2
            continue
        length = struct.unpack(">H", data[pos + 2 : pos + 4])[0]
        if length < 2:
            return None
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if pos + 9 > count:
                return None
            height, width = struct.unpack(">HH", data[pos + 5 : pos + 9])
            return width, height
        pos += 2 + length
    return None


def inspect_image(data):
    """``(content_type, extension, width, height)`` for a PNG or JPEG, else ``None``."""
    if data[:8] == PNG_MAGIC:
        kind = ("image/png", "png")
        size = _png_size(data)
    elif data[:3] == b"\xff\xd8\xff":
        kind = ("image/jpeg", "jpeg")
        size = _jpeg_size(data)
    else:
        return None
    if size is None:
        return None
    width, height = size
    if not (1 <= width <= MAX_PIXELS and 1 <= height <= MAX_PIXELS):
        return None
    return kind[0], kind[1], width, height
