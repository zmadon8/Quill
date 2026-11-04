"""The three Word exports of docs/DESIGN.md section 12: Full, Full by Subject (a .zip) and Current View.

Every function works inside one profile and takes the user only for their number formats, date format and
time zone (My settings). Permissions are checked by the views.
"""
import io
import zipfile
from dataclasses import dataclass

from django.utils import timezone

from accounts.profiles import effective_export_name, export_file_name

from .. import reading
from . import gather, naming
from . import model as m
from .render import OTHER_SUBJECTS, render

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
ZIP_TYPE = "application/zip"

FULL, BY_SUBJECT, VIEW = "full", "by_subject", "view"


class ExportError(Exception):
    """The export cannot be made (for example the Subject is gone). The message is plain English."""


@dataclass
class ExportFile:
    name: str
    data: bytes
    content_type: str
    items: int  # Items in the whole file (all documents of a zip)
    documents: int = 1

    @property
    def size(self):
        return len(self.data)


def user_options(user):
    """(number formats, date format, time zone) from the user's My settings, standard values if none are saved."""
    settings = getattr(user, "diary_settings", None) if user is not None and getattr(user, "pk", None) else None
    date_format = settings.export_date_format if settings is not None else "YYYY-MM-DD"
    zone = settings.time_zone if settings is not None else naming.DEFAULT_ZONE
    return reading.formats_for(user), date_format, zone


def _context(profile, user, now):
    fmts, date_format, zone = user_options(user)
    now = now or timezone.now()
    return {
        "fmts": fmts,
        # The title is the name as typed; file names use the cleaned name with the same fallbacks as the Settings preview.
        "export_name": effective_export_name(profile),
        "file_export_name": export_file_name(profile),
        "date_text": naming.format_date(naming.today(now, zone), date_format),
        "created": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _input(ctx, part, include_review, **kw):
    return m.ExportInput(title=ctx["export_name"], part=part, date_text=ctx["date_text"], fmts=ctx["fmts"],
                         include_review=include_review, created=ctx["created"], **kw)


def file_name_preview(profile, user, now=None):
    """Example file names for the Export page and the settings preview: {kind: name}."""
    ctx = _context(profile, user, now)
    name = ctx["file_export_name"]
    date = ctx["date_text"]
    return {
        FULL: naming.build_name(name, ["Full"], date, "docx"),
        BY_SUBJECT: naming.build_name(name, ["Full - by Subject"], date, "zip"),
        "example_subject": naming.build_name(name, ["Arbitration"], date, "docx"),
        "example_view": naming.build_name(name, ["Arbitration", "Fraud"], date, "docx"),
    }


def view_file_name(profile, user, path, now=None):
    """The file name of a Current View of ``path`` (Subject, Topic, Sub-topic names), for the Export page."""
    ctx = _context(profile, user, now)
    return naming.build_name(ctx["file_export_name"], path, ctx["date_text"], "docx")


def full(profile, user, include_review=False, now=None, snapshot=None):
    """(i) The whole diary in one document."""
    ctx = _context(profile, user, now)
    snap = snapshot or gather.load(profile)
    data = _input(ctx, "Full", include_review, main=snap.main, others=snap.others)
    name = naming.build_name(ctx["file_export_name"], ["Full"], ctx["date_text"], "docx")
    return ExportFile(name, render(data), DOCX_TYPE, m.count_items(data))


def by_subject(profile, user, include_review=False, now=None, snapshot=None):
    """(ii) One document per main Subject plus one for all Other Subjects, in one .zip with manifest.txt."""
    ctx = _context(profile, user, now)
    snap = snapshot or gather.load(profile)
    taken = set()
    files = []  # (name, bytes, items, label)
    for subject in snap.main:
        data = _input(ctx, subject.name, include_review, main=[subject])
        name = naming.build_name(ctx["file_export_name"], [subject.name], ctx["date_text"], "docx", taken)
        files.append((name, render(data), m.count_items(data), subject.name))
    if snap.others:
        data = _input(ctx, OTHER_SUBJECTS, include_review, others=snap.others)
        name = naming.build_name(ctx["file_export_name"], [OTHER_SUBJECTS], ctx["date_text"], "docx", taken)
        files.append((name, render(data), m.count_items(data), OTHER_SUBJECTS))
    total = sum(f[2] for f in files)
    lines = [
        f"{ctx['export_name']}: Full, one document per Subject",
        f"Exported {ctx['date_text']}. Flags: {'included' if include_review else 'not included'}.",
        "Records are Items at every depth (the figure shown beside each Subject).",
        "",
    ]
    lines += [f"{name}: {count} Item{'' if count == 1 else 's'}" for name, _data, count, _label in files]
    lines += ["", f"Total: {total} Item{'' if total == 1 else 's'} in {len(files)} document{'' if len(files) == 1 else 's'}."]
    manifest = "\n".join(lines) + "\n"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:  # the .docx files are already compressed
        for name, data, _count, _label in files:
            info = zipfile.ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0))
            archive.writestr(info, data)
        archive.writestr(zipfile.ZipInfo("manifest.txt", date_time=(2000, 1, 1, 0, 0, 0)), manifest.encode("utf-8"))
    zip_name = naming.build_name(ctx["file_export_name"], ["Full - by Subject"], ctx["date_text"], "zip")
    return ExportFile(zip_name, buffer.getvalue(), ZIP_TYPE, total, documents=len(files))


