import unittest

from diary.richtext import plain_text, sanitise_html


class SanitiseTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(sanitise_html(""), "")
        self.assertEqual(sanitise_html(None), "")

    def test_allowed_kept(self):
        html = "<p>a <b>b</b><i>i</i><u>u</u><br>x</p>"
        self.assertEqual(sanitise_html(html), html)

    def test_strong_em_converted(self):
        self.assertEqual(
            sanitise_html("<strong>a</strong><em>b</em>"), "<b>a</b><i>b</i>"
        )

    def test_attributes_stripped(self):
        self.assertEqual(
            sanitise_html('<p style="color:red" onclick="x()">hi</p>'), "<p>hi</p>"
        )

    def test_disallowed_tags_removed_text_kept(self):
        self.assertEqual(
            sanitise_html('<div><a href="http://x">link</a> <font color="red">t</font></div>'),
            "link t",
        )

    def test_script_and_style_dropped(self):
        self.assertEqual(
            sanitise_html("<p>a</p><script>alert(1)</script><style>p{}</style>b"),
            "<p>a</p>b",
        )

    def test_escaping(self):
        self.assertEqual(sanitise_html("a < b & c"), "a &lt; b &amp; c")
        self.assertEqual(sanitise_html("&lt;script&gt;"), "&lt;script&gt;")

    def test_unclosed_closed(self):
        self.assertEqual(sanitise_html("<b>bold"), "<b>bold</b>")

    def test_stray_end_tag(self):
        self.assertEqual(sanitise_html("a</b>b"), "ab")

    def test_self_closing_br(self):
        self.assertEqual(sanitise_html("a<br/>b"), "a<br>b")

    def test_idempotent(self):
        once = sanitise_html("<p><strong>x</strong> &amp; <a href='#'>y</a></p>")
        self.assertEqual(sanitise_html(once), once)


class PlainTextTests(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(plain_text("<p>One <b>two</b></p><p>Three</p>"), "One two\nThree")

    def test_br_and_entities(self):
        self.assertEqual(plain_text("a<br>b &amp; c"), "a\nb & c")

    def test_empty(self):
        self.assertEqual(plain_text(""), "")


if __name__ == "__main__":
    unittest.main()
