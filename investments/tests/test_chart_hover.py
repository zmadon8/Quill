"""Hover data on the SVG line charts (static/js/investments/chart-hover.js reads it); the chart still draws without JS."""
import json
from datetime import date, timedelta

from django.template.loader import render_to_string
from django.test import SimpleTestCase

from investments import svgchart


class ChartHoverTests(SimpleTestCase):
    def chart(self, n=5, label="A & B"):
        days = [date(2024, 1, 1) + timedelta(days=i) for i in range(n)]
        return svgchart.line_chart(days, [(label, [1 + i for i in range(n)]), ("Index", [None] + [2] * (n - 1))])

    def test_hover_data_parses_and_matches_lines(self):
        hover = json.loads(self.chart()["hover"])
        self.assertEqual(len(hover["x"]), 5)
        self.assertEqual(len(hover["d"]), 5)
        self.assertEqual([s["l"] for s in hover["s"]], ["A & B", "Index"])
        self.assertEqual(hover["s"][0]["v"][0], "1.00")
        self.assertEqual(hover["s"][1]["v"][0], "")          # no value on that day
        self.assertEqual(hover["d"][0], "1 Jan 2024")

    def test_point_count_is_bounded_and_keeps_the_last_day(self):
        hover = json.loads(self.chart(n=1000)["hover"])
        self.assertLessEqual(len(hover["x"]), svgchart.HOVER_POINTS + 1)
        self.assertEqual(hover["d"][-1], "26 Sep 2026")

    def test_template_renders_escaped_data_and_polylines(self):
        html = render_to_string("investments/_chart.html", {"chart": self.chart(), "caption": "Test"})
        self.assertIn('class="ch hv"', html)
        self.assertIn('tabindex="0"', html)
        self.assertIn('data-hover="', html)
        self.assertIn("A &amp; B", html)
        self.assertNotIn('"l":"A & B"', html)             # quotes in the attribute are escaped
        self.assertIn("<polyline", html)
        self.assertIn('class="hv-tip"', html)

    def test_no_chart_renders_no_hover_markup(self):
        html = render_to_string("investments/_chart.html", {"chart": None, "caption": "Test"})
        self.assertNotIn("data-hover", html)
