"""The Offline copy: the whole diary as ONE self-contained, read-only .html file (docs/DESIGN.md D98).

Pure Python, no Django: it turns the same neutral tree the Word export uses (``model.ExportInput``) into HTML text.
The file has its own style sheet and script inside it (no request to any server), looks like the website's reading
pages (Subjects page, Contents, Topics, Sub-topics, Items, citations, flags, hyperlinks) and has a search box that
runs in the reader's browser. Nothing in it can change the diary, and no edit controls are written.

Every piece of text from the diary is escaped, except rich text, which goes through ``richtext.sanitise_html`` (only
p, br, b, i, u). A citation's web address becomes a link only if it starts with http:// or https://.
"""
import re
from html import escape
from pathlib import Path

from .. import numbering
from ..richtext import sanitise_html
from .model import XSection, count_items

OTHER_SUBJECTS = "Other Subjects"
_ASSETS = Path(__file__).parent / "offline_assets"


def _asset(name):
    return (_ASSETS / name).read_text(encoding="utf-8")


def _e(text):
    return escape(text or "", quote=True)


def _safe_url(url):
    url = (url or "").strip()
    return url if url.lower().startswith(("http://", "https://")) and not any(c in url for c in " <>\"'\n\r\t") else ""


def _plain_has_text(html):
    import re

    return bool(re.sub(r"<[^>]*>", "", sanitise_html(html or "")).strip())


def anchor(kind, pk):
    return f"{kind}-{pk}"


