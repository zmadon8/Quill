from django.test import SimpleTestCase

from investments.services import fund_names


class ParseTests(SimpleTestCase):
    CASES = [
        ("HDFC Flexi Cap Fund - Regular Plan - Growth Option", ("HDFC Flexi Cap Fund", "Regular", "Growth")),
        ("HDFC Flexi Cap Fund - Growth Plan", ("HDFC Flexi Cap Fund", "", "Growth")),
        ("Aditya Birla Sun Life Flexi Cap Fund - Growth - Direct Plan", ("Aditya Birla Sun Life Flexi Cap Fund", "Direct", "Growth")),
        ("X Fund - Direct Plan - IDCW Reinvestment", ("X Fund", "Direct", "IDCW Reinvestment")),
        ("X Fund-Regular Growth", ("X Fund", "Regular", "Growth")),
        ("X Fund - Dividend Payout", ("X Fund", "", "IDCW Payout")),
        ("X Fund - Bonus", ("X Fund", "", "Bonus")),
        ("X Fund - Regular Plan - Bonus Option", ("X Fund", "Regular", "Bonus")),
        ("Reliance Growth Fund - Direct Plan - Growth", ("Reliance Growth Fund", "Direct", "Growth")),
        ("X Fund - REGULAR PLAN - DIVIDEND REINVESTMENT", ("X Fund", "Regular", "IDCW Reinvestment")),
        ("X Fund - Regular Plan - Monthly Dividend Payout", ("X Fund", "Regular", "Monthly IDCW Payout")),
        ("Y Fund (Direct) - Growth", ("Y Fund", "Direct", "Growth")),
        ("Z Fund - Direct Plan - Payout of Income Distribution cum Capital Withdrawal option",
         ("Z Fund", "Direct", "IDCW Payout")),
        ("Axis Fund - Direct Plan - IDCW Transfer", ("Axis Fund", "Direct", "IDCW Transfer")),
        ("Foo Fund - Weekly IDCW", ("Foo Fund", "", "Weekly IDCW")),
        ("Foo Fund Direct Growth", ("Foo Fund", "Direct", "Growth")),
        ("Foo Fund - Direct", ("Foo Fund", "Direct", "")),
        ("Multi-Asset Fund - Direct Plan - Growth Option", ("Multi-Asset Fund", "Direct", "Growth")),
        ("Quarterly Interval Fund", ("Quarterly Interval Fund", "", "")),
        ("Fund (erstwhile Old Name) - Direct - Growth", ("Fund (erstwhile Old Name)", "Direct", "Growth")),
        ("", ("", "", "")),
        ("Growth", ("Growth", "", "")),
    ]

    def test_variants(self):
        for raw, expected in self.CASES:
            with self.subTest(raw=raw):
                self.assertEqual(fund_names.parse(raw), expected)

    def test_standard_name(self):
        self.assertEqual(fund_names.standard_name("HDFC Flexi Cap Fund - Regular Plan - Growth Option"), "HDFC Flexi Cap Fund Regular Plan Growth Option")
        self.assertEqual(fund_names.standard_name("X Fund-Regular Growth"), "X Fund Regular Plan Growth Option")
        self.assertEqual(fund_names.standard_name("X Fund - Dividend Payout"), "X Fund IDCW Payout Option")
        self.assertEqual(fund_names.standard_name("Plain Fund"), "Plain Fund")

    def test_stored_values_win(self):
        self.assertEqual(fund_names.standard_name("X Fund - Growth", plan="Direct"), "X Fund Direct Plan Growth Option")
