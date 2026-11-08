"""Safe, bounded access to a ``.docx`` zip (design 8.1 and 8.4, requirements R-SET-3).

The Word template is user supplied, so a zip is never trusted. This module is the one place the limits
live, and both ``template_prep`` (upload time) and ``word`` (render time) use it:

* at most ``MAX_ENTRIES`` (200) entries;
* at most ``MAX_TOTAL_BYTES`` (20 MB) uncompressed in total, counted from the bytes actually read and
  not from the declared ``file_size`` (a forged zip can declare any size, so a declared size is only an
  early reject, never the gate);
* no single XML part over ``MAX_XML_PART_BYTES``;
* an uploaded template of at most ``MAX_TEMPLATE_BYTES`` (2 MB, R-SET-3).

Every read is chunked. Parts that are only copied (images, styles, fonts) are streamed from the source
zip to the output zip chunk by chunk, so they are never held whole in memory. Stdlib only.
"""

import io
import zipfile
import zlib

MAX_ENTRIES = 200
MAX_TOTAL_BYTES = 20 * 1024 * 1024
MAX_TEMPLATE_BYTES = 2 * 1024 * 1024
MAX_XML_PART_BYTES = 10 * 1024 * 1024
MAX_SMALL_PART_BYTES = 1024 * 1024  # [Content_Types].xml and .rels files
CHUNK_SIZE = 64 * 1024


class DocxError(Exception):
    """The zip is unreadable or breaks a limit. ``message`` is safe to show to the user."""

    def __init__(self, message):
        self.message = message
        super().__init__(message)


class Budget:
    """Counts uncompressed bytes actually read across a whole zip against ``MAX_TOTAL_BYTES``."""

    def __init__(self, limit=MAX_TOTAL_BYTES):
        self.limit = limit
        self.used = 0

    def consume(self, count):
        self.used += count
        if self.used > self.limit:
            raise DocxError("The Word file expands to more than 20 MB, so it was refused.")


def open_zip(data):
    """Opens ``data`` (bytes) as a zip and checks the entry count and the declared sizes."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        infos = zf.infolist()
    except (zipfile.BadZipFile, OSError, ValueError, EOFError, zlib.error):
        raise DocxError("The file is not a readable Word (.docx) file.") from None
    if len(infos) > MAX_ENTRIES:
        zf.close()
        raise DocxError("The Word file has more than 200 parts, so it was refused.")
    names = set()
    declared = 0
    for info in infos:
        if info.filename in names:
            zf.close()
            raise DocxError("The Word file has repeated part names, so it was refused.")
        names.add(info.filename)
        declared += max(info.file_size, 0)
    if declared > MAX_TOTAL_BYTES:
        zf.close()
        raise DocxError("The Word file expands to more than 20 MB, so it was refused.")
    return zf


def _chunks(zf, info):
    try:
        with zf.open(info) as src:
            while True:
                chunk = src.read(CHUNK_SIZE)
                if not chunk:
                    return
                yield chunk
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, EOFError, zlib.error):
        raise DocxError("A part of the Word file could not be read.") from None


def read_part(zf, info, budget, limit=MAX_XML_PART_BYTES):
    """Reads one part fully, in chunks, stopping at ``limit`` bytes or when the budget is spent."""
    parts = []
    size = 0
    for chunk in _chunks(zf, info):
        size += len(chunk)
        if size > limit:
            raise DocxError("A part of the Word file is too large, so it was refused.")
        budget.consume(len(chunk))
        parts.append(chunk)
    return b"".join(parts)


def new_info(info):
    """A fresh deflated ``ZipInfo`` carrying the name, timestamp and attributes of ``info``."""
    fresh = zipfile.ZipInfo(info.filename, info.date_time)
    fresh.compress_type = zipfile.ZIP_DEFLATED
    fresh.external_attr = info.external_attr
    return fresh


def copy_part(zf, info, out, budget):
    """Streams one part from ``zf`` into the output zip ``out`` without holding it whole."""
    with out.open(new_info(info), "w") as dst:
        for chunk in _chunks(zf, info):
            budget.consume(len(chunk))
            dst.write(chunk)
