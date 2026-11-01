"""Rich text sanitiser (docs/DESIGN.md section 3.3). Pure Python, no Django.

Output is limited to p, br, b, i, u. strong becomes b, em becomes i.
"""

import re
from html import escape, unescape
from html.parser import HTMLParser

ALLOWED = {"p", "br", "b", "i", "u"}
_CONVERT = {"strong": "b", "em": "i"}
_DROP_CONTENT = {"script", "style", "head", "title", "template"}


class _Sanitiser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.open = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _DROP_CONTENT:
            self.skip += 1
            return
        tag = _CONVERT.get(tag, tag)
        if self.skip or tag not in ALLOWED:
            return
        if tag == "br":
            self.out.append("<br>")
            return
        self.out.append(f"<{tag}>")
        self.open.append(tag)

    def handle_startendtag(self, tag, attrs):
        if tag in _DROP_CONTENT:
            return
        if _CONVERT.get(tag, tag) == "br" and not self.skip:
            self.out.append("<br>")

    def handle_endtag(self, tag):
        if tag in _DROP_CONTENT:
            self.skip = max(0, self.skip - 1)
            return
        tag = _CONVERT.get(tag, tag)
        if self.skip or tag not in ALLOWED or tag == "br":
            return
        if tag in self.open:
            while self.open:
                top = self.open.pop()
                self.out.append(f"</{top}>")
                if top == tag:
                    break

    def handle_data(self, data):
        if not self.skip:
            self.out.append(escape(data, quote=False))

    def result(self):
        while self.open:
            self.out.append(f"</{self.open.pop()}>")
        return "".join(self.out)


def sanitise_html(html):
    """Return HTML containing only p, br, b, i, u (no attributes)."""
    if not html:
        return ""
    parser = _Sanitiser()
    parser.feed(html)
    parser.close()
    return parser.result()


def plain_text(html):
    """Plain-text copy for searching. Paragraphs and breaks become newlines."""
    if not html:
        return ""
    clean = sanitise_html(html)
    clean = re.sub(r"<br>|</p>", "\n", clean)
    clean = re.sub(r"<[^>]+>", "", clean)
    clean = unescape(clean)
    lines = [ln.strip() for ln in clean.split("\n")]
    return "\n".join(lines).strip()
