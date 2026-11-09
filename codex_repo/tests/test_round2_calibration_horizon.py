"""Changing fill-label horizon must not train early or change price-label horizon."""
import tempfile
import unittest
from pathlib import Path
from scripts.round2_calibration_horizon import build
from simulator.main import load_strategy_from_file
from simulator.models import BookOrderView,OrderBookSnapshot,Side
from simulator.strategy import StrategyContext


class CalibrationHorizonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.path=Path(cls.temp.name)/'s.py'
        cls.path.write_text(build()['fill_horizon2000ms'])

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

    def test_label_matures_at_two_seconds_only(self):
        b=self.bot();b._cal_labels.append((0,1,100,.2,100,1))
        b.on_order_book_change(self.book(1999999),[])
        self.assertEqual(b._cal_groups,[0]*4)
        self.assertEqual(b.HORIZON_US,400000)
        b.on_order_book_change(self.book(2000000),[])
        self.assertAlmostEqual(b._cal_groups[2],.018)

    def test_stale_tolerance_moves_with_maturity(self):
        b=self.bot();b._cal_labels.append((0,1,100,.2,100,1))
        b.on_order_book_change(self.book(3000001),[])
        self.assertEqual(b._cal_groups,[0]*4)
        self.assertEqual(len(b._cal_labels),0)


if __name__=='__main__':unittest.main()
