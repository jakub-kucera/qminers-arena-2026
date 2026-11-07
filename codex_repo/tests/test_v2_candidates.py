import unittest

from scripts.check_submission import check
from simulator.main import load_strategy_from_file
from simulator.models import OrderStatus, PrivateOrderEvent
from test_strategy import Gateway


class V2CandidateTests(unittest.TestCase):
    def test_standalone_candidates_pass_documented_checks(self):
        for size in (20,60,90):
            self.assertEqual(check(f'strategies/passive_v2_q{size}.py'),[])

    def test_all_inventory_states_reserve_both_sides_without_breaching_cap(self):
        for size in (20,60,90):
            path=f'strategies/passive_v2_q{size}.py'
            prototype=load_strategy_from_file(path)
            constructor=prototype.__class__
            cap=prototype.POSITION_LIMIT
            for inventory in range(-cap,cap+1):
                s=constructor()
                gateway=Gateway(s)
                cancels=[]
                s._ctx.cancel_order=cancels.append
                s.inventory=inventory
                s._quote(0,1,99)
                s._quote(0,-1,101)
                buys=sum(r[2] for r in s._orders.values() if r[0]>0)
                sells=sum(r[2] for r in s._orders.values() if r[0]<0)
                self.assertLessEqual(inventory+buys,cap)
                self.assertGreaterEqual(inventory-sells,-cap)
                for oid,record in list(s._orders.items()):
                    s.on_private_order_update(PrivateOrderEvent(timestamp_us=5000,
                        order_id=oid,status=OrderStatus.ACCEPTED,remaining_quantity=record[2]))
                    s._quote(60000,record[0],record[1]-record[0])
                    self.assertTrue(record[4])
                # Cancellation requests cannot release the reservation or
                # create replacement orders before acknowledgement.
                before=len(gateway.sent)
                s._quote(70000,1,98)
                s._quote(70000,-1,102)
                for sign in (1,-1):
                    if not any(r[0]==sign for r in s._orders.values()):
                        self.assertEqual(inventory,sign*cap)
                self.assertEqual(len(gateway.sent),before)


if __name__=='__main__':
    unittest.main()
