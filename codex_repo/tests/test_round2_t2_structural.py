import tempfile
import unittest
from pathlib import Path
from scripts.round2_t2_structural import build
from simulator.main import load_strategy_from_file
from simulator.models import BookOrderView,OrderBookSnapshot,Side
from simulator.strategy import StrategyContext


class StructuralTakerTests(unittest.TestCase):
    def test_feature_dimensions_and_causal_labels(self):
        with tempfile.TemporaryDirectory() as d:
            for name,text in build().items():
                path=Path(d)/(name+'.py');path.write_text(text)
                bot=load_strategy_from_file(path)
                orders=[]
                bot._attach_context(StrategyContext(lambda r:orders.append(r) or str(len(orders)),lambda *_:None,lambda *_:None,lambda:0))
                def book(now):
                    return OrderBookSnapshot(now,[BookOrderView('b',Side.BUY,100,100,'market')],
                        [BookOrderView('a',Side.SELL,101,100,'market')])
                bot.on_order_book_change(book(0),[])
                self.assertEqual(len(bot._observations[0][2]),bot.FEATURE_COUNT)
                bot.on_order_book_change(book(bot.HORIZON_US-1),[])
                self.assertEqual(bot._labels,0)
                bot.on_order_book_change(book(bot.HORIZON_US),[])
                self.assertEqual(bot._labels,1)
                self.assertEqual(bot.POSITION_LIMIT,100)


if __name__=='__main__':unittest.main()
