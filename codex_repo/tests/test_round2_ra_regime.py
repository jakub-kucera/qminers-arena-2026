"""Independent shadow stops and mode hysteresis use only observed information."""
from collections import deque
from pathlib import Path
import tempfile
import unittest
from scripts.round2_ra_regime import build
from simulator.main import load_strategy_from_file
from simulator.models import Trade


class RegimeControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        for name,text in build().items():(cls.root/(name+'.py')).write_text(text)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_hysteresis_requires_entry_gain_and_retains_mode_until_exit(self):
        b=load_strategy_from_file(self.root/'stopped_shadow0_exit5.py')
        b._m2_start=0;b._m2_last_sample=60000000
        b._m2_history=deque([(0,79)])
        b._m2_shadow_cash=100
        b._m2_target(60000000,99,101,[])
        self.assertTrue(b._regime_active)
        b._m2_shadow_cash=90
        b._m2_target(60000001,99,101,[])
        self.assertTrue(b._regime_active)
        b._m2_shadow_cash=83
        b._m2_target(60000002,99,101,[])
        self.assertFalse(b._regime_active)
        b._m2_shadow_cash=90
        b._m2_target(60000003,99,101,[])
        self.assertFalse(b._regime_active)

    def test_shadow_stops_and_rearms_without_real_position(self):
        b=load_strategy_from_file(self.root/'stopped_shadow1_exitNone.py')
        trade=Trade(timestamp_us=0,price=101,quantity=500,taker_order_id='t',
            maker_order_id='m',taker_owner='market',maker_owner='market',book_side='ask')
        b._m2_target(0,99,101,[trade])
        self.assertEqual(b._m2_shadow_pos,1)
        b._m2_target(1000000,96,98,[])
        self.assertEqual(b._m2_shadow_pos,0)
        self.assertTrue(b._shadow_ra_stopped)
        self.assertEqual(b._m2_shadow_cash,-5)
        self.assertFalse(b._ra_stopped)
        b._m2_target(1100000,96,98,[trade])
        self.assertEqual(b._m2_shadow_pos,1)
        self.assertFalse(b._shadow_ra_stopped)
        self.assertEqual(b._shadow_ra_anchor,97)


if __name__=='__main__':unittest.main()
