import unittest
import tempfile
from pathlib import Path
from simulator.models import OrderRequest,OrderType,OrderStatus,Side
from simulator.models import PrivateOrderEvent
from simulator.main import load_strategy_from_file
from simulator.strategy import BaseStrategy
from test_strategy import replay,Gateway
from scripts.round1_overbooked_depth import source_for


class PendingCancelTests(unittest.TestCase):
    def test_cancel_sent_before_ack_arrives_after_original_acceptance(self):
        class Strategy(BaseStrategy):
            def __init__(self):
                super().__init__();self.oid=None;self.canceled=False;self.events=[]
            def on_order_book_change(self,snapshot,trades):
                if self.oid is None and snapshot.bids and snapshot.asks:
                    self.oid=self.send_order(OrderRequest(side=Side.BUY,price=99,quantity=10,order_type=OrderType.LIMIT))
                elif self.oid is not None and not self.canceled and snapshot.timestamp_us>=2000:
                    self.cancel_order(self.oid);self.canceled=True
            def on_private_order_update(self,event):
                self.events.append((event.status,event.timestamp_us))
        s=Strategy()
        _,result=replay(s,'''0.000000,Insert,b,B,100,99,G
0.000001,Insert,a,A,100,101,G
0.002000,Insert,b2,B,10,98,G
0.010000,Cancel,unknown,,,,
''')
        self.assertEqual(s.events,[(OrderStatus.ACCEPTED,5001),(OrderStatus.CANCELED,7000)])
        self.assertEqual(result.inventory,0)
        self.assertEqual(result.breach_penalty,0)

    def test_cancel_rejection_before_acceptance_preserves_original_request(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'candidate.py';path.write_text(source_for(1,50))
            s=load_strategy_from_file(path)
        g=Gateway(s);cancels=[];s._ctx.cancel_order=cancels.append
        oid=s.send_order(OrderRequest(side=Side.BUY,price=9999,quantity=7,order_type=OrderType.LIMIT))
        s._orders[oid]=[1,9999,7,False,False,4968504,None]
        s._cancel(oid)
        s.on_private_order_update(PrivateOrderEvent(timestamp_us=4973504,order_id=oid,
            status=OrderStatus.REJECTED,message='cancel rejected: no resting order with this id'))
        self.assertIn(oid,s._orders)
        self.assertEqual(s._orders[oid][2],7)
        s.on_private_order_update(PrivateOrderEvent(timestamp_us=4973504,order_id=oid,
            status=OrderStatus.ACCEPTED,remaining_quantity=7))
        self.assertEqual(cancels,[oid,oid])
        s.on_private_order_update(PrivateOrderEvent(timestamp_us=6721064,order_id=oid,
            status=OrderStatus.FILLED,filled_quantity=7,remaining_quantity=0,fill_price=9999))
        self.assertEqual((s.inventory,s.cash),(7,-69993))
        self.assertNotIn(oid,s._orders)
        self.assertNotIn(oid,s._cancel_requested)


if __name__=='__main__':unittest.main()
