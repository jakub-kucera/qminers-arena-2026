"""Freshness expires without inventing an opposite signal; conflict filtering is causal."""
from collections import deque
from pathlib import Path
import tempfile
import unittest
from scripts.round2_ra_flow_quality import build
from simulator.main import load_strategy_from_file
from simulator.models import Trade


class FlowQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        for name,text in build().items():(cls.root/(name+'.py')).write_text(text)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_expired_signal_returns_to_maker_without_flipping(self):
        b=load_strategy_from_file(self.root/'fresh250ms.py')
        b._m2_start=0;b._m2_last_sample=60000000
        b._m2_history=deque([(0,79)])
        b._m2_big=b._m2_shadow_pos=1;b._ra_last_fire=60000000
        self.assertEqual(b._m2_target(60000000,99,101,[]),100)
        self.assertIsNone(b._m2_target(60250001,99,101,[]))
        self.assertEqual(b._m2_big,1)

    def test_conflicting_flow_is_rejected_until_direction_dominates(self):
        b=load_strategy_from_file(self.root/'purity0.5.py')
        for i,quantity in enumerate((400,-400,400,-400,600)):
            t=Trade(timestamp_us=i*10000,price=100,quantity=abs(quantity),taker_order_id='t',
                maker_order_id='m',taker_owner='market',maker_owner='market',book_side='ask' if quantity>0 else 'bid')
            b._m2_target(i*10000,99,101,[t])
        self.assertEqual(b._m2_big,0)
        t=Trade(timestamp_us=50000,price=100,quantity=1200,taker_order_id='t2',maker_order_id='m',
            taker_owner='market',maker_owner='market',book_side='ask')
        b._m2_target(50000,99,101,[t])
        self.assertEqual(b._m2_big,1)
        self.assertEqual(b._ra_sum,0)


if __name__=='__main__':unittest.main()
