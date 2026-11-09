"""Pure-module tests: FIFO lots, selling limits, the re-check, XIRR and valuation (plan section 31)."""
from datetime import date
from decimal import Decimal as D

from django.test import SimpleTestCase

from investments import lots, valuation, xirr
from investments.lots import BUY, SELL, TRANSFER, Bucket, Event

A = Bucket(1, 10, None)         # portfolio 1, broker 10, no folio
B = Bucket(1, 20, None)         # same portfolio, other broker
F1 = Bucket(1, 10, 100)         # broker 10, folio 100


def buy(on, units, total, bucket=A, ref=None, **kw):
    return Event(BUY, on, D(units), bucket, ref or f"b{on}", D(total), order=kw.pop("order", 0), **kw)


def sell(on, units, total, bucket=A, ref=None, **kw):
    return Event(SELL, on, D(units), bucket, ref or f"s{on}", D(total), order=kw.pop("order", 0), **kw)


class FifoTests(SimpleTestCase):
    def test_sale_consumes_oldest_first_and_splits_cost(self):
        events = [buy(date(2024, 1, 1), 10, 1000), buy(date(2024, 6, 1), 10, 2000), sell(date(2025, 1, 1), 15, 3000)]
        result = lots.replay(events)
        self.assertEqual(result.violations, [])
        self.assertEqual([(m.buy_ref, m.units, m.cost) for m in result.matches],
                         [("b2024-01-01", D(10), D(1000)), ("b2024-06-01", D(5), D(1000))])
        self.assertEqual(sum(m.proceeds for m in result.matches), D(3000))
        self.assertEqual(result.units(), D(5))
        self.assertEqual(result.cost(), D(1000))
        self.assertEqual(lots.average_cost(result), D(200))

    def test_holding_days_use_allotment_date_and_paid_date_is_kept(self):
        e = buy(date(2024, 1, 8), 5, 500, paid_on=date(2024, 1, 2))
        result = lots.replay([e, sell(date(2025, 1, 8), 5, 600)])
        match = result.matches[0]
        self.assertEqual(match.holding_days, 366)
        self.assertEqual(match.paid_on, date(2024, 1, 2))

    def test_gain_is_proceeds_less_cost(self):
        result = lots.replay([buy(date(2024, 1, 1), 4, 400), sell(date(2024, 2, 1), 4, 480)])
        self.assertEqual(result.matches[0].gain, D(80))

    def test_same_day_purchase_counts_before_sale(self):
        events = [sell(date(2024, 3, 1), 5, 600), buy(date(2024, 3, 1), 5, 500)]
        self.assertEqual(lots.check_history(events), [])

    def test_sale_over_bucket_is_a_violation_with_shortfall(self):
        events = [buy(date(2024, 1, 1), 5, 500), sell(date(2024, 2, 1), 8, 900, ref="S1")]
        (v,) = lots.check_history(events)
        self.assertEqual((v.ref, v.shortfall, v.available), ("S1", D(3), D(5)))

    def test_sale_cannot_borrow_from_another_broker(self):
        events = [buy(date(2024, 1, 1), 5, 500, A), buy(date(2024, 1, 2), 5, 500, B), sell(date(2024, 2, 1), 7, 800, A)]
        (v,) = lots.check_history(events)
        self.assertEqual(v.bucket, A)
        self.assertEqual(lots.available(events, B, date(2024, 2, 1)), D(5))

    def test_no_folio_group_is_its_own_bucket(self):
        events = [buy(date(2024, 1, 1), 5, 500, A), buy(date(2024, 1, 1), 5, 500, F1), sell(date(2024, 2, 1), 6, 700, F1)]
        self.assertEqual(len(lots.check_history(events)), 1)

    def test_reducing_a_purchase_that_a_later_sale_relies_on_is_caught(self):
        before = [buy(date(2024, 1, 1), 10, 1000), sell(date(2024, 2, 1), 10, 1100)]
        after = [buy(date(2024, 1, 1), 6, 600), sell(date(2024, 2, 1), 10, 1100)]
        self.assertEqual(lots.check_history(before), [])
        self.assertEqual(len(lots.check_history(after)), 1)

    def test_moving_a_purchase_after_its_sale_is_caught(self):
        events = [buy(date(2024, 3, 1), 10, 1000), sell(date(2024, 2, 1), 10, 1100)]
        self.assertEqual(len(lots.check_history(events)), 1)

    def test_units_on_a_past_date(self):
        events = [buy(date(2024, 1, 1), 10, 1000), sell(date(2024, 6, 1), 4, 500)]
        self.assertEqual(lots.available(events, A, date(2024, 5, 31)), D(10))
        self.assertEqual(lots.available(events, A, date(2024, 6, 1)), D(6))

    def test_fractional_fund_units(self):
        events = [buy(date(2024, 1, 1), "100.333", 10000), sell(date(2024, 2, 1), "50.1665", 6000)]
        result = lots.replay(events)
        self.assertEqual(result.violations, [])
        self.assertEqual(result.units(), D("50.1665"))
        self.assertEqual(result.cost(), D(5000))

    def test_cost_is_exact_when_a_lot_is_consumed_in_three_pieces(self):
        events = [buy(date(2024, 1, 1), 3, 100)] + [sell(date(2024, 2, d), 1, 40, ref=f"s{d}") for d in (1, 2, 3)]
        result = lots.replay(events)
        self.assertEqual(sum(m.cost for m in result.matches), D(100))
        self.assertEqual(result.cost(), D(0))


