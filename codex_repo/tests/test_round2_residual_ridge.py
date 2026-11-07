"""Residual training uses stored causal features and decays stale corrections."""
from math import exp,isfinite
from pathlib import Path
import tempfile
import unittest
from scripts.round2_residual_ridge import build
from simulator.main import load_strategy_from_file
from simulator.models import BookOrderView,OrderBookSnapshot,Side
from simulator.strategy import StrategyContext


class ResidualRidgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.path=Path(cls.temp.name)/'s.py'
        cls.path.write_text(build()['ridge5_blend1.0'])

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

    def test_no_training_before_maturity_and_uses_saved_flow_feature(self):
        b=self.bot();context=(0,0,1,0,1,.5)
        b._cal_labels.append((0,1,100,.2,100,1,context))
        b.on_order_book_change(self.book(399999),[])
        self.assertEqual(b._res_weights,[0]*6)
        self.assertIsNone(b._res_time)
        b.on_order_book_change(self.book(400000),[])
        self.assertEqual(b._m2_big,0)
        self.assertGreater(b._res_weights[4],0)
        self.assertTrue(all(isfinite(w) for w in b._res_weights))

    def test_regularized_fit_and_stale_decay(self):
        b=self.bot();x=(1,0,0,0,0,0)
        for i in range(20):b._res_update(i*1000000,x,.3,100)
        recent=b._res_predict(19000000,x)
        self.assertGreater(recent,0)
        self.assertLess(recent,.3)
        self.assertAlmostEqual(b._res_predict(319000000,x),recent*exp(-1))
        self.assertLessEqual(abs(b._res_predict(19000000,(100,0,0,0,0,0))),.5)


if __name__=='__main__':unittest.main()
