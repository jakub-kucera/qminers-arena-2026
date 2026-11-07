"""Causal flow consumption, expiry and stop rearming."""
import tempfile
import unittest
from pathlib import Path
from scripts.round2_ra_composite import build
from simulator.main import load_strategy_from_file
from simulator.models import Trade


class RACompositeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.source=Path(cls.temp.name)/'strategy.py'
        cls.source.write_text(build()['flow250_stop3_gate20_flat'])

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def trade(self,quantity,owner='market'):
        return Trade(timestamp_us=0,price=101,quantity=quantity,taker_order_id='t',
            maker_order_id='m',taker_owner=owner,maker_owner='market',book_side='ask')

    def test_small_orders_accumulate_then_are_consumed(self):
        b=load_strategy_from_file(self.source)
        for now in (0,100000):
            b._m2_target(now,99,101,[self.trade(200)])
            self.assertEqual(b._m2_big,0)
        b._m2_target(200000,99,101,[self.trade(200)])
        self.assertEqual(b._m2_big,1)
        self.assertEqual(b._ra_sum,0)
        self.assertEqual(len(b._ra_flow),0)

    def test_expired_and_own_flow_cannot_create_signal(self):
        b=load_strategy_from_file(self.source)
        b._m2_target(0,99,101,[self.trade(300)])
        b._m2_target(250001,99,101,[self.trade(300)])
        self.assertEqual(b._m2_big,0)
        b._m2_target(250002,99,101,[self.trade(1000,'user')])
        self.assertEqual(b._m2_big,0)

    def test_stop_requires_fresh_flow_to_rearm(self):
        b=load_strategy_from_file(self.source)
        b._m2_target(0,99,101,[self.trade(500)])
        b.inventory=100
        b._m2_target(1000000,96,98,[])
        self.assertTrue(b._ra_stopped)
        b._m2_target(1100000,99,101,[])
        self.assertTrue(b._ra_stopped)
        b._m2_target(1200000,99,101,[self.trade(500)])
        self.assertFalse(b._ra_stopped)
        self.assertEqual(b._ra_anchor,100)


if __name__=='__main__':unittest.main()
