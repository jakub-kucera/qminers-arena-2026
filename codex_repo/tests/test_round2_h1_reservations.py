import tempfile
import unittest
from pathlib import Path
from scripts.round2_h1_refine import build
from simulator.main import load_strategy_from_file


class H1ReservationTests(unittest.TestCase):
    def test_cancel_pending_quotes_still_reserve_both_sides(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'strategy.py'
            path.write_text(build()['strict_base'])
            for sign in (1,-1):
                bot=load_strategy_from_file(path)
                bot.inventory=99*sign
                bot._orders={'old':[sign,100,1,True,True,0,0,0]}
                sent=[]
                bot.send_order=lambda order:sent.append(order) or 'new'
                bot._quote(100000,sign,99 if sign==1 else 101)
                self.assertEqual(sent,[])

    def test_ioc_counts_pending_reservations(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'strategy.py'
            path.write_text(build()['strict_base'])
            for sign in (1,-1):
                bot=load_strategy_from_file(path)
                bot.inventory=98*sign
                bot._orders={'old':[sign,100,1,True,True,0,0,0]}
                sent=[]
                bot.send_order=lambda order:sent.append(order) or 'new'
                bot._take(100000,2*sign,1,100,101)
                self.assertEqual(len(sent),1)
                self.assertEqual(sent[0].quantity,1)


if __name__=='__main__':unittest.main()
