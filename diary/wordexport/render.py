"""Turns an ``ExportInput`` tree into a .docx (docs/DESIGN.md section 12). Pure Python, no Django.

Decisions recorded in D42 to D49 of docs/DESIGN.md. In short:

* Numbers are written as literal text from ``diary.numbering`` (never Word auto-numbering), with a tab and a
  hanging indent, so the file matches the screen exactly and survives editing. No full stop is added.
* One Word section per Subject: new page, Subject name in the page header.
* The contents page is a plain list of links (bookmarks), not a TOC field.
"""
from html.parser import HTMLParser

from .. import numbering
from ..richtext import sanitise_html
from . import docxwriter as dw
from .model import XSection, count_items

W = 567  # one step of indent (1 cm) and the width of a number
OTHER_SUBJECTS = "Other Subjects"
# Paragraph styles (ids in docxwriter.styles_xml); the round-trip check reads them back.
S_H1, S_H2, S_H3 = "Heading1", "Heading2", "Heading3"
S_SUBTOPIC, S_SECTION, S_ITEM, S_BULLET = "DiarySubtopic", "DiarySection", "DiaryItem", "DiaryBullet"
S_NOTE, S_SEE_ALSO, S_CONTENTS = "DiaryNote", "DiarySeeAlso", "DiaryContents"


