"""Causal calibration and reduction-only reservation invariants."""
import tempfile
import unittest
from pathlib import Path
from scripts.round2_adaptation_batch import build
from simulator.main import load_strategy_from_file
from simulator.models import BookOrderView,OrderBookSnapshot,Side
from simulator.strategy import StrategyContext


class AdaptationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        for name,text in build().items():(cls.root/(name+'.py')).write_text(text)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def bot(self,name):
        bot=load_strategy_from_file(self.root/(name+'.py'));sent=[]
        def submit(request):sent.append(request);return str(len(sent))
        bot._attach_context(StrategyContext(submit,lambda *_:None,lambda *_:None,lambda:0))
        return bot,sent

    def snapshot(self,now):
        return OrderBookSnapshot(now,[BookOrderView('b',Side.BUY,101,100,'market')],
                                 [BookOrderView('a',Side.SELL,103,100,'market')])

    def test_fill_label_cannot_change_gate_before_maturity(self):
        bot,_=self.bot('calibrate_fast')
        bot._cal_labels.append((0,1,100,.2,100))
        bot.on_order_book_change(self.snapshot(399999),[])
        self.assertEqual(bot._cal_error,0)
        self.assertEqual(len(bot._cal_labels),1)
        bot.on_order_book_change(self.snapshot(400000),[])
        self.assertAlmostEqual(bot._cal_error,.054)
        self.assertEqual(len(bot._cal_labels),0)

    def test_stale_label_is_discarded(self):
        bot,_=self.bot('calibrate_fast')
        bot._cal_labels.append((0,1,100,.2,100))
        bot.on_order_book_change(self.snapshot(1500000),[])
        self.assertEqual(bot._cal_error,0)
        self.assertEqual(len(bot._cal_labels),0)

    def test_reduction_reserves_pending_cancels(self):
        bot,sent=self.bot('passive_escape');bot.inventory=-50
        bot._entry_buy_allowed=False
        bot._orders['pending']=[1,101,20,True,True,0]
        bot._quote(10000,1,101)
        self.assertEqual(len(sent),1)
        self.assertEqual(sent[0].quantity,30)
        self.assertEqual(sum(r[2] for r in bot._orders.values()),50)

    def test_blocked_side_cannot_increase_inventory(self):
        bot,sent=self.bot('passive_escape');bot.inventory=50
        bot._entry_buy_allowed=False;bot._quote(10000,1,101)
        self.assertEqual(sent,[])

    def test_aggressive_trend_escape_stops_at_flat(self):
        bot,sent=self.bot('trend_escape');bot.inventory=80
        bot._cached_bid=101;bot._cached_ask=103
        bot._quote(10000,-1,101)
        self.assertEqual(len(sent),1)
        self.assertEqual(sent[0].quantity,80)


if __name__=='__main__':unittest.main()
