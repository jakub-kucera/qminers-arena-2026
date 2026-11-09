import unittest
import csv
import tempfile
from pathlib import Path

from scripts.check_submission import check
from strategies.guarded_strategy import GuardedStrategy
from strategies.passive_strategy import PassiveStrategy
from simulator.models import PrivateOrderEvent, OrderStatus, Side, BookOrderView, OrderBookSnapshot
from scripts.perf_check import generate_dense
from test_strategy import Gateway, replay, snapshot


def event(order_id,status,quantity=0,remaining=0,price=101):
    return PrivateOrderEvent(timestamp_us=5000,order_id=order_id,status=status,
        filled_quantity=quantity,remaining_quantity=remaining,fill_price=price)


class CandidatesTests(unittest.TestCase):
    def test_dense_tape_has_sustained_aggression(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'dense.csv'
            generate_dense(path,10000)
            with path.open() as file:
                rows=list(csv.DictReader(file))
            self.assertEqual(len(rows),10000)
            self.assertTrue(any(r['Lifespan']=='F' for r in rows[2000:4000]))
            self.assertTrue(any(r['Lifespan']=='F' for r in rows[-2000:]))

    def test_submission_files(self):
        for name in ('guarded','passive'):
            self.assertEqual(check('strategies/'+name+'_strategy.py'),[])

    def test_guard_pauses_and_recovers_from_virtual_outcomes(self):
        s=GuardedStrategy()
        # Scoring continues without orders or fills, including during a pause.
        for n in range(100):
            s._guard_pending.append((n*100_000,100,2,1))
            s._guard_update(n*100_000+s.HORIZON_US,99,2)
        self.assertEqual(s._guard_scale,0)
        self.assertEqual(s.inventory,0)
        for n in range(100,600):
            s._guard_pending.append((n*100_000,100,2,1))
            s._guard_update(n*100_000+s.HORIZON_US,108,2)
        self.assertGreater(s._guard_scale,0.9)

    def test_guard_cap_does_not_repeatedly_shrink_existing_target(self):
        s=GuardedStrategy()
        g=Gateway(s)
        s._guard_scale=0.5
        s.inventory=40
        s._send_toward(0,40,99,101,100,100)
        self.assertFalse(g.sent)
        s._guard_scale=0
        s._send_toward(20_000,40,99,101,100,100)
        self.assertEqual(g.sent[-1].side,Side.SELL)

    def test_passive_cancel_reserves_and_fill_race_does_not_resurrect(self):
        s=PassiveStrategy()
        g=Gateway(s)
        cancels=[]
        s._ctx.cancel_order=cancels.append
        s._quote(0,1,99)
        order_id=next(iter(s._orders))
        s.on_private_order_update(event(order_id,OrderStatus.ACCEPTED,remaining=5))
        s._quote(50_000,1,98)
        s._quote(60_000,1,97)
        self.assertEqual(cancels,[order_id])
        self.assertEqual(len(g.sent),1)
        self.assertEqual(s._orders[order_id][2],5)
        s.on_private_order_update(event(order_id,OrderStatus.FILLED,quantity=5,price=99))
        s.on_private_order_update(event(order_id,OrderStatus.REJECTED))
        self.assertFalse(s._orders)
        self.assertEqual(s.inventory,5)
        self.assertEqual(s.cash,-495)

    def test_passive_partial_then_cancel_releases_only_remaining(self):
        s=PassiveStrategy()
        Gateway(s)
        s._quote(0,-1,101)
        order_id=next(iter(s._orders))
        s.on_private_order_update(event(order_id,OrderStatus.ACCEPTED,remaining=5))
        s.on_private_order_update(event(order_id,OrderStatus.PARTIALLY_FILLED,quantity=2,remaining=3))
        self.assertEqual(s._orders[order_id][2],3)
        self.assertEqual(s.inventory,-2)
        s.on_private_order_update(event(order_id,OrderStatus.CANCELED,remaining=3))
        self.assertFalse(s._orders)
        self.assertEqual(s.inventory,-2)

    def test_passive_tracks_deeper_queue_and_keeps_stable_priority(self):
        s=PassiveStrategy()
        g=Gateway(s)
        s._quote(0,1,98)
        oid=next(iter(s._orders))
        s.on_private_order_update(event(oid,OrderStatus.ACCEPTED,remaining=5))
        bids=[BookOrderView('best',Side.BUY,99,10,'market'),
              BookOrderView('ahead',Side.BUY,98,7,'market'),
              BookOrderView(oid,Side.BUY,98,5,'user'),
              BookOrderView('behind',Side.BUY,98,20,'market')]
        asks=[BookOrderView('a',Side.SELL,101,10,'market')]
        # At inventory 30 the skew places the desired bid at 98.
        s.inventory=30
        s.on_order_book_change(OrderBookSnapshot(10000,bids,asks),[])
        self.assertEqual(s.queue_ahead[oid],7)
        self.assertFalse(s._orders[oid][4])
        s.on_order_book_change(OrderBookSnapshot(20000,bids,asks),[])
        self.assertEqual(len(g.sent),2)

    def test_passive_ledger_and_limit_in_real_matching_engine(self):
        s=PassiveStrategy()
        rows='0.000000,Insert,b,B,10,99,G\n0.000001,Insert,a,A,10,101,G\n'
        rows+=''.join(f'{n/100:.6f},Insert,t{n},A,15,99,F\n' for n in range(1,100))
        engine,result=replay(s,rows)
        self.assertEqual(s.inventory,result.inventory)
        self.assertEqual(s.cash,result.cash)
        self.assertEqual(result.breach_penalty,0)
        self.assertLessEqual(max(engine._abs_inventory_time_us),s.POSITION_LIMIT)


if __name__=='__main__':
    unittest.main()
