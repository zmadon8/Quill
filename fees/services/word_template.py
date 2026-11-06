"""Word template and signature service for the Fee Register (T5.2, design 8, R-SET-3, R-SET-8, R-EX).

One ``WordTemplate`` row per profile holds the uploaded ``.docx`` (``data``), the merged copy used for
rendering (``prepared``), the tag list (``tags``), and the optional signature image
(``signature_data``, ``signature_filename``, ``signature_content_type``). The binary columns are heavy,
so reads here use ``.defer`` for the ones not needed.

Public functions (every one takes ``profile`` first):

* ``upload_template(profile, filename, data)``: validates (2 MB before the zip is opened, a ``.docx``
  name, then ``template_prep.prepare`` for the zip limits and the tag check), stores ``data``,
  ``prepared`` and ``tags``, and replaces any earlier template. Failures are ``INVALID_TEMPLATE``.
* ``get_template_info(profile)``: a small dict (no bytes) for the settings page.
* ``download_template(profile)``: ``(filename, original_bytes)``; ``NO_TEMPLATE`` when none.
* ``upload_signature(profile, filename, content_type, data)``: validates type (png or jpg/jpeg) and
  size (2 MB) BEFORE the image is opened, then checks the header, and stores it, replacing any earlier
  one. Failures are ``INVALID_SIGNATURE`` (422).
* ``download_signature(profile)``: ``(filename, content_type, bytes)``; ``SIGNATURE_NOT_FOUND`` (404)
  when none.
* ``render_memo_docx(profile, memo_id)``: ``(file_name, TemporaryFile)`` for one memo, using the
  prepared template, the placeholder map and the memo file name pattern. Read only.

Each mutator runs in one ``transaction.atomic()`` and calls ``memos.touch(profile)`` once (R-DATA-6).
Payment data is never part of an export.
"""

import re

from django.db import transaction

from fees.errors import FeesError
from fees.exports import images, template_prep, word
from fees.exports.docx_zip import MAX_TEMPLATE_BYTES
from fees.exports.filenames import memo_export_filename
from fees.exports.placeholders import build_placeholder_map
from fees.models import FeesSettings, Memo, WordTemplate
from fees.services import memos

__all__ = [
    "MAX_SIGNATURE_BYTES",
    "MAX_TEMPLATE_BYTES",
    "download_signature",
    "download_template",
    "get_template_info",
    "render_memo_docx",
    "upload_signature",
    "upload_template",
]

#: A signature image is at most this many bytes (R-SET-8).
MAX_SIGNATURE_BYTES = 2 * 1024 * 1024

_MAX_FILENAME = 255
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
#: Accepted content types by family; browsers send ``image/jpg`` and ``image/pjpeg`` too.
_PNG_TYPES = {"image/png"}
_JPEG_TYPES = {"image/jpeg", "image/jpg", "image/pjpeg"}
_NEUTRAL_TYPES = {"", "application/octet-stream"}


def _clean_filename(filename):
    name = _CONTROL_CHARS.sub("", str(filename or "")).replace("\\", "/").rsplit("/", 1)[-1].strip()
    return name[:_MAX_FILENAME]


def _row(profile, defer=("data", "prepared", "signature_data")):
    row, _created = WordTemplate.objects.defer(*defer).get_or_create(profile=profile)
    return row


def _bytes(value):
    return bytes(value) if value is not None else b""


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------


def upload_template(profile, filename, data):
    """Validates and stores a template, replacing any earlier one; returns ``get_template_info``."""
    name = _clean_filename(filename)
    if not name.lower().endswith(".docx"):
        raise FeesError("INVALID_TEMPLATE", "The template must be a Word (.docx) file.")
    data = bytes(data)
    prepared, tags = template_prep.prepare(data)
    with transaction.atomic():
        row = _row(profile)
        row.filename = name
        row.data = data
        row.prepared = prepared
        row.tags = tags
        row.save(update_fields=["filename", "data", "prepared", "tags", "uploaded_at"])
        memos.touch(profile)
    return get_template_info(profile)


