import random
import unittest

from scripts.check_submission import check
from simulator.models import OrderStatus,PrivateOrderEvent
from strategies.passive_v2_champion import PassiveStrategy
from test_strategy import Gateway


class ChampionTests(unittest.TestCase):
    def test_submission_restrictions(self):
        self.assertEqual(check('strategies/passive_v2_champion.py'),[])

    def test_replenishment_preserves_older_order_and_reserves_total_exposure(self):
        s=PassiveStrategy();g=Gateway(s)
        s._quote(0,1,99);s._quote(0,-1,101)
        original_buy=next(oid for oid,r in s._orders.items() if r[0]==1)
        original_sell=next(oid for oid,r in s._orders.items() if r[0]==-1)
        for oid,r in list(s._orders.items()):
            s.on_private_order_update(PrivateOrderEvent(timestamp_us=5000,order_id=oid,
                status=OrderStatus.ACCEPTED,remaining_quantity=r[2]))
        s.on_private_order_update(PrivateOrderEvent(timestamp_us=6000,order_id=original_sell,
            status=OrderStatus.PARTIALLY_FILLED,filled_quantity=20,remaining_quantity=80,fill_price=101))
        s._quote(10000,1,99)
        self.assertIn(original_buy,s._orders)
        self.assertFalse(s._orders[original_buy][4])
        self.assertEqual(len(g.sent),3)
        self.assertEqual(s.inventory,-20)
        self.assertEqual(sum(r[2] for r in s._orders.values() if r[0]>0),120)

    def test_randomized_layer_fills_and_cancels_preserve_ledger_and_bounds(self):
        s=PassiveStrategy();Gateway(s)
        s._ctx.cancel_order=lambda oid:None
        rng=random.Random(1907)
        inventory=cash=0
        for n in range(10000):
            now=n*10000
            for oid,r in list(s._orders.items()):
                if not r[3]:
                    s.on_private_order_update(PrivateOrderEvent(timestamp_us=now,order_id=oid,
                        status=OrderStatus.ACCEPTED,remaining_quantity=r[2]))
            if s._orders:
                oid=rng.choice(list(s._orders));r=s._orders[oid]
                fill=rng.randint(1,r[2]);remaining=r[2]-fill
                inventory+=r[0]*fill;cash-=r[0]*fill*r[1]
                s.on_private_order_update(PrivateOrderEvent(timestamp_us=now,order_id=oid,
                    status=OrderStatus.FILLED if remaining==0 else OrderStatus.PARTIALLY_FILLED,
                    filled_quantity=fill,remaining_quantity=remaining,fill_price=r[1]))
            for oid,r in list(s._orders.items()):
                if r[4]:
                    s.on_private_order_update(PrivateOrderEvent(timestamp_us=now,order_id=oid,
                        status=OrderStatus.CANCELED,remaining_quantity=r[2]))
            if rng.random()<.05:
                s._quote(now,1,None);s._quote(now,-1,None)
            else:
                s._quote(now,1,99);s._quote(now,-1,101)
            self.assertEqual((s.inventory,s.cash),(inventory,cash))
            buys=sum(r[2] for r in s._orders.values() if r[0]>0)
            sells=sum(r[2] for r in s._orders.values() if r[0]<0)
            self.assertLessEqual(inventory+buys,100)
            self.assertGreaterEqual(inventory-sells,-100)
            for sign in (1,-1):
                self.assertLessEqual(sum(r[0]==sign for r in s._orders.values()),4)


if __name__=='__main__':unittest.main()
