import unittest

from scripts.compare_market_dynamics import DynamicsProbe
from simulator.models import BookOrderView,OrderBookSnapshot,Side


def snapshot(now,mid=100,spread=2,valid=True):
    return OrderBookSnapshot(now,
        [BookOrderView('b',Side.BUY,mid-spread//2,100,'market')] if valid else [],
        [BookOrderView('a',Side.SELL,mid+spread//2,100,'market')])


class MarketDynamicsTests(unittest.TestCase):
    def test_regular_samples_use_pre_event_price_and_time_weight_spreads(self):
        s=DynamicsProbe(25)
        for row in (snapshot(0,100,2),snapshot(20,110,4),snapshot(30,90,10),snapshot(60,91,2)):
            s.on_order_book_change(row,[])
        self.assertEqual(s.samples,[(25,110),(50,90)])
        r=s.report()
        self.assertEqual(r['spread_tail_time_fraction']['2'],2/3)
        self.assertEqual(r['spread_tail_time_fraction']['5'],0.5)
        self.assertEqual(r['valid_to_valid_mid_jumps']['10'],2)

    def test_invalid_book_is_not_silently_bridged_for_returns_or_jumps(self):
        s=DynamicsProbe(25)
        for row in (snapshot(0),snapshot(20,valid=False),snapshot(30,120),snapshot(60,130)):
            s.on_order_book_change(row,[])
        self.assertEqual(s.samples,[(25,None),(50,120)])
        self.assertEqual(s.report()['valid_return_intervals'],0)
        self.assertEqual(s.report()['valid_to_valid_mid_jumps']['10'],1)

    def test_no_valid_book_reports_missing_statistics_without_zero_division(self):
        s=DynamicsProbe(25)
        s.on_order_book_change(snapshot(0,valid=False),[])
        s.on_order_book_change(snapshot(60,valid=False),[])
        r=s.report()
        self.assertIsNone(r['sampled_return_sd_ticks'])
        self.assertIsNone(r['spread_tail_time_fraction']['1'])


if __name__=='__main__':unittest.main()