def get_template_info(profile):
    """The template and signature state as a dict with no bytes. Read only."""
    row = WordTemplate.objects.filter(profile=profile).defer(
        "data", "prepared", "signature_data"
    ).first()
    if row is None:
        return {
            "has_template": False,
            "filename": "",
            "tags": [],
            "uploaded_at": None,
            "has_signature": False,
            "signature_filename": "",
            "signature_content_type": "",
        }
    has_signature = (
        WordTemplate.objects.filter(pk=row.pk, signature_data__isnull=False)
        .exclude(signature_filename="")
        .exists()
    )
    has_template = bool(row.filename)
    return {
        "has_template": has_template,
        "filename": row.filename,
        "tags": list(row.tags or []),
        "uploaded_at": row.uploaded_at if has_template else None,
        "has_signature": has_signature,
        "signature_filename": row.signature_filename if has_signature else "",
        "signature_content_type": row.signature_content_type if has_signature else "",
    }


def download_template(profile):
    """``(filename, original_bytes)`` of the uploaded template, or ``NO_TEMPLATE``."""
    row = WordTemplate.objects.filter(profile=profile).defer("prepared", "signature_data").first()
    if row is None or row.data is None:
        raise FeesError("NO_TEMPLATE")
    return row.filename or "template.docx", _bytes(row.data)


# ---------------------------------------------------------------------------
# Signature
# ---------------------------------------------------------------------------


def _invalid_signature(message):
    return FeesError("INVALID_SIGNATURE", message)


def _check_signature(filename, content_type, data):
    """Type and size first (nothing is opened), then the header. Returns the cleaned values."""
    name = _clean_filename(filename)
    if len(data) == 0:
        raise _invalid_signature("The signature file is empty.")
    if len(data) > MAX_SIGNATURE_BYTES:
        raise _invalid_signature("The signature image is larger than 2 MB.")
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    kind = str(content_type or "").split(";", 1)[0].strip().lower()
    if extension == "png":
        family = _PNG_TYPES
    elif extension in ("jpg", "jpeg"):
        family = _JPEG_TYPES
    else:
        raise _invalid_signature("The signature must be a PNG or JPEG image.")
    if kind not in _NEUTRAL_TYPES and kind not in family:
        raise _invalid_signature("The signature must be a PNG or JPEG image.")
    info = images.inspect_image(data)
    if info is None:
        raise _invalid_signature("The signature file is not a readable PNG or JPEG image.")
    stored_type = info[0]
    if (stored_type == "image/png") != (family is _PNG_TYPES):
        raise _invalid_signature("The signature file does not match its extension.")
    return name, stored_type


def upload_signature(profile, filename, content_type, data):
    """Validates and stores the signature image, replacing any earlier one; returns the info dict."""
    data = bytes(data)
    name, stored_type = _check_signature(filename, content_type, data)
    with transaction.atomic():
        row = _row(profile)
        row.signature_data = data
        row.signature_filename = name
        row.signature_content_type = stored_type
        row.save(
            update_fields=["signature_data", "signature_filename", "signature_content_type"]
        )
        memos.touch(profile)
    return get_template_info(profile)


def download_signature(profile):
    """``(filename, content_type, bytes)`` of the signature, or ``SIGNATURE_NOT_FOUND``."""
    row = WordTemplate.objects.filter(profile=profile).defer("data", "prepared").first()
    if row is None or row.signature_data is None:
        raise FeesError("SIGNATURE_NOT_FOUND", "No signature image has been uploaded yet.")
    return row.signature_filename, row.signature_content_type, _bytes(row.signature_data)


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def _signature_of(row):
    """The ``word.Signature`` for ``row``, or ``None`` when no usable image is stored."""
    if row.signature_data is None:
        return None
    data = _bytes(row.signature_data)
    info = images.inspect_image(data)
    if info is None:
        return None
    content_type, extension, width, height = info
    return word.Signature(content_type, extension, data, width, height)


def render_memo_docx(profile, memo_id):
    """``(file_name, TemporaryFile)`` for one memo from the profile's template. Read only."""
    row = WordTemplate.objects.filter(profile=profile).defer("data").first()
    if row is None or row.prepared is None:
        raise FeesError("NO_TEMPLATE")
    detail = memos.get_memo(profile, memo_id)
    settings_row, _created = FeesSettings.objects.get_or_create(profile=profile)
    memo = Memo.objects.select_related("matter", "firm", "group").get(profile=profile, pk=memo_id)
    mapping = build_placeholder_map(detail, settings_row)
    rendered = word.render(_bytes(row.prepared), mapping, _signature_of(row))
    return memo_export_filename(memo, settings_row), rendered
