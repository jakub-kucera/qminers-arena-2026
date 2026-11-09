import tempfile
import unittest
from pathlib import Path

from scripts.profile_round import Histogram, MarketProbe, ProfileSimulator, SignalStats
from simulator.models import BookOrderView, OrderBookSnapshot, Side, Trade
from simulator.simulator import SimulationConfig


def book(now,bid=99,ask=101):
    return OrderBookSnapshot(now,
        [] if bid is None else [BookOrderView('b',Side.BUY,bid,10,'market')],
        [] if ask is None else [BookOrderView('a',Side.SELL,ask,20,'market')])


def buying(now):
    return [Trade(timestamp_us=now,price=101,quantity=5,taker_order_id='t',maker_order_id='a',
                  taker_owner='market',maker_owner='market',book_side='ask')]


class ProfileTests(unittest.TestCase):
    def test_equal_timestamp_uses_book_before_market_change(self):
        p=MarketProbe(horizons=(5000,))
        p.on_order_book_change(book(1),buying(1))
        p.on_order_book_change(book(5001,100,102),[])
        s=p.stats[(0,5000,'trade_flow')]
        self.assertEqual(s.n,1)
        self.assertEqual(s.sy,0)
        self.assertEqual(s.follow_n,1)
        self.assertEqual(s.follow_sum,-2)

    def test_quote_moving_before_latency_can_prevent_entry(self):
        p=MarketProbe(horizons=(5000,))
        p.on_order_book_change(book(1),buying(1))
        p.on_order_book_change(book(2001,100,102),[])
        p.on_order_book_change(book(5001,100,102),[])
        s=p.stats[(0,5000,'trade_flow')]
        self.assertEqual(s.follow_n,0)
        self.assertEqual(s.fade_n,1)
        self.assertEqual(s.sy,1)

    def test_end_labels_remain_censored(self):
        p=MarketProbe(horizons=(5000,20000))
        p.on_order_book_change(book(1),buying(1))
        self.assertFalse(p.stats)
        self.assertEqual(p.report()['unresolved_at_end_by_horizon_ms'],{'5.0':1,'20.0':1})

    def test_labels_do_not_cross_chronological_blocks(self):
        p=MarketProbe(block_us=1_000_000,horizons=(20000,))
        p.on_order_book_change(book(0,None,None),[])
        p.on_order_book_change(book(990_000),buying(990_000))
        p.on_order_book_change(book(1_010_000),[])
        self.assertFalse(p.stats)
        self.assertEqual(p.skipped['crosses_time_block'],1)

    def test_time_weighting_handles_transient_one_sided_quotes(self):
        p=MarketProbe()
        p.on_order_book_change(book(0),[])
        p.on_order_book_change(book(1_000_000,ask=None),[])
        p.on_order_book_change(book(1_000_001),[])
        p.on_order_book_change(book(2_000_000),[])
        self.assertEqual(p.valid_time_us,1_999_999)
        self.assertEqual(p.invalid_time_us,1)
        self.assertEqual(p.report()['time_weighted_book']['spread_ticks']['mean'],2)

    def test_observation_storage_is_bounded_by_time_horizon(self):
        p=MarketProbe()
        for n in range(10000):
            p.on_order_book_change(book(n*1000),[])
        for h,queue in p.pending.items():
            self.assertLessEqual(len(queue),h//p.sample_us+1)
        self.assertLessEqual(len(p.awaiting_entry),2)

    def test_histogram_weighted_mean_and_quantile_intervals(self):
        h=Histogram()
        h.add(1,9)
        h.add(100,1)
        r=h.report()
        self.assertAlmostEqual(r['mean'],10.9)
        self.assertEqual(r['quantile_intervals']['0.5']['upper_inclusive'],1)
        self.assertEqual(r['quantile_intervals']['0.95']['upper_inclusive'],100)

    def test_round_trip_requires_covering_both_spreads(self):
        s=SignalStats()
        s.add(1,2,(99,101,True,True),(101,103,10,10))
        r=s.report()
        self.assertEqual(r['follow_mean_quote_round_trip_ticks'],0)
        self.assertEqual(r['fade_mean_quote_round_trip_ticks'],-4)

    def test_replay_rejects_backward_timestamps(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'bad.csv'
            path.write_text('Time,Operation,OrderId,Side,Volume,Price,Lifespan\n'
                            '1,Insert,b,B,10,99,G\n0,Insert,a,A,10,101,G\n')
            engine=ProfileSimulator(MarketProbe(),SimulationConfig())
            with self.assertRaisesRegex(ValueError,'backwards'):
                engine.run(path)


if __name__ == '__main__':
    unittest.main()