class _Builder:
    def __init__(self, data):
        self.data = data
        self.fmts = data.fmts
        self.review = data.include_review
        self.out = []
        self.path = []

    # -- small pieces -----------------------------------------------------------------------------
    def flag(self, label, key):
        if not (self.review and label):
            return ""
        return f' <span class="flag-text flag-{_e(key or "other")}">[{_e(label)}]</span>'

    def link_html(self, link):
        if link.deleted or not link.ref:
            # The target is in Trash: the offline file holds live data only, so its path (which names the trashed
            # Item) is not written; it only says that the target was deleted.
            return '<div class="see-also">See also: (target deleted)</div>'
        return f'<div class="see-also">See also: <a href="#{_e(link.ref)}">{_e(link.path)}</a></div>'

    def notes(self, notes):
        parts = []
        for note in notes:
            body = sanitise_html(note.html or "") if _plain_has_text(note.html) else ""
            links = "".join(self.link_html(link) for link in note.links)
            if body or links:
                parts.append(f'<div class="note">{body}{links}</div>')
        return "".join(parts)

    def citation(self, case):
        url = _safe_url(case.url)
        if url:
            return (f'<a class="cite-link" href="{_e(url)}" target="_blank" rel="noopener noreferrer">'
                    f'<em class="citation">{_e(case.citation or url)}</em></a>')
        return f'<em class="citation">{_e(case.citation)}</em>' if case.citation else ""

    def comment(self, case):
        return sanitise_html(case.comment_html) if _plain_has_text(case.comment_html) else ""

    # -- items ------------------------------------------------------------------------------------
    def item(self, item, label, indented):
        text = sanitise_html(item.html) if _plain_has_text(item.html) else ""
        lines = len(item.cases) > 1 and item.layout == "lines"
        colon = ""
        if text and lines and not re.sub(r"<[^>]*>", "", text).rstrip().endswith(":"):
            colon = '<span class="item-colon">:</span>'  # the citations follow on their own lines
        body = [f'<span class="item-text">{text}{colon}</span>' if text else ""]
        labels = numbering.number_siblings(len(item.cases), self.fmts["multi_citation_format"]) if len(item.cases) > 1 \
            else [""] * len(item.cases)
        if item.cases and lines:
            rows = []
            for case_label, case in zip(labels, item.cases):
                comment = self.comment(case)
                cite = self.citation(case)
                joined = f'<span class="case-line-comment">{comment}</span>' if comment else ""
                if comment and cite:
                    joined += " - "
                rows.append(f'<div class="case-line"><span class="num">{_e(case_label)}</span>'
                            f'<span class="case-line-body">{joined}{cite}</span></div>')
            body.append('<div class="case-lines">' + "".join(rows) + "</div>")
        elif item.cases:
            pieces = []
            for case_label, case in zip(labels, item.cases):
                comment = self.comment(case)
                pieces.append('<span class="case">' + (f'<span class="num">{_e(case_label)}</span> ' if case_label else "")
                              + self.citation(case) + (f' <span class="case-comment">{comment}</span>' if comment else "")
                              + "</span>")
            body.append((" - " if text else "") + " ".join(pieces))
        body.append(self.flag(item.flag_label, item.flag))
        body.append(self.notes(item.notes))
        where = " > ".join(self.path)
        self.out.append(
            f'<div class="item{" under-section" if indented else ""}" id="{anchor("item", item.pk)}" data-find '
            f'data-where="{_e(where)}"><span class="num">{_e(numbering.display_label(label))}</span>'
            f'<div class="item-body">{"".join(body)}</div></div>')

    def container(self, container, indent=False):
        kinds = [numbering.SECTION if isinstance(e, XSection) else numbering.ITEM for e in container.entries]
        labels = numbering.number_children(kinds, self.fmts["item_format"], self.fmts["section_format"])
        under_section = False
        for entry, kind, label in zip(container.entries, kinds, labels):
            if kind == numbering.SECTION:
                under_section = True
                name = f" {_e(entry.name)}" if entry.name else ""
                self.out.append(
                    f'<div class="section-header" id="{anchor("section", entry.pk)}" data-find '
                    f'data-where="{_e(" > ".join(self.path))}"><span class="num">{_e(numbering.display_label(label))}</span>'
                    f'{name}{self.flag(entry.flag_label, entry.flag)}</div>{self.notes(entry.notes)}')
            else:
                self.item(entry, label, under_section)
        self.out.append(self.notes(container.notes))

    # -- headings ---------------------------------------------------------------------------------
    def subtopic(self, sub, label, tag="h3"):
        self.path.append(sub.name)
        self.out.append(f'<{tag} class="subtopic-heading" id="{anchor("subtopic", sub.pk)}" data-find '
                        f'data-where="{_e(" > ".join(self.path[:-1]))}"><span class="num">'
                        f'{_e(numbering.display_label(label))}</span> {_e(sub.name)}</{tag}>')
        self.container(sub.container)
        self.path.pop()

    def subject_view(self, subject, heading):
        """One Subject: its Contents, then everything in it. ``heading`` is the Subject's name as shown."""
        self.path = [subject.name]
        topic_labels = numbering.number_siblings(len(subject.topics), self.fmts["topic_format"])
        sub_labels = numbering.number_siblings(len(subject.subtopics), self.fmts["subtopic_format"])
        self.out.append(f'<section class="view" id="{anchor("subject", subject.pk)}">'
                        '<p><a class="back" href="#">Back to Subjects</a></p>'
                        f'<h1 data-find id="{anchor("subject-title", subject.pk)}" data-where="">{_e(heading)}</h1>')
        contents = []
        for topic, label in zip(subject.topics, topic_labels):
            contents.append(f'<li><a href="#{anchor("topic", topic.pk)}">{_e(numbering.display_label(label))} {_e(topic.name)}</a></li>')
            for sub, sub_label in zip(topic.subtopics, numbering.number_siblings(len(topic.subtopics), self.fmts["subtopic_format"])):
                contents.append(f'<li class="l2"><a href="#{anchor("subtopic", sub.pk)}">{_e(numbering.display_label(sub_label))} {_e(sub.name)}</a></li>')
        for sub, label in zip(subject.subtopics, sub_labels):
            contents.append(f'<li><a href="#{anchor("subtopic", sub.pk)}">{_e(numbering.display_label(label))} {_e(sub.name)}</a></li>')
        if contents:
            self.out.append('<h2>Contents</h2><ul class="contents">' + "".join(contents) + "</ul>")
        self.container(subject.container)
        for topic, label in zip(subject.topics, topic_labels):
            self.path = [subject.name, topic.name]
            self.out.append(f'<h2 class="topic-heading" id="{anchor("topic", topic.pk)}" data-find '
                            f'data-where="{_e(subject.name)}"><span class="num">{_e(numbering.display_label(label))}</span> {_e(topic.name)}</h2>')
            self.container(topic.container)
            sub_labels_t = numbering.number_siblings(len(topic.subtopics), self.fmts["subtopic_format"])
            for sub, sub_label in zip(topic.subtopics, sub_labels_t):
                self.subtopic(sub, sub_label)
            self.path = [subject.name]
        for sub, label in zip(subject.subtopics, sub_labels):
            self.path = [subject.name]
            self.subtopic(sub, label, "h2")
        self.out.append("</section>")

    def subject_list(self, subjects):
        rows = []
        for subject in subjects:
            n = count_items(subject)
            rows.append(f'<li><a href="#{anchor("subject", subject.pk)}">{_e(subject.name)}</a> '
                        f'<span class="count">({n} Item{"" if n == 1 else "s"})</span></li>')
        return '<ul class="plain">' + "".join(rows) + "</ul>"

    def single_view(self, data):
        """A Topic or a Sub-topic on its own: the home page of the file is that page (no list of Subjects)."""
        path = data.path or []
        self.path = list(path[:-1])
        if data.view_topic is not None:
            topic = data.view_topic
            label = numbering.format_number(topic.index, self.fmts["topic_format"])
            tag, thing = "h1", topic
        else:
            topic = data.view_subtopic
            label = numbering.format_number(topic.index, self.fmts["subtopic_format"])
            tag, thing = "h1", topic
        kind = "topic" if data.view_topic is not None else "subtopic"
        self.out.append(f'<{tag} id="{anchor(kind, thing.pk)}" data-find data-where="{_e(" > ".join(path[:-1]))}">'
                        f'<span class="num">{_e(numbering.display_label(label))}</span> {_e(thing.name)}</{tag}>')
        self.path = list(path)
        self.container(thing.container)
        if data.view_topic is not None:
            sub_labels = numbering.number_siblings(len(thing.subtopics), self.fmts["subtopic_format"])
            for sub, sub_label in zip(thing.subtopics, sub_labels):
                self.path = list(path)
                self.subtopic(sub, sub_label, "h2")

    def build(self):
        data = self.data
        total = count_items(data)
        title = _e(data.title)
        flags = "included" if self.review else "not included"
        if data.view_topic is not None or data.view_subtopic is not None:
            self.single_view(data)
            head = (f'<section class="view on" id="home"><p class="meta">{title}. On screen: {_e(" > ".join(data.path))}. '
                    f'Offline copy, read-only. Made on {_e(data.date_text)}. {total} Item{"" if total == 1 else "s"}. '
                    f"Flags: {flags}.</p>")
            body = head + "".join(self.out) + "</section>"
            return self.page(title, body)
        home = ['<section class="view on" id="home">', f"<h1>{title}</h1>",
                f'<p class="meta">Offline copy, read-only. Made on {_e(data.date_text)}. {total} Item{"" if total == 1 else "s"}. '
                f"Flags: {flags}. To get newer changes, download a new copy from the Export page.</p>",
                "<h2>Subjects</h2>"]
        home.append(self.subject_list(data.main) if data.main else '<p class="meta">There are no Subjects yet.</p>')
        if data.others:
            home += [f"<h2>{OTHER_SUBJECTS}</h2>", self.subject_list(data.others)]
        home.append("</section>")
        for subject in data.main + data.others:
            self.subject_view(subject, subject.name)
        body = "".join(home) + "".join(self.out) + '<section class="view" id="results"></section>'
        return self.page(title, body)

    def page(self, title, body):
        if 'id="results"' not in body:
            body += '<section class="view" id="results"></section>'
        return (
            '<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{title} (offline copy)</title><style>{_asset('offline.css')}</style></head><body>"
            f'<header class="top"><div class="bar"><span class="title"><a href="#">{title}</a></span>'
            '<form class="search" id="search-form" role="search"><label class="meta" for="q" style="display:none">Search</label>'
            '<input type="search" id="q" placeholder="Search this copy" autocomplete="off">'
            '<button type="submit">Search</button></form></div></header>'
            f"<main>{body}</main>"
            f"<script>{_asset('offline.js')}</script></body></html>\n"
        )


def build_html(data):
    """The Offline copy of ``data`` (an ``ExportInput`` with ``main`` and ``others``) as a str."""
    return _Builder(data).build()
