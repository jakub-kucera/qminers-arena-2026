"""Risk accounting and causal signal checks for the exact supplied file."""
import unittest
from pathlib import Path
from simulator.main import load_strategy_from_file
from simulator.models import BookOrderView,OrderBookSnapshot,OrderStatus,PrivateOrderEvent,Side,Trade
from simulator.strategy import StrategyContext


class SuppliedM2Tests(unittest.TestCase):
    def bot(self):
        s=load_strategy_from_file(Path('strategies/round2_big_aggressor_supplied.py'));sent=[]
        def submit(request):sent.append(request);return str(len(sent))
        s._attach_context(StrategyContext(submit,lambda *_:None,lambda *_:None,lambda:0))
        return s,sent

    def trade(self,quantity,owner='market',book_side='ask'):
        return Trade(timestamp_us=0,price=101,quantity=quantity,taker_order_id='t',maker_order_id='m',
                     taker_owner=owner,maker_owner='market',book_side=book_side)

    def snapshot(self,now=0,bid=99,ask=101):
        return OrderBookSnapshot(now,[BookOrderView('b',Side.BUY,bid,1000,'market')],
                                 [BookOrderView('a',Side.SELL,ask,1000,'market')])

    def test_own_ioc_flow_does_not_trigger_signal(self):
        s,sent=self.bot();s.on_order_book_change(self.snapshot(),[self.trade(1000,'user')])
        self.assertEqual(s._big,0);self.assertEqual(sent,[])

    def test_threshold_and_shadow_gate_are_causal(self):
        s,sent=self.bot();s.on_order_book_change(self.snapshot(),[self.trade(499)])
        self.assertEqual(s._big,0)
        s.on_order_book_change(self.snapshot(1000),[self.trade(500)])
        self.assertEqual(s._big,1);self.assertEqual(sent,[])
        # Shadow bought at 101; its subsequently observed gain is now 11.
        s.on_order_book_change(self.snapshot(2000,111,113),[])
        self.assertEqual(len(sent),1);self.assertEqual(sent[0].quantity,100)

    def test_pending_order_reserves_entire_flip(self):
        s,sent=self.bot();s._pos=-100
        first=s._send(1,101,200)
        self.assertEqual(sent[0].quantity,200)
        self.assertIsNone(s._send(1,101,1))
        s.on_private_order_update(PrivateOrderEvent(timestamp_us=5000,order_id=first,
            status=OrderStatus.PARTIALLY_FILLED,filled_quantity=60,remaining_quantity=140,fill_price=101))
        self.assertEqual(s._pos,-40);self.assertEqual(s._room(1),0)
        s.on_private_order_update(PrivateOrderEvent(timestamp_us=5000,order_id=first,
            status=OrderStatus.CANCELED,remaining_quantity=0))
        self.assertEqual(s._room(1),140)

    def test_one_live_ioc_prevents_duplicate_entry(self):
        s,sent=self.bot();s._big=1;s._shadow_cash=100;s._shadow_pos=0
        s.on_order_book_change(self.snapshot(),[])
        s.on_order_book_change(self.snapshot(1000),[])
        self.assertEqual(len(sent),1)


if __name__=='__main__':unittest.main()
