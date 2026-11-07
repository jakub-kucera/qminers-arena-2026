"""Experimental bursts preserve reservations and trigger bounded-size recovery."""
import tempfile
import unittest
from pathlib import Path
from scripts.round2_burst_revisit import build
from simulator.main import load_strategy_from_file
from simulator.models import OrderStatus,PrivateOrderEvent
from simulator.strategy import StrategyContext


class BurstRevisitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.path=Path(cls.temp.name)/'s.py'
        cls.path.write_text(build()['cap1000_hold20ms'])

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def bot(self):
        b=load_strategy_from_file(self.path);sent=[]
        def submit(request):sent.append(request);return str(len(sent))
        b._attach_context(StrategyContext(submit,lambda *_:None,lambda *_:None,lambda:0))
        return b,sent

    def test_large_quote_does_not_duplicate_pending_reservation(self):
        b,sent=self.bot();b._entry_buy_allowed=True;b._burst_prediction=1;b._burst_spread=4
        b._quote(0,1,100);b._quote(1,1,100)
        self.assertEqual(len(sent),1)
        self.assertEqual(sent[0].quantity,1000)
        self.assertEqual(sum(r[2] for r in b._orders.values()),1000)

    def test_recovery_trigger_sends_only_excess_and_sets_cooldown_after_fill(self):
        b,sent=self.bot();b.inventory=1000
        b._cached_bid=99;b._cached_ask=101;b._cached_time=0
        b._hedge(0);self.assertEqual(sent,[])
        b._hedge(19999);self.assertEqual(sent,[])
        b._hedge(20000);b._hedge(20001)
        self.assertEqual(len(sent),1);self.assertEqual(sent[0].quantity,900)
        b.on_private_order_update(PrivateOrderEvent(timestamp_us=25000,order_id='1',
            status=OrderStatus.FILLED,filled_quantity=900,remaining_quantity=0,fill_price=99))
        self.assertEqual(b.inventory,100)
        self.assertIsNone(b._burst_start)
        self.assertEqual(b._burst_cooldown,1025000)


if __name__=='__main__':unittest.main()
