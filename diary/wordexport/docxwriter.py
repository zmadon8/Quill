"""A small .docx writer (standard library only: zipfile and hand-built WordprocessingML).

Why not python-docx: the project's reader is standard-library only, the export needs exact control of
styles, literal numbers, hanging indents and one Word section (with its own page header) per Subject,
and python-docx could not be installed or tested where this was written. See docs/DESIGN.md, D42.

Model: a ``Document`` holds ``Section`` objects; each Section has a page-header text and a list of
``Para`` objects; each Para has ``Run`` objects. A Section starts on a new page.
"""
import io
import re
import zipfile
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS = f'xmlns:w="{NS_W}" xmlns:r="{NS_R}"'
_XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'

#: Characters XML 1.0 cannot carry (everything below space except tab, line feed and carriage return).
_BAD_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")

RED = "C00000"
AMBER = "B45F06"

#: Page: A4, 2 cm margins (twips).
PAGE_W, PAGE_H, MARGIN = 11906, 16838, 1134


@dataclass
class Run:
    text: str = ""
    bold: bool = False
    italic: bool = False
    underline: bool = False
    color: str = ""
    tab: bool = False  # a tab character (the text is empty)
    anchor: str = ""  # make the run a link to the bookmark with this name

    def key(self):
        return (self.bold, self.italic, self.underline, self.color, self.anchor)


@dataclass
class Para:
    style: str = "Normal"
    runs: list = field(default_factory=list)
    left: int = 0  # twips; with ``hanging`` the first line starts at left - hanging
    hanging: int = 0
    bookmark: str = ""


@dataclass
class Section:
    header: str
    paras: list = field(default_factory=list)


def clean_text(text):
    return _BAD_XML.sub("", text or "")


def _rpr(run, extra=""):
    parts = []
    if run.anchor:
        parts.append('<w:rStyle w:val="Hyperlink"/>')
    if run.bold:
        parts.append("<w:b/>")
    if run.italic:
        parts.append("<w:i/>")
    if run.color:
        parts.append(f'<w:color w:val="{run.color}"/>')
    if run.underline:  # schema order: rStyle, b, i, color, ..., u
        parts.append('<w:u w:val="single"/>')
    parts.append(extra)
    body = "".join(parts)
    return f"<w:rPr>{body}</w:rPr>" if body else ""


def _run_xml(run):
    """One Word run. Line feeds inside the text become <w:br/>, tabs become <w:tab/> (they read back the same)."""
    props = _rpr(run)
    if run.tab:
        return f"<w:r>{props}<w:tab/></w:r>"
    text = clean_text(run.text).replace("\r\n", "\n").replace("\r", "\n")
    pieces = []
    for line_no, line in enumerate(text.split("\n")):
        if line_no:
            pieces.append("<w:br/>")
        for tab_no, chunk in enumerate(line.split("\t")):
            if tab_no:
                pieces.append("<w:tab/>")
            if chunk:
                pieces.append(f'<w:t xml:space="preserve">{escape(chunk)}</w:t>')
    if not pieces:
        return ""
    return f"<w:r>{props}{''.join(pieces)}</w:r>"


def _para_xml(para, bookmark_id, tail_ppr=""):
    ppr = f'<w:pStyle w:val="{para.style}"/>'
    if para.left or para.hanging:
        hang = f' w:hanging="{para.hanging}"' if para.hanging else ""
        ppr += f'<w:ind w:left="{para.left}"{hang}/>'
    ppr += tail_ppr
    runs = []
    for run in para.runs:
        xml = _run_xml(run)
        if xml and run.anchor:
            xml = f'<w:hyperlink w:anchor="{escape(run.anchor)}" w:history="1">{xml}</w:hyperlink>'
        runs.append(xml)
    inner = "".join(runs)
    if para.bookmark:
        inner = (f'<w:bookmarkStart w:id="{bookmark_id}" w:name="{escape(para.bookmark)}"/>{inner}'
                 f'<w:bookmarkEnd w:id="{bookmark_id}"/>')
    return f"<w:p><w:pPr>{ppr}</w:pPr>{inner}</w:p>"


def _sect_pr(index):
    return (f'<w:sectPr><w:headerReference w:type="default" r:id="rIdHeader{index}"/>'
            '<w:footerReference w:type="default" r:id="rIdFooter"/>'
            f'<w:pgSz w:w="{PAGE_W}" w:h="{PAGE_H}"/>'
            f'<w:pgMar w:top="{MARGIN}" w:right="{MARGIN}" w:bottom="{MARGIN}" w:left="{MARGIN}" '
            'w:header="567" w:footer="567" w:gutter="0"/></w:sectPr>')


def _style(style_id, name, based="Normal", nxt="", ppr="", rpr="", outline=None, kind="paragraph", quick=True):
    out = f'<w:style w:type="{kind}" w:styleId="{style_id}"><w:name w:val="{name}"/>'
    if based:
        out += f'<w:basedOn w:val="{based}"/>'
    if nxt:
        out += f'<w:next w:val="{nxt}"/>'
    if quick:
        out += "<w:qFormat/>"
    if outline is not None:
        ppr += f'<w:outlineLvl w:val="{outline}"/>'
    if ppr:
        out += f"<w:pPr>{ppr}</w:pPr>"
    if rpr:
        out += f"<w:rPr>{rpr}</w:rPr>"
    return out + "</w:style>"


