"""AMFI's newer lines carry the plan and option as their own columns after the name; they must reach the stored scheme and every display."""
from datetime import timedelta

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from investments.adapters import amfi
from investments.models import AmfiScheme
from investments.services import instrument_search, schemes

NAVALL = """Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;Net Asset Value;Date

Open Ended Schemes(Equity Scheme - Flexi Cap Fund)
118955;INF179K01UT0;-;HDFC Flexi Cap Fund;Direct Plan;Growth Option;2374.132;12-Nov-2026
118954;INF179K01UR4;-;HDFC Flexi Cap Fund;Regular Plan;Growth Option;2100.000;12-Nov-2026
118956;INF179K01UU8;INF179K01UV6;HDFC Flexi Cap Fund;Direct Plan;IDCW Option;100.000;12-Nov-2026
100001;INF000000001;-;Old Fund - Regular Plan - Growth;50.0;12-Nov-2026
"""


class ParseTests(SimpleTestCase):
    def test_plan_and_option_come_from_their_columns(self):
        rows = list(amfi.iter_all(NAVALL.splitlines(), with_category=True, with_plan=True))
        self.assertEqual([r[6:] for r in rows], [("Direct", "Growth"), ("Regular", "Growth"), ("Direct", "IDCW"), ("", "")])
        self.assertEqual(len(list(amfi.iter_all(NAVALL.splitlines()))[0]), 5)


class StoreTests(TestCase):
    def store(self):
        return schemes._store_rows(amfi.iter_all(NAVALL.splitlines(), with_category=True, with_plan=True))

    def test_stored_and_displayed(self):
        self.store()
        s = AmfiScheme.objects.get(code="118955")
        self.assertEqual((s.plan, s.option), ("Direct", "Growth"))
        self.assertEqual(s.display_name, "HDFC Flexi Cap Fund Direct Plan Growth Option")
        old = AmfiScheme.objects.get(code="100001")
        self.assertEqual((old.plan, old.option), ("Regular", "Growth"))
        found = {x.code: x for x in schemes.find("hdfc flexi")}
        self.assertEqual({(x.plan, x.option) for x in found.values()}, {("Direct", "Growth"), ("Regular", "Growth"), ("Direct", "IDCW")})
        self.assertEqual(instrument_search.fund_plans(["118954"]), {"118954": ("Regular", "Growth")})

    def test_refresh_rewrites_blank_rows_and_advances_updated_at(self):
        AmfiScheme.objects.create(code="118955", name="HDFC Flexi Cap Fund")
        AmfiScheme.objects.filter(code="118955").update(updated_at=timezone.now() - timedelta(days=30))
        before = AmfiScheme.objects.get(code="118955").updated_at
        self.store()
        s = AmfiScheme.objects.get(code="118955")
        self.assertEqual((s.plan, s.option), ("Direct", "Growth"))
        self.assertGreater(s.updated_at, before)
        self.assertFalse(schemes.due())
