"""Text that must be typed exactly to confirm is shown with its real capitals (never in a small-caps label)."""
import pathlib
import re

from django.test import SimpleTestCase

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCREENS = {
    "templates/fees/clear_confirm.html": "clear_phrase",
    "templates/fees/restore_preview.html": "restore_phrase",
    "templates/accounts/profile_clear.html": "target.name",
    "templates/backups/restore_preview.html": "confirm_word",
}


class ExactTextTests(SimpleTestCase):
    def test_every_phrase_to_type_is_marked_exact_text(self):
        for path, variable in SCREENS.items():
            html = (ROOT / path).read_text(encoding="utf-8")
            self.assertRegex(html, r'<strong class="exact-text">\{\{ %s \}\}</strong>' % re.escape(variable), path)

    def test_exact_text_cancels_the_capitals(self):
        css = (ROOT / "static/css/site.css").read_text(encoding="utf-8")
        rule = re.search(r"\.exact-text \{([^}]*)\}", css)
        self.assertIsNotNone(rule)
        self.assertIn("text-transform: none", rule.group(1))