class TransferTests(SimpleTestCase):
    def test_transfer_keeps_dates_and_cost_and_moves_oldest_first(self):
        events = [
            buy(date(2023, 1, 1), 10, 1000), buy(date(2024, 1, 1), 10, 2000),
            Event(TRANSFER, date(2024, 6, 1), D(12), A, "T1", to_bucket=B),
        ]
        result = lots.replay(events)
        moved = result.lots[B]
        self.assertEqual([(l.bought_on, l.units, l.cost) for l in moved],
                         [(date(2023, 1, 1), D(10), D(1000)), (date(2024, 1, 1), D(2), D(400))])
        self.assertEqual(result.units(A), D(8))

    def test_sale_after_transfer_matches_the_original_purchase(self):
        events = [buy(date(2023, 1, 1), 10, 1000), Event(TRANSFER, date(2024, 1, 1), D(10), A, "T1", to_bucket=B),
                  sell(date(2024, 6, 1), 10, 2000, B)]
        result = lots.replay(events)
        self.assertEqual(result.violations, [])
        self.assertEqual(result.matches[0].buy_ref, "b2023-01-01")
        self.assertEqual(result.matches[0].bought_on, date(2023, 1, 1))

    def test_transfer_of_more_than_held_is_a_violation(self):
        events = [buy(date(2023, 1, 1), 5, 500), Event(TRANSFER, date(2024, 1, 1), D(6), A, "T1", to_bucket=B)]
        self.assertEqual(len(lots.check_history(events)), 1)


class XirrTests(SimpleTestCase):
    def test_one_year_ten_percent(self):
        got = xirr.xirr([(date(2023, 1, 1), -1000), (date(2024, 1, 1), 1100)])
        self.assertAlmostEqual(got, 1.1 ** (365 / 365) - 1, places=6)

    def test_matches_a_closed_form_two_year_case(self):
        got = xirr.xirr([(date(2022, 1, 1), -1000), (date(2024, 1, 1), 1210)])
        expected = 1.21 ** (365 / 730) - 1
        self.assertAlmostEqual(got, expected, places=6)

    def test_irregular_flows_root_makes_npv_zero(self):
        flows = [(date(2022, 1, 1), -1000), (date(2022, 7, 1), -500), (date(2023, 3, 1), 300), (date(2024, 1, 1), 1500)]
        rate = xirr.xirr(flows)
        npv = sum(a / (1 + rate) ** ((d - flows[0][0]).days / 365) for d, a in flows)
        self.assertAlmostEqual(npv, 0, places=5)

    def test_loss(self):
        self.assertLess(xirr.xirr([(date(2023, 1, 1), -1000), (date(2024, 1, 1), 800)]), 0)

    def test_na_cases(self):
        self.assertIsNone(xirr.xirr([]))
        self.assertIsNone(xirr.xirr([(date(2023, 1, 1), -1000)]))
        self.assertIsNone(xirr.xirr([(date(2023, 1, 1), -1000), (date(2024, 1, 1), -50)]))   # same sign
        self.assertIsNone(xirr.xirr([(date(2023, 1, 1), -1000), (date(2023, 1, 10), 1100)]))  # too short
        self.assertIsNotNone(xirr.xirr([(date(2023, 1, 1), -1000), (date(2023, 1, 10), 1010)], min_days=1))

    def test_total_loss_beyond_range_is_na(self):
        self.assertIsNone(xirr.xirr([(date(2023, 1, 1), -1000), (date(2024, 1, 1), 1)]))

    def test_huge_gain_beyond_range_is_na(self):
        self.assertIsNone(xirr.xirr([(date(2023, 1, 1), -1000), (date(2023, 3, 1), 900000)]))

    def test_solver_falls_back_to_bisection(self):
        # a steep curve where Newton from 0.1 overshoots
        rate = xirr.xirr([(date(2023, 1, 1), -1000), (date(2023, 2, 15), 1200)])
        self.assertIsNotNone(rate)
        npv = -1000 + 1200 / (1 + rate) ** (45 / 365)
        self.assertAlmostEqual(npv, 0, places=4)

    def test_simple_return(self):
        self.assertAlmostEqual(xirr.simple_return(1000, 1100), 0.1)
        self.assertIsNone(xirr.simple_return(0, 5))


class ValuationTests(SimpleTestCase):
    SERIES = [(date(2024, 1, 5), D(100)), (date(2024, 1, 8), D(110))]

    def test_as_of_uses_last_close_on_or_before(self):
        self.assertEqual(valuation.as_of_price(self.SERIES, date(2024, 1, 7)), (date(2024, 1, 5), D(100)))  # weekend
        self.assertEqual(valuation.as_of_price(self.SERIES, date(2024, 1, 8)), (date(2024, 1, 8), D(110)))
        self.assertIsNone(valuation.as_of_price(self.SERIES, date(2024, 1, 4)))
        self.assertEqual(valuation.as_of_price(self.SERIES, date(2030, 1, 1))[1], D(110))

    def test_alt_unchanged_and_averaged(self):
        values = [(date(2024, 1, 1), D(1000)), (date(2024, 1, 11), D(1100))]
        self.assertEqual(valuation.alt_value_on(values, date(2024, 1, 6), valuation.UNCHANGED), D(1000))
        self.assertEqual(valuation.alt_value_on(values, date(2024, 1, 6), valuation.AVERAGED), D(1050))
        self.assertEqual(valuation.alt_value_on(values, date(2024, 1, 11), valuation.AVERAGED), D(1100))
        self.assertEqual(valuation.alt_value_on(values, date(2025, 1, 1), valuation.AVERAGED), D(1100))
        self.assertIsNone(valuation.alt_value_on(values, date(2023, 12, 31)))
        self.assertIsNone(valuation.alt_value_on([], date(2024, 1, 1)))

    def test_position_value(self):
        self.assertEqual(valuation.position_value(D(3), D("10.5")), D("31.5"))
        self.assertIsNone(valuation.position_value(D(3), None))
