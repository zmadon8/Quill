"""Fund asset class from AMFI's category headings (pure: no database)."""
from django.test import SimpleTestCase

from investments.adapters import amfi
from investments.services import asset_class

NAVALL = """Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date

Open Ended Schemes(Debt Scheme - Liquid Fund)

Axis Mutual Fund

100001;INF000000001;-;Axis Liquid Fund - Direct Plan - Growth;2500.1;05-Nov-2026

Open Ended Schemes ( Equity Scheme - Large Cap Fund )

100002;INF000000002;-;Axis Bluechip Fund - Direct Plan - Growth;55.1;05-Nov-2026
100003;INF000000003;-;Axis Other Fund;N.A.;05-Nov-2026

Open Ended Schemes(Other Scheme - Gold ETF)

100004;INF000000004;-;Axis Gold ETF;60.0;05-Nov-2026
"""


class CategoryParseTests(SimpleTestCase):
    def test_default_shape_is_unchanged(self):
        rows = list(amfi.iter_all(NAVALL.splitlines()))
        self.assertEqual([len(r) for r in rows], [5, 5, 5, 5])
        self.assertEqual(rows[0][:3], ("100001", "Axis Liquid Fund - Direct Plan - Growth", "INF000000001"))

    def test_each_scheme_carries_the_heading_above_its_block(self):
        rows = list(amfi.iter_all(NAVALL.splitlines(), with_category=True))
        self.assertEqual([r[5] for r in rows], [
            "Open Ended Schemes(Debt Scheme - Liquid Fund)", "Open Ended Schemes ( Equity Scheme - Large Cap Fund )",
            "Open Ended Schemes ( Equity Scheme - Large Cap Fund )", "Open Ended Schemes(Other Scheme - Gold ETF)"])
        self.assertEqual([asset_class.for_fund(r[5], r[1]) for r in rows], ["debt", "equity", "equity", "gold"])


class MappingTests(SimpleTestCase):
    def test_names(self):
        for name, want in [("X Liquid Fund", "debt"), ("X Overnight Fund", "debt"), ("X Money Market Fund", "debt"), ("X Gilt Fund", "debt"),
                           ("X Corporate Bond Fund", "debt"), ("X Income Fund", "debt"), ("X Gold Fund", "gold"), ("X Balanced Advantage Fund", "other"),
                           ("X Arbitrage Fund", "other"), ("X Multi Asset Allocation Fund", "other"), ("X Hybrid Equity Fund", "other"),
                           ("X Flexi Cap Fund", "equity")]:
            self.assertEqual(asset_class.from_name(name), want, name)

    def test_categories(self):
        self.assertEqual(asset_class.from_category("Open Ended Schemes(Hybrid Scheme - Balanced Hybrid Fund)"), "other")
        self.assertIsNone(asset_class.from_category("Open Ended Schemes(Other Scheme - Index Funds)"))
        self.assertIsNone(asset_class.from_category(""))
