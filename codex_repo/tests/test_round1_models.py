import unittest

from scripts.check_submission import check
from strategies.round1_best import PassiveStrategy
from simulator.models import BookOrderView,OrderBookSnapshot,Side
from test_strategy import Gateway


def book(now,bq=100,aq=100):
    return OrderBookSnapshot(now,[BookOrderView('b',Side.BUY,99,bq,'market')],
                             [BookOrderView('a',Side.SELL,101,aq,'market')])


class Round1ModelTests(unittest.TestCase):
    def test_documented_submission_checks(self):
        for path in ('strategies/round1_linear_base.py','strategies/round1_ofi_base.py','strategies/round1_best.py'):
            self.assertEqual(check(path),[])

    def test_extended_model_cannot_learn_before_horizon(self):
        s=PassiveStrategy()
        s._observations.append((0,100,(1,0,0,0,0)))
        s._learn(s.HORIZON_US-1,120)
        self.assertEqual(s._labels,0)
        s._learn(s.HORIZON_US,102)
        self.assertEqual(s._labels,1)
        self.assertEqual(s._xy,[2,0,0,0,0])

    def test_five_dimensional_solver_against_known_regularized_system(self):
        s=PassiveStrategy()
        s._labels=s.MIN_LABELS
        s._mass=0
        s._xx=[[0.0]*5 for _ in range(5)]
        for i in range(5):s._xx[i][i]=10
        # Ridge floor is 10, so a diagonal 10 matrix gives beta = xy / 20.
        s._xy=[20,40,60,80,100]
        s._learn(0,100)
        self.assertEqual(s._weights,[1,2,3,4,5])

    def test_order_flow_imbalance_sign_and_dimensions(self):
        s=PassiveStrategy();Gateway(s)
        s.on_order_book_change(book(0),[])
        s.on_order_book_change(book(100000,bq=200),[])
        self.assertGreater(s._ofi,0)
        self.assertEqual(len(s._observations[-1][2]),5)
        s.on_order_book_change(book(200000,bq=200,aq=400),[])
        self.assertLess(s._ofi,0)

    def test_actual_submission_reserves_both_sides_at_all_inventory_states(self):
        for inventory in range(-100,101):
            s=PassiveStrategy();Gateway(s)
            s.inventory=inventory
            s._quote(0,1,99);s._quote(0,-1,101)
            buys=sum(r[2] for r in s._orders.values() if r[0]>0)
            sells=sum(r[2] for r in s._orders.values() if r[0]<0)
            self.assertLessEqual(inventory+buys,100)
            self.assertGreaterEqual(inventory-sells,-100)


if __name__=='__main__':unittest.main()