class _RunParser(HTMLParser):
    """Sanitised rich text (p, br, b, i, u) -> runs. Several paragraphs become line breaks inside one Word paragraph."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.runs = []
        self.depth = {"b": 0, "i": 0, "u": 0}
        self.seen_paragraph = False

    def _add(self, text):
        run = dw.Run(text, self.depth["b"] > 0, self.depth["i"] > 0, self.depth["u"] > 0)
        if self.runs and self.runs[-1].key() == run.key():
            self.runs[-1].text += text
        else:
            self.runs.append(run)

    def handle_starttag(self, tag, attrs):
        if tag in self.depth:
            self.depth[tag] += 1
        elif tag == "br":
            self._add("\n")
        elif tag == "p":
            if self.seen_paragraph:
                self._add("\n")
            self.seen_paragraph = True

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self._add("\n")

    def handle_endtag(self, tag):
        if tag in self.depth:
            self.depth[tag] = max(0, self.depth[tag] - 1)

    def handle_data(self, data):
        if data:
            self._add(data)


def html_runs(html, **extra):
    """Runs for stored rich text. Trailing line breaks are dropped; ``extra`` (e.g. italic=True) is added to every run."""
    parser = _RunParser()
    parser.feed(sanitise_html(html or ""))
    parser.close()
    runs = parser.runs
    while runs and not runs[-1].text.strip("\n"):
        runs.pop()
    if runs:
        runs[-1].text = runs[-1].text.rstrip("\n")
    for run in runs:
        for key, value in extra.items():
            setattr(run, key, getattr(run, key) or value)
    return runs


def has_text(html):
    return any(r.text.strip() for r in html_runs(html))


class Renderer:
    def __init__(self, data):
        self.data = data
        self.fmts = data.fmts
        self.review = data.include_review
        self.doc = dw.Document(f"{data.title} {data.part}".strip(), data.created)
        self.bookmarks = 0
        self.contents = []  # (level, name, bookmark)
        # A document with a single Subject (or a Current View) also lists the headings one level down.
        self.detail = (len(data.main) == 1 and not data.others) or data.view_topic is not None \
            or data.view_subtopic is not None

    # -- small helpers ------------------------------------------------------------------------------
    def bookmark(self):
        self.bookmarks += 1
        return f"toc_{self.bookmarks}"

    def labelled(self, style, label, runs, pos, **kw):
        """A paragraph: number (literal text), a tab, then the content. The label sits at ``pos``, the text at ``pos + W``."""
        lead = [dw.Run(label, bold=kw.pop("bold_label", False)), dw.Run(tab=True)]
        return dw.Para(style, lead + runs, left=pos + W, hanging=W, **kw)

    def review_runs(self, needs_review, note):
        if not (self.review and needs_review):
            return []
        return [dw.Run(" [For review" + (f": {note}" if note else "") + "]", color=dw.AMBER)]

    # -- notes ------------------------------------------------------------------------------------
    def emit_notes(self, notes, left):
        for note in notes:
            if has_text(note.html):
                self.doc.add(dw.Para(S_NOTE, html_runs(note.html), left=left))
            for link in note.links:
                text = f"See also: {link.path}" + (" (target deleted)" if link.deleted else "")
                self.doc.add(dw.Para(S_SEE_ALSO, [dw.Run(text)], left=left))

    # -- items ------------------------------------------------------------------------------------
    def item_runs(self, item):
        runs = html_runs(item.html)
        has = bool(runs) and any(r.text.strip() for r in runs)
        if item.cases:
            if has:
                runs.append(dw.Run(" - "))
            labels = (numbering.number_siblings(len(item.cases), self.fmts["multi_citation_format"])
                      if len(item.cases) > 1 else [""] * len(item.cases))
            for n, (label, case) in enumerate(zip(labels, item.cases)):
                if n:
                    runs.append(dw.Run(" ; "))
                if label:
                    runs.append(dw.Run(label + " "))
                runs.append(dw.Run(case.citation, italic=True))
                if has_text(case.comment_html):
                    runs.append(dw.Run(" "))
                    runs.extend(html_runs(case.comment_html))
        elif item.citation:
            if has:
                runs.append(dw.Run(" - "))
            runs.append(dw.Run(item.citation, italic=True))
        if item.flag_label:
            runs.append(dw.Run(f" [{item.flag_label}]", color=dw.RED))
        runs.extend(self.review_runs(item.needs_review, item.review_note))
        return runs

    def emit_item(self, item, label, pos, child=False):
        self.doc.add(self.labelled(S_BULLET if child else S_ITEM, label, self.item_runs(item), pos))
        self.emit_notes(item.notes, pos + W)
        if item.children:
            labels = numbering.number_siblings(len(item.children), self.fmts["nested_item_format"])
            for kid, kid_label in zip(item.children, labels):
                self.emit_item(kid, kid_label, pos + W, child=True)

    def emit_container(self, container, base):
        """Items and Sections in manual order (Sections numbered, Items restarting after each), then the Notes."""
        kinds = [numbering.SECTION if isinstance(e, XSection) else (numbering.NESTED if e.is_nested else numbering.ITEM)
                 for e in container.entries]
        labels = numbering.number_children(kinds, self.fmts["item_format"], self.fmts["section_format"])
        under_section = False
        for entry, kind, label in zip(container.entries, kinds, labels):
            if kind == numbering.SECTION:
                under_section = True
                runs = [dw.Run(entry.name, bold=True)] if entry.name else []
                runs += self.review_runs(entry.needs_review, entry.review_note)
                self.doc.add(self.labelled(S_SECTION, label, runs, base, bold_label=True))
                self.emit_notes(entry.notes, base + W)
            else:
                self.emit_item(entry, label, base + (W if under_section else 0))
        self.emit_notes(container.notes, base)

    # -- headings ---------------------------------------------------------------------------------
    def heading(self, style, name, label="", bookmark="", listed=False):
        if label:
            para = self.labelled(style, label, [dw.Run(name)], 0)
        else:
            para = dw.Para(style, [dw.Run(name)])
        para.bookmark = bookmark
        self.doc.add(para)
        if listed:
            self.note_detail(label, name, para)

    def note_detail(self, label, name, para):
        """Add a bookmark to ``para`` and list it on the contents page (single-Subject documents and Current Views)."""
        if self.detail:
            para.bookmark = self.bookmark()
            self.contents.append((2, (f"{label} " if label else "") + name, para.bookmark))

    def emit_subtopic(self, sub, label, pos, listed=False):
        runs = [dw.Run(sub.name, bold=True)]
        para = self.doc.add(self.labelled(S_SUBTOPIC, label, runs, pos, bold_label=True))
        if listed:
            self.note_detail(label, sub.name, para)
        self.emit_container(sub.container, pos + W)

    def emit_topic_body(self, topic):
        """The Topic's own Items first, then its Sub-topics."""
        self.emit_container(topic.container, W)
        labels = numbering.number_siblings(len(topic.subtopics), self.fmts["subtopic_format"])
        for sub, label in zip(topic.subtopics, labels):
            self.emit_subtopic(sub, label, W)

    def emit_subject_body(self, subject, topic_style):
        self.emit_container(subject.container, 0)
        labels = numbering.number_siblings(len(subject.topics), self.fmts["topic_format"])
        for topic, label in zip(subject.topics, labels):
            self.heading(topic_style, topic.name, label, listed=True)
            self.emit_topic_body(topic)
        sub_labels = numbering.number_siblings(len(subject.subtopics), self.fmts["subtopic_format"])
        for sub, label in zip(subject.subtopics, sub_labels):
            self.emit_subtopic(sub, label, 0, listed=True)

    # -- whole document ---------------------------------------------------------------------------
    def build(self):
        data = self.data
        front = self.doc.new_section(data.title)
        self.doc.add(dw.Para("Title", [dw.Run(data.title)]))
        self.doc.add(dw.Para("Subtitle", [dw.Run(data.part)]))
        if data.path:
            self.doc.add(dw.Para("Normal", [dw.Run("On screen: " + " > ".join(data.path))]))
        total = count_items(data)
        self.doc.add(dw.Para("Normal", [dw.Run(f"Exported {data.date_text}. Records in this document: {total} "
                                               f"Item{'' if total == 1 else 's'}.")]))
        marks = "included" if self.review else "not included"
        self.doc.add(dw.Para("Normal", [dw.Run(f"Review markers: {marks}.")]))
        self.doc.add(dw.Para("ContentsHeading", [dw.Run("Contents")]))
        contents_at = len(front.paras)  # the list is filled in after the body, when every bookmark is known

        for subject in data.main:
            mark = self.bookmark()
            self.doc.new_section(" > ".join(data.path) if data.path else subject.name)
            self.heading(S_H1, subject.name, bookmark=mark)
            self.contents.append((1, subject.name, mark))
            self.emit_subject_body(subject, S_H2)
        if data.others:
            mark = self.bookmark()
            self.doc.new_section(OTHER_SUBJECTS)
            self.heading(S_H1, OTHER_SUBJECTS, bookmark=mark)
            self.contents.append((1, OTHER_SUBJECTS, mark))
            group_entries = []
            for subject in data.others:
                group_entries.append((subject, self.bookmark()))
            for subject, sub_mark in group_entries:
                self.doc.add(dw.Para(S_CONTENTS, [dw.Run(subject.name, anchor=sub_mark)], left=W))
            for subject, sub_mark in group_entries:
                self.doc.new_section(f"{OTHER_SUBJECTS}: {subject.name}")
                self.heading(S_H2, subject.name, bookmark=sub_mark)
                self.contents.append((2, subject.name, sub_mark))
                self.emit_subject_body(subject, S_H3)
        if data.view_topic is not None:
            self.emit_view_topic(data.view_topic)
        if data.view_subtopic is not None:
            self.emit_view_subtopic(data.view_subtopic)

        entries = [dw.Para(S_CONTENTS, [dw.Run(name, anchor=mark)], left=(level - 1) * W)
                   for level, name, mark in self.contents]
        front.paras[contents_at:contents_at] = entries
        return self.doc.to_bytes()

    def emit_view_topic(self, topic):
        mark = self.bookmark()
        label = numbering.format_number(topic.index, self.fmts["topic_format"])
        self.doc.new_section(" > ".join(self.data.path) or topic.name)
        self.heading(S_H1, topic.name, label, bookmark=mark)
        self.contents.append((1, (f"{label} " if label else "") + topic.name, mark))
        self.emit_container(topic.container, 0)
        labels = numbering.number_siblings(len(topic.subtopics), self.fmts["subtopic_format"])
        for sub, sub_label in zip(topic.subtopics, labels):
            self.emit_subtopic(sub, sub_label, 0, listed=True)

    def emit_view_subtopic(self, sub):
        mark = self.bookmark()
        label = numbering.format_number(sub.index, self.fmts["subtopic_format"])
        self.doc.new_section(" > ".join(self.data.path) or sub.name)
        self.heading(S_H1, sub.name, label, bookmark=mark)
        self.contents.append((1, (f"{label} " if label else "") + sub.name, mark))
        self.emit_container(sub.container, 0)


def render(data):
    """The bytes of the .docx for ``data`` (an ``ExportInput``)."""
    return Renderer(data).build()
