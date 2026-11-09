"""Directional calibration labels mature causally and stay in their own group."""
import tempfile
import unittest
from math import exp
from pathlib import Path
from scripts.round2_conditional_calibration import build
from simulator.main import load_strategy_from_file
from simulator.models import BookOrderView,OrderBookSnapshot,Side
from simulator.strategy import StrategyContext


class ConditionalCalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.path=Path(cls.temp.name)/'s.py'
        cls.path.write_text(build()['side_spread1_blend1.0'])

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def bot(self):
        b=load_strategy_from_file(self.path);sent=[]
        def submit(request):sent.append(request);return str(len(sent))
        b._attach_context(StrategyContext(submit,lambda *_:None,lambda *_:None,lambda:0))
        return b

    def book(self,now):
        return OrderBookSnapshot(now,[BookOrderView('b',Side.BUY,101,100,'market')],
            [BookOrderView('a',Side.SELL,103,100,'market')])

    def test_mature_label_updates_only_recorded_direction_and_spread(self):
        b=self.bot();b._cal_labels.append((0,1,100,.2,100,1))
        b.on_order_book_change(self.book(399999),[])
        self.assertEqual(b._cal_groups,[0,0,0,0])
        b.on_order_book_change(self.book(400000),[])
        self.assertAlmostEqual(b._cal_groups[2],.054)
        self.assertEqual([b._cal_groups[i] for i in (0,1,3)],[0,0,0])

    def test_stale_labels_are_discarded(self):
        b=self.bot();b._cal_labels.append((0,-1,103,.2,100,1))
        b.on_order_book_change(self.book(1500000),[])
        self.assertEqual(b._cal_groups,[0,0,0,0])

    def test_unobserved_group_decays_toward_zero(self):
        b=self.bot();b._cal_groups[1]=.5;b._cal_time=0
        b.on_order_book_change(self.book(300000000),[])
        self.assertAlmostEqual(b._cal_groups[1],.5*exp(-1))


if __name__=='__main__':unittest.main()