def scope_path(profile, kind, pk):
    """The on-screen path (names) of a live Subject, Topic or Sub-topic of ``profile`` using three light queries; ExportError if absent."""
    from ..models import Subject, Subtopic, Topic

    live = {"profile": profile, "deleted_at__isnull": True}
    if kind == "subject":
        row = Subject.objects.filter(pk=pk, **live).first()
        if row is not None:
            return [row.name]
    elif kind == "topic":
        row = Topic.objects.filter(pk=pk, subject__deleted_at__isnull=True, **live).select_related("subject").first()
        if row is not None:
            return [row.subject.name, row.name]
    elif kind == "subtopic":
        row = Subtopic.objects.filter(pk=pk, **live).select_related("subject", "topic__subject").first()
        if row is not None:
            if row.topic_id and row.topic.deleted_at is None and row.topic.subject.deleted_at is None:
                return [row.topic.subject.name, row.topic.name, row.name]
            if row.subject_id and row.subject.deleted_at is None:
                return [row.subject.name, row.name]
    raise ExportError("That is not in this profile (or is in Trash).")


def view_scope(profile, kind, pk, snapshot=None):
    """(path names, the tree pieces) of a Subject, Topic or Sub-topic of ``profile``; ExportError if it is not there."""
    snap = snapshot or gather.load(profile)
    if kind == "subject":
        found = snap.subjects.get(pk)
        if found is None:
            raise ExportError("That Subject is not in this profile (or is in Trash).")
        return [found.name], {"main": [found]}
    if kind == "topic":
        found = snap.topics.get(pk)
        if found is None:
            raise ExportError("That Topic is not in this profile (or is in Trash).")
        topic, subject = found
        return [subject.name, topic.name], {"view_topic": topic}
    if kind == "subtopic":
        found = snap.subtopics.get(pk)
        if found is None:
            raise ExportError("That Sub-topic is not in this profile (or is in Trash).")
        sub, topic_id, subject = found
        path = [subject.name] + ([snap.topics[topic_id][0].name] if topic_id else []) + [sub.name]
        return path, {"view_subtopic": sub}
    raise ExportError("Choose a Subject, a Topic or a Sub-topic.")


def current_view(profile, user, kind, pk, include_review=False, now=None, snapshot=None):
    """(iii) What is on the screen: a Subject, Topic or Sub-topic with everything below it. Its heading is Heading 1."""
    ctx = _context(profile, user, now)
    path, pieces = view_scope(profile, kind, pk, snapshot)
    data = _input(ctx, ", ".join(path), include_review, path=path, **pieces)
    name = view_file_name(profile, user, path, now)
    return ExportFile(name, render(data), DOCX_TYPE, m.count_items(data))


def roundtrip(profile, original_bytes, now=None):
    """Export ``profile`` in full (standard number formats, no flags) and compare it with the original Word file.

    Returns a ``roundtrip.RoundTrip`` (``.text`` is the plain report, ``.unexpected`` lists real differences).
    """
    from . import roundtrip as check

    exported = full(profile, None, include_review=False, now=now)
    return check.check(original_bytes, exported.data)
