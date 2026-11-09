import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from scripts.round2_h1_maker import build
from simulator.main import load_strategy_from_file
from simulator.models import OrderStatus


class H1MakerTests(unittest.TestCase):
    def test_only_passive_fills_enter_calibration(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'s.py';path.write_text(build()['maker25_wide'])
            for taker in (False,True):
                bot=load_strategy_from_file(path)
                bot._value_us=0;bot._bid_value=.2
                bot._orders={'x':[1,100,10,True,False,0,1000000 if taker else 0,0]}
                bot.on_private_order_update(SimpleNamespace(order_id='x',status=OrderStatus.PARTIALLY_FILLED,
                    timestamp_us=1000,filled_quantity=1,fill_price=100,remaining_quantity=9))
                self.assertEqual(len(bot._cal_labels),0 if taker else 1)
                self.assertEqual(bot.inventory,1)
                self.assertEqual(bot.cash,-100)

    def test_large_maker_quote_respects_shared_pending_budget(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'s.py';path.write_text(build()['maker100_inactive'])
            bot=load_strategy_from_file(path);bot.inventory=90
            bot._orders={'pending':[1,100,5,True,True,0,0,0]}
            sent=[];bot.send_order=lambda r:sent.append(r) or 'new'
            bot._quote(100000,1,99)
            self.assertEqual(len(sent),1)
            self.assertEqual(sent[0].quantity,5)


if __name__=='__main__':unittest.main()
