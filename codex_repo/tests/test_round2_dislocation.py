import tempfile
import unittest
from pathlib import Path

from scripts.round2_dislocation_taker import taker_source
from simulator.main import load_strategy_from_file
from simulator.models import BookOrderView,OrderBookSnapshot,OrderStatus,OrderType,PrivateOrderEvent,Side
from test_strategy import Gateway


class DislocationTakerTests(unittest.TestCase):
    def strategy(self):
        text=taker_source(Path('strategies/round2/round2_transfer.py').read_text(),100000)
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'s.py';p.write_text(text);s=load_strategy_from_file(p)
        s._labels=s.MIN_LABELS;s._last_fit_us=0
        return s,Gateway(s)

    def book(self,time):
        return OrderBookSnapshot(time,[BookOrderView('b',Side.BUY,100,900,'market')],
                                 [BookOrderView('a',Side.SELL,101,100,'market')])

    def test_crossing_cost_gate_blocks_small_prediction(self):
        s,g=self.strategy();s._weights[2]=.5
        s.on_order_book_change(self.book(1),[])
        self.assertEqual(g.sent,[])
        self.assertFalse(hasattr(s,'_vol_variance'))

    def test_single_ioc_entry_holds_until_horizon_then_reduces(self):
        s,g=self.strategy();s._weights[2]=1
        s.on_order_book_change(self.book(1),[])
        self.assertEqual((g.sent[0].side,g.sent[0].quantity,g.sent[0].order_type),(Side.BUY,20,OrderType.IOC))
        s.on_order_book_change(self.book(2),[])
        self.assertEqual(len(g.sent),1)
        oid=next(iter(s._orders))
        s.on_private_order_update(PrivateOrderEvent(timestamp_us=5001,order_id=oid,status=OrderStatus.ACCEPTED,remaining_quantity=20))
        s.on_private_order_update(PrivateOrderEvent(timestamp_us=5001,order_id=oid,status=OrderStatus.FILLED,
            filled_quantity=20,remaining_quantity=0,fill_price=101))
        s.on_order_book_change(self.book(50000),[])
        self.assertEqual(len(g.sent),1)
        s.on_order_book_change(self.book(100002),[])
        self.assertEqual((g.sent[-1].side,g.sent[-1].quantity),(Side.SELL,20))


if __name__=='__main__':unittest.main()
