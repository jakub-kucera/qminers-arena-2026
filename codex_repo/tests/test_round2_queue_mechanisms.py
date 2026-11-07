import tempfile
import unittest
from pathlib import Path

from scripts.round2_queue_value import queue_value
from scripts.round2_queue_wait import queue_wait
from scripts.round2_queue_close_only import close_only_queue
from simulator.main import load_strategy_from_file
from test_strategy import Gateway


class QueueMechanismTests(unittest.TestCase):
    def strategy(self,transform):
        text=transform(Path('strategies/round2_research/round2_absolute_variance_112379.py').read_text())
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'s.py';p.write_text(text);s=load_strategy_from_file(p)
        g=Gateway(s);self.canceled=[];s._ctx.cancel_order=self.canceled.append
        return s,g

    def test_front_quote_keeps_priority_only_with_positive_forecast_edge(self):
        s,g=self.strategy(lambda t:queue_value(t,100))
        s._upper_target=100;s._cached_bid=99;s._cached_ask=101;s._quote_fair=100
        s._quote(0,1,99);oid=next(iter(s._orders));s._orders[oid][3]=True
        s.queue_ahead[oid]=50;s._quote(6000,1,98)
        self.assertEqual(self.canceled,[])
        self.assertEqual(len(g.sent),1)
        s._quote_fair=98.5;s._quote(7000,1,98)
        self.assertEqual(self.canceled,[oid])
        self.assertEqual(s._orders[oid][2],100)

    def test_slow_queue_blocks_new_aligned_exposure(self):
        s,g=self.strategy(lambda t:queue_wait(t,.1))
        s._queue_bid_quantity=1000;s._volume=100
        s._quote(0,1,99)
        self.assertEqual(g.sent,[])
        s._cancel_bid_quantity=10000;s._quote(1,1,99)
        self.assertGreater(len(g.sent),0)

    def test_closing_only_variant_does_not_plan_a_reversal_on_slow_queue(self):
        s,g=self.strategy(lambda t:close_only_queue(t,.1))
        s.inventory=-50;s._queue_bid_quantity=1000;s._volume=100
        s._quote(0,1,99)
        self.assertEqual(g.sent[0].quantity,50)


if __name__=='__main__':unittest.main()
