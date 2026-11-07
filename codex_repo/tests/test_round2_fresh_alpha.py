import tempfile
import unittest
from pathlib import Path

from scripts.round2_fresh_quote_alpha import fast_quotes,order_age
from scripts.round2_pretrained_alpha import BASE
from simulator.main import load_strategy_from_file
from simulator.models import BookOrderView,OrderBookSnapshot,Side


class FreshQuoteAlphaTests(unittest.TestCase):
    def strategy(self,source):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'s.py';p.write_text(source);s=load_strategy_from_file(p)
        s._learn=lambda *args:None;s._quote=lambda *args:None;s._hedge=lambda *args:None
        return s

    def book(self,time,ask_id):
        return OrderBookSnapshot(time,[BookOrderView('b',Side.BUY,100,100,'market')],
            [BookOrderView(ask_id,Side.SELL,101,100,'market')])

    def test_near_touch_age_uses_observation_history(self):
        s=self.strategy(order_age(BASE.read_text(),100000))
        s.on_order_book_change(self.book(0,'a'),[])
        s.on_order_book_change(self.book(200001,'new_a'),[])
        frame=s._observations[-1][2]
        self.assertEqual(len(frame),34)
        self.assertEqual(frame[-5:],(-1,1,-1,1,0))

    def test_new_ask_moves_only_causal_fresh_quote_statistics(self):
        s=self.strategy(fast_quotes(BASE.read_text(),20000))
        s.on_order_book_change(self.book(0,'a'),[])
        s.on_order_book_change(self.book(200001,'new_a'),[])
        frame=s._observations[-1][2]
        self.assertEqual(len(frame),33)
        self.assertLess(frame[-4],0)
        self.assertGreater(frame[-3],0)


if __name__=='__main__':unittest.main()
