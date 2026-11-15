"""Buy and sell markers on portfolio charts: the aggregation is a pure function and the markers draw on the first line."""
from datetime import date, timedelta
from decimal import Decimal

from django.template.loader import render_to_string
from django.test import SimpleTestCase

from investments import markers, svgchart
from investments.services import dashboard


def days(n, start=date(2024, 1, 1), step=1):
    return [start + timedelta(days=i * step) for i in range(n)]


class AggregateTests(SimpleTestCase):
    def test_one_marker_per_day_and_side_with_count_and_net(self):
        ds = days(5)
        out = markers.aggregate(ds, [(ds[1], "buy", Decimal(1000)), (ds[1], "buy", Decimal(234567)), (ds[1], "sell", Decimal(500))])
        self.assertEqual([m[0::2] for m in out], [["2024-01-02", "buy"], ["2024-01-02", "sell"]])
        self.assertIn("2 purchases, net Rs2,35,567.00", out[0][1])
        self.assertIn("1 sale, net Rs500.00", out[1][1])

    def test_weekly_sample_groups_into_the_next_sampled_day(self):
        ds = days(4, step=7)
        out = markers.aggregate(ds, [(ds[0] + timedelta(days=2), "buy", Decimal(10)), (ds[0] + timedelta(days=6), "buy", Decimal(20))])
        self.assertEqual([m[0] for m in out], ["2024-01-08"])
        self.assertIn("2 purchases, net Rs30.00", out[0][1])

    def test_outside_the_window_and_other_sides_are_left_out(self):
        ds = days(3)
        self.assertEqual(markers.aggregate(ds, [(ds[-1] + timedelta(days=1), "buy", Decimal(1)), (ds[0], "dividend", Decimal(1))]), [])
        self.assertEqual(markers.aggregate([], [(ds[0], "buy", Decimal(1))]), [])

    def test_json_safe(self):
        import json

        ds = days(3)
        out = markers.aggregate(ds, [(ds[0], "sell", Decimal(5))])
        self.assertEqual(json.loads(json.dumps(out)), out)


class DrawTests(SimpleTestCase):
    def test_iso_markers_draw_on_the_first_line(self):
        ds = days(5)
        chart = svgchart.line_chart(ds, [("Value", [1, 2, 3, 4, 5])], markers=markers.aggregate(ds, [(ds[2], "buy", Decimal(9)), (ds[3], "sell", Decimal(9))]))
        self.assertEqual([m["kind"] for m in chart["markers"]], ["buy", "sell"])
        html = render_to_string("investments/_chart.html", {"chart": chart, "caption": "c"})
        self.assertIn("1 purchase, net Rs9.00", html)
        self.assertIn("var(--loss)", html)

    def test_payload_version_covers_markers(self):
        self.assertGreaterEqual(dashboard.PAYLOAD_VERSION, 4)
