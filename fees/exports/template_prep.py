"""Upload-time preparation of a Word template (design 8.1, port of ``scripts/templateTags.mjs``).

``prepare(data)`` returns ``(prepared_bytes, tags)``. It opens the ``.docx`` as a zip under the limits in
``docx_zip`` (200 entries, 20 MB uncompressed, 2 MB upload), merges every tag Word split across runs in
``word/document.xml``, ``word/header*.xml`` and ``word/footer*.xml``, renames long tags to short ones
(``convert_template_xml``), collects the tags, refuses any unknown tag, and writes a new zip with the
merged parts. Every other part is streamed across unchanged. Stdlib only.

``convert_template_xml`` is the Python form of ``convertTemplateXml``. One change from the JavaScript
regex: the inner group is ``(?:[^{}<]|<[^>]*>)*?`` rather than ``(?:[^{}]|<[^>]*>)*?``. The original lets
``<`` match both branches, which can backtrack exponentially on hostile input; excluding it from the
first branch matches the same well-formed XML and removes that risk.
"""

import io
import re
import zipfile

from fees.errors import FeesError
from fees.exports import docx_zip
from fees.exports.placeholders import is_known_tag, short_tag

#: The parts whose text may carry tags.
MERGE_PART = re.compile(r"^word/(document|header\d*|footer\d*)\.xml$")

_TAG_SPLIT = re.compile(r"\{(?:<[^>]*>)*\{((?:[^{}<]|<[^>]*>)*?)\}(?:<[^>]*>)*\}")
_XML_TAG = re.compile(r"<[^>]*>")
_FOUND_TAG = re.compile(r"\{\{([^{}<>]*)\}\}")
_MAX_UNKNOWN_SHOWN = 20


def _loose(word):
    """A regex fragment matching ``word`` even when XML tags split its letters."""
    return "(?:<[^>]*>)*".join(re.escape(ch) for ch in word)


_FOLD_APPEARANCES = re.compile(r"(\{\{)L16(\}\})(?:<[^>]*>|\s)*" + _loose("Appearances"))
_FOLD_CONFERENCES = re.compile(r"(\{\{)L19(\}\})(?:<[^>]*>|\s)*" + _loose("Conferences"))


def convert_template_xml(xml):
    """Merges split tags, shortens long names, and folds the plural words into ``L16W``/``L19W``."""
    out = _TAG_SPLIT.sub(lambda m: "{{" + short_tag(_XML_TAG.sub("", m.group(1))) + "}}", xml)
    out = _FOLD_APPEARANCES.sub(r"\1L16W\2", out)
    out = _FOLD_CONFERENCES.sub(r"\1L19W\2", out)
    return out


def find_tags(xml):
    """The distinct tag names (whitespace trimmed, section prefix kept) found in merged ``xml``."""
    return {m.group(1).strip() for m in _FOUND_TAG.finditer(xml)}


def _invalid(message, details=None):
    return FeesError("INVALID_TEMPLATE", message, details=details)


def prepare(data):
    """Validates and merges a template; returns ``(prepared_bytes, sorted_tag_list)``.

    Raises ``FeesError("INVALID_TEMPLATE")`` for an oversize file (checked before the zip is opened), a
    file that is not a readable ``.docx``, a zip over the limits, a missing ``word/document.xml``, or a
    tag that is not in the accepted set (the unknown names are listed in ``details``).
    """
    data = bytes(data)
    if len(data) > docx_zip.MAX_TEMPLATE_BYTES:
        raise _invalid("The Word template is larger than 2 MB.")
    try:
        zf = docx_zip.open_zip(data)
    except docx_zip.DocxError as exc:
        raise _invalid(exc.message) from None
    budget = docx_zip.Budget()
    tags = set()
    out_buffer = io.BytesIO()
    try:
        names = {info.filename for info in zf.infolist()}
        if "word/document.xml" not in names:
            raise _invalid("The file is not a Word template (word/document.xml is missing).")
        with zipfile.ZipFile(out_buffer, "w", zipfile.ZIP_DEFLATED) as out:
            for info in zf.infolist():
                if info.filename.endswith("/"):
                    continue
                if MERGE_PART.match(info.filename):
                    raw = docx_zip.read_part(zf, info, budget)
                    try:
                        text = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        raise _invalid("A part of the Word template is not valid text.") from None
                    text = convert_template_xml(text)
                    tags |= find_tags(text)
                    out.writestr(docx_zip.new_info(info), text.encode("utf-8"))
                else:
                    docx_zip.copy_part(zf, info, out, budget)
    except docx_zip.DocxError as exc:
        raise _invalid(exc.message) from None
    finally:
        zf.close()
    unknown = sorted(name for name in tags if not is_known_tag(name))
    if unknown:
        shown = unknown[:_MAX_UNKNOWN_SHOWN]
        raise _invalid(
            "The Word template uses tags that are not recognised: " + ", ".join(
                "{{" + name + "}}" for name in shown
            ),
            details={"unknown_tags": shown},
        )
    return out_buffer.getvalue(), sorted(tags)
