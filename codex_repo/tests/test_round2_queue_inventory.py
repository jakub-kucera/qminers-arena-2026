import tempfile
import unittest
from pathlib import Path

from scripts.round2_queue_inventory import queue_inventory
from simulator.main import load_strategy_from_file
from simulator.models import OrderStatus,PrivateOrderEvent
from test_strategy import Gateway


class QueueInventoryTests(unittest.TestCase):
    def strategy(self):
        source=queue_inventory(Path('strategies/round2/round2_transfer.py').read_text(),25,150)
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'s.py';p.write_text(source);s=load_strategy_from_file(p)
        g=Gateway(s);self.modified=[];self.canceled=[]
        s._ctx.modify_order=lambda oid,q:self.modified.append((oid,q))
        s._ctx.cancel_order=self.canceled.append
        s._upper_target=100;s._quote(0,1,99)
        oid=next(iter(s._orders));s._orders[oid][3]=True
        return s,g,oid

    def test_shrink_retains_real_reservation_until_ack(self):
        s,g,oid=self.strategy();s._upper_target=25;s._quote(6000,1,99)
        self.assertEqual(self.modified,[(oid,25)])
        self.assertEqual(self.canceled,[])
        self.assertEqual(s._orders[oid][2],100)
        self.assertEqual(len(g.sent),1)
        s._quote(7000,1,99)
        self.assertEqual(len(self.modified),1)
        s.on_private_order_update(PrivateOrderEvent(timestamp_us=11000,order_id=oid,
            status=OrderStatus.MODIFIED,remaining_quantity=25))
        self.assertEqual(s._orders[oid][2],25)
        self.assertNotIn(oid,s._modify_pending)

    def test_fill_race_and_rejected_modify_preserve_ledger(self):
        s,g,oid=self.strategy();s._upper_target=25;s._quote(6000,1,99)
        s.on_private_order_update(PrivateOrderEvent(timestamp_us=7000,order_id=oid,
            status=OrderStatus.PARTIALLY_FILLED,filled_quantity=90,fill_price=99,remaining_quantity=10))
        s.on_private_order_update(PrivateOrderEvent(timestamp_us=11000,order_id=oid,
            status=OrderStatus.REJECTED,remaining_quantity=10))
        self.assertEqual((s.inventory,s.cash,s._orders[oid][2]),(90,-8910,10))
        self.assertFalse(s._orders[oid][4])
        self.assertNotIn(oid,s._modify_pending)

    def test_cancel_waits_for_pending_modify(self):
        s,g,oid=self.strategy();s._upper_target=25;s._quote(6000,1,99)
        s._quote(7000,1,None)
        self.assertEqual(self.canceled,[])
        s.on_private_order_update(PrivateOrderEvent(timestamp_us=11000,order_id=oid,
            status=OrderStatus.MODIFIED,remaining_quantity=25))
        s._quote(12000,1,None)
        self.assertEqual(self.canceled,[oid])


if __name__=='__main__':unittest.main()
