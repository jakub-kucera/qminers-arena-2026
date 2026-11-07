import random
import unittest

from scripts.check_submission import check
from simulator.models import BookOrderView, OrderBookSnapshot, OrderStatus, PrivateOrderEvent, Side
from strategies.round1_depth_524k import PassiveStrategy as DepthStrategy
from strategies.round1_depth_nonlinear_534k import PassiveStrategy as NonlinearDepthStrategy
from strategies.round1_nonlinear_498k import PassiveStrategy as NonlinearStrategy
from strategies.round1_queue_545k import PassiveStrategy as QueueStrategy
from strategies.round1_inside_551k import PassiveStrategy as InsideStrategy
from strategies.round1_private_554k import PassiveStrategy as PrivateStrategy
from strategies.round1_submission import PassiveStrategy as SubmissionStrategy
from strategies.round1_size_555389 import PassiveStrategy as SizeStrategy
from test_strategy import Gateway


class PreservedRound1Tests(unittest.TestCase):
    def test_mature_labels_and_solver_for_expanded_models(self):
        for cls in (NonlinearStrategy, DepthStrategy, NonlinearDepthStrategy, QueueStrategy, InsideStrategy, PrivateStrategy, SubmissionStrategy, SizeStrategy):
            with self.subTest(model=cls.__name__, dimensions=cls.FEATURE_COUNT):
                s = cls()
                features = (1,) + (0,) * (s.FEATURE_COUNT - 1)
                s._observations.append((0, 100, features))
                s._learn(s.HORIZON_US - 1, 102)
                self.assertEqual(s._labels, 0)
                s._learn(s.HORIZON_US, 102)
                self.assertEqual(s._xy, [2] + [0] * (s.FEATURE_COUNT - 1))
                s._labels = s.MIN_LABELS
                s._mass = 0
                s._xx = [[10.0 if i == j else 0 for j in range(s.FEATURE_COUNT)]
                         for i in range(s.FEATURE_COUNT)]
                s._xy = [20.0 * (i + 1) for i in range(s.FEATURE_COUNT)]
                s._learn(s.HORIZON_US + 1, 102)
                self.assertEqual(s._weights, list(range(1, s.FEATURE_COUNT + 1)))

    def test_robust_depth_ignores_user_orders_and_distant_liquidity(self):
        def features(extra):
            s = DepthStrategy()
            Gateway(s)
            bids = [BookOrderView('b1', Side.BUY, 99, 10000, 'market'),
                    BookOrderView('b2', Side.BUY, 99, 50, 'market')]
            asks = [BookOrderView('a1', Side.SELL, 101, 100, 'market')]
            bids += extra
            s.on_order_book_change(OrderBookSnapshot(0, bids, asks), [])
            return s._observations[-1][2]
        baseline = features([])
        self.assertAlmostEqual(baseline[8], 1 / 3)
        # Capping each order at 100 makes the 10,000-lot order count as 100.
        self.assertAlmostEqual(baseline[9], 0.2)
        changed = features([BookOrderView('own', Side.BUY, 98, 200, 'user'),
                            BookOrderView('far', Side.BUY, 96, 90000, 'market')])
        self.assertEqual(changed, baseline)

    def test_preserved_models_pass_rules_and_reserve_all_inventory_states(self):
        for path, cls in (
            ('strategies/round1_nonlinear_498k.py', NonlinearStrategy),
            ('strategies/round1_depth_524k.py', DepthStrategy),
            ('strategies/round1_depth_nonlinear_534k.py', NonlinearDepthStrategy),
            ('strategies/round1_queue_545k.py', QueueStrategy),
            ('strategies/round1_inside_551k.py', InsideStrategy),
            ('strategies/round1_private_554k.py', PrivateStrategy),
            ('strategies/round1_submission.py', SubmissionStrategy),
            ('strategies/round1_private_554347.py', SubmissionStrategy),
            ('strategies/round1_size_555389.py', SizeStrategy),
        ):
            self.assertEqual(check(path), [])
            for inventory in range(-100, 101):
                s = cls()
                Gateway(s)
                s.inventory = inventory
                s._quote(0, 1, 99)
                s._quote(0, -1, 101)
                buys = sum(r[2] for r in s._orders.values() if r[0] > 0)
                sells = sum(r[2] for r in s._orders.values() if r[0] < 0)
                self.assertLessEqual(inventory + buys, 100)
                self.assertGreaterEqual(inventory - sells, -100)

    def test_size_buckets_separate_touch_and_deeper_liquidity(self):
        s=SizeStrategy();Gateway(s)
        bids=[BookOrderView('b'+str(i),Side.BUY,99,q,'market') for i,q in enumerate((2,15,50,250))]
        asks=[BookOrderView('a1',Side.SELL,101,3,'market'),
              BookOrderView('a2',Side.SELL,101,100,'market'),
              BookOrderView('a3',Side.SELL,102,250,'market')]
        s.on_order_book_change(OrderBookSnapshot(0,bids,asks),[])
        features=s._observations[-1][2]
        self.assertEqual(len(features),23)
        self.assertEqual(features[15:19],(0,1,0,1))
        self.assertEqual(features[19:23],(0,1,0,0))

    def test_inside_quotes_require_spread_and_edge_and_never_cross(self):
        for spread, weight, inventory, expected_buy, expected_sell in (
            (1, 1.0, 0, 100, 102),
            (2, 0.5, 0, 100, 102),  # Prediction exactly 0.25: no improvement.
            (2, 1.0, 0, 101, 102),
            (2, -1.0, 0, 100, 101),
            (3, 1.0, 0, 101, 103),
            (2, 1.0, 100, None, 102),
        ):
            s = InsideStrategy()
            gateway = Gateway(s)
            s.inventory = inventory
            s._labels = s.MIN_LABELS
            s._last_fit_us = 0
            s._weights[2] = weight
            snapshot = OrderBookSnapshot(1,
                [BookOrderView('b', Side.BUY, 100, 300, 'market')],
                [BookOrderView('a', Side.SELL, 100+spread, 100, 'market')])
            s.on_order_book_change(snapshot, [])
            buys = [r for r in gateway.sent if r.side == Side.BUY]
            sells = [r for r in gateway.sent if r.side == Side.SELL]
            self.assertEqual(buys[0].price if buys else None, expected_buy)
            self.assertEqual(sells[0].price if sells else None, expected_sell)
            for order in buys:
                self.assertLess(order.price, 100+spread)
            for order in sells:
                self.assertGreater(order.price, 100)
            self.assertLessEqual(inventory+sum(r.quantity for r in buys), 100)
            self.assertGreaterEqual(inventory-sum(r.quantity for r in sells), -100)

    def test_private_cancel_replenishes_only_from_fresh_valid_quotes(self):
        for canceled_at, invalidate, expected_orders in (
            (15000, False, 3), (15001, False, 2), (12000, True, 2),
        ):
            s = SubmissionStrategy()
            gateway = Gateway(s)
            s._ctx.cancel_order = lambda oid: None
            s._quote(0, 1, 99)
            s._quote(0, -1, 101)
            for oid, r in list(s._orders.items()):
                s.on_private_order_update(PrivateOrderEvent(timestamp_us=5000, order_id=oid,
                    status=OrderStatus.ACCEPTED, remaining_quantity=r[2]))
            buy_id = next(oid for oid, r in s._orders.items() if r[0] == 1)
            s._desired_buy, s._desired_sell, s._desired_time = 99, 101, 10000
            s._cancel(buy_id)
            if invalidate:
                s.on_order_book_change(OrderBookSnapshot(11000, [], []), [])
                self.assertIsNone(s._desired_time)
            s.on_private_order_update(PrivateOrderEvent(timestamp_us=canceled_at, order_id=buy_id,
                status=OrderStatus.CANCELED, remaining_quantity=100))
            self.assertEqual(len(gateway.sent), expected_orders)
            self.assertLessEqual(s.inventory+sum(r[2] for r in s._orders.values() if r[0] > 0), 100)

    def test_private_partial_fill_updates_ledger_without_using_cached_quotes(self):
        s = SubmissionStrategy()
        gateway = Gateway(s)
        s._quote(0, 1, 99)
        oid = next(iter(s._orders))
        s.on_private_order_update(PrivateOrderEvent(timestamp_us=5000, order_id=oid,
            status=OrderStatus.ACCEPTED, remaining_quantity=100))
        s._desired_buy, s._desired_sell, s._desired_time = 99, 101, 10000
        s.on_private_order_update(PrivateOrderEvent(timestamp_us=12000, order_id=oid,
            status=OrderStatus.PARTIALLY_FILLED, filled_quantity=40, remaining_quantity=60, fill_price=99))
        self.assertEqual((s.inventory, s.cash), (40, -3960))
        self.assertEqual(len(gateway.sent), 1)

    def test_selected_submission_inside_threshold_is_strict_in_both_directions(self):
        for weight, expected_buy, expected_sell in (
            (0.6, 100, 102), (0.60002, 101, 102),
            (-0.6, 100, 102), (-0.60002, 100, 101),
        ):
            s = SubmissionStrategy()
            gateway = Gateway(s)
            s._labels = s.MIN_LABELS
            s._last_fit_us = 0
            s._weights[2] = weight
            s.on_order_book_change(OrderBookSnapshot(1,
                [BookOrderView('b', Side.BUY, 100, 300, 'market')],
                [BookOrderView('a', Side.SELL, 102, 100, 'market')]), [])
            self.assertEqual(next(r.price for r in gateway.sent if r.side == Side.BUY), expected_buy)
            self.assertEqual(next(r.price for r in gateway.sent if r.side == Side.SELL), expected_sell)

    def test_overlapping_replacements_reserve_pending_cancels_and_survive_fill_races(self):
        s = QueueStrategy()
        Gateway(s)
        s._ctx.cancel_order = lambda oid: None
        rng = random.Random(544764)
        inventory = cash = 0
        for n in range(10000):
            now = n * 1000
            for oid, r in list(s._orders.items()):
                if not r[3] and rng.random() < 0.3:
                    status = OrderStatus.REJECTED if rng.random() < 0.03 else OrderStatus.ACCEPTED
                    s.on_private_order_update(PrivateOrderEvent(timestamp_us=now, order_id=oid,
                        status=status, remaining_quantity=r[2]))
            accepted = [oid for oid, r in s._orders.items() if r[3]]
            if accepted and rng.random() < 0.7:
                oid = rng.choice(accepted)
                r = s._orders[oid]
                fill = rng.randint(1, r[2])
                remaining = r[2] - fill
                inventory += r[0] * fill
                cash -= r[0] * fill * r[1]
                s.on_private_order_update(PrivateOrderEvent(timestamp_us=now, order_id=oid,
                    status=OrderStatus.FILLED if remaining == 0 else OrderStatus.PARTIALLY_FILLED,
                    filled_quantity=fill, remaining_quantity=remaining, fill_price=r[1]))
                if remaining == 0:
                    # A late reject must not resurrect an order filled while its cancel travelled.
                    s.on_private_order_update(PrivateOrderEvent(timestamp_us=now, order_id=oid,
                        status=OrderStatus.REJECTED))
            for oid, r in list(s._orders.items()):
                if r[4] and rng.random() < 0.15:
                    status = OrderStatus.REJECTED if rng.random() < 0.05 else OrderStatus.CANCELED
                    s.on_private_order_update(PrivateOrderEvent(timestamp_us=now, order_id=oid,
                        status=status, remaining_quantity=r[2]))
            shift = rng.randint(-2, 2)
            s._quote(now, 1, None if rng.random() < 0.05 else 99 + shift)
            s._quote(now, -1, None if rng.random() < 0.05 else 101 + shift)
            self.assertEqual((s.inventory, s.cash), (inventory, cash))
            buys = sum(r[2] for r in s._orders.values() if r[0] > 0)
            sells = sum(r[2] for r in s._orders.values() if r[0] < 0)
            self.assertLessEqual(inventory + buys, 100)
            self.assertGreaterEqual(inventory - sells, -100)
            for sign in (1, -1):
                self.assertLessEqual(sum(r[0] == sign for r in s._orders.values()), 8)


if __name__ == '__main__':
    unittest.main()