def styles_xml():
    sz = lambda half_points: f'<w:sz w:val="{half_points}"/><w:szCs w:val="{half_points}"/>'  # noqa: E731
    parts = [
        f'{_XML}<w:styles xmlns:w="{NS_W}"><w:docDefaults><w:rPrDefault><w:rPr>'
        '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri" w:eastAsia="Calibri"/>'
        f'{sz(22)}<w:lang w:val="en-IN"/></w:rPr></w:rPrDefault>'
        '<w:pPrDefault><w:pPr><w:spacing w:after="80" w:line="259" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>',
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>',
        _style("Heading1", "heading 1", nxt="Normal", outline=0,
               ppr='<w:keepNext/><w:spacing w:before="240" w:after="160"/>', rpr="<w:b/>" + sz(36)),
        _style("Heading2", "heading 2", nxt="Normal", outline=1,
               ppr='<w:keepNext/><w:spacing w:before="240" w:after="120"/>', rpr="<w:b/>" + sz(28)),
        _style("Heading3", "heading 3", nxt="Normal", outline=2,
               ppr='<w:keepNext/><w:spacing w:before="200" w:after="100"/>', rpr="<w:b/>" + sz(24)),
        _style("Title", "Title", nxt="Normal", ppr='<w:spacing w:before="0" w:after="120"/>', rpr="<w:b/>" + sz(44)),
        _style("Subtitle", "Subtitle", nxt="Normal", ppr='<w:spacing w:after="80"/>', rpr=sz(26)),
        _style("ContentsHeading", "Contents Heading", nxt="Normal",
               ppr='<w:keepNext/><w:spacing w:before="360" w:after="120"/>', rpr="<w:b/>" + sz(28)),
        _style("DiaryContents", "Diary Contents", ppr='<w:spacing w:after="40"/>'),
        _style("DiarySubtopic", "Diary Sub-topic", nxt="Normal",
               ppr='<w:keepNext/><w:spacing w:before="160" w:after="80"/>', rpr="<w:b/>"),
        _style("DiarySection", "Diary Section", nxt="Normal",
               ppr='<w:keepNext/><w:spacing w:before="120" w:after="60"/>', rpr="<w:b/>"),
        _style("DiaryItem", "Diary Item"),
        _style("DiaryBullet", "Diary Bullet"),
        _style("DiaryNote", "Diary Note", rpr="<w:i/>"),
        _style("DiarySeeAlso", "Diary See also"),
        _style("Header", "header", ppr='<w:pBdr><w:bottom w:val="single" w:sz="4" w:space="1" w:color="808080"/></w:pBdr>',
               rpr=sz(18), quick=False),
        _style("Footer", "footer", ppr='<w:jc w:val="center"/>', rpr=sz(18), quick=False),
        '<w:style w:type="character" w:styleId="Hyperlink"><w:name w:val="Hyperlink"/>'
        '<w:rPr><w:color w:val="0563C1"/><w:u w:val="single"/></w:rPr></w:style>',
        "</w:styles>",
    ]
    return "".join(parts)


def _header_xml(text):
    return (f"{_XML}<w:hdr {_NS}>"
            f"{_para_xml(Para('Header', [Run(text)]), 0)}</w:hdr>")


def _footer_xml():
    return (f'{_XML}<w:ftr {_NS}><w:p><w:pPr><w:pStyle w:val="Footer"/></w:pPr>'
            '<w:r><w:t xml:space="preserve">Page </w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>1</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:ftr>')


class Document:
    def __init__(self, title="", created="2000-01-01T00:00:00Z"):
        self.title = title
        self.created = created
        self.sections = []

    def new_section(self, header):
        section = Section(header)
        self.sections.append(section)
        return section

    def add(self, para):
        if not self.sections:
            self.new_section("")
        self.sections[-1].paras.append(para)
        return para

    # -- output -----------------------------------------------------------------------------------
    def _body(self):
        if not self.sections:
            self.new_section("")
        out = []
        bookmark_id = 0
        last = len(self.sections) - 1
        for index, section in enumerate(self.sections):
            paras = section.paras or [Para()]
            for n, para in enumerate(paras):
                bookmark_id += 1
                tail = ""
                if index < last and n == len(paras) - 1:
                    tail = _sect_pr(index + 1)  # the section's properties travel with its last paragraph
                out.append(_para_xml(para, bookmark_id, tail))
        return "".join(out) + _sect_pr(len(self.sections))

    def to_bytes(self):
        body = self._body()
        count = len(self.sections)
        document = f"{_XML}<w:document {_NS}><w:body>{body}</w:body></w:document>"
        rels = ['<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>',
                '<Relationship Id="rIdFooter" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>']
        overrides = [
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>',
            '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>',
            '<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>',
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>',
        ]
        for i in range(1, count + 1):
            rels.append(f'<Relationship Id="rIdHeader{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header{i}.xml"/>')
            overrides.append(f'<Override PartName="/word/header{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>')
        content_types = (f'{_XML}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                         '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                         '<Default Extension="xml" ContentType="application/xml"/>' + "".join(overrides) + "</Types>")
        root_rels = (f'{_XML}<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                     '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                     '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
                     "</Relationships>")
        doc_rels = (f'{_XML}<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    + "".join(rels) + "</Relationships>")
        core = (f'{_XML}<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
                'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
                f"<dc:title>{escape(clean_text(self.title))}</dc:title>"
                f'<dcterms:created xsi:type="dcterms:W3CDTF">{escape(self.created)}</dcterms:created></cp:coreProperties>')
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            def put(name, text):
                info = zipfile.ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0))  # fixed time: the same input gives the same bytes
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, text.encode("utf-8"))

            put("[Content_Types].xml", content_types)
            put("_rels/.rels", root_rels)
            put("word/document.xml", document)
            put("word/_rels/document.xml.rels", doc_rels)
            put("word/styles.xml", styles_xml())
            put("word/footer1.xml", _footer_xml())
            put("docProps/core.xml", core)
            for i, section in enumerate(self.sections, start=1):
                put(f"word/header{i}.xml", _header_xml(section.header))
        return buffer.getvalue()
