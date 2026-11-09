import random
import tempfile
import unittest
from pathlib import Path

from scripts.check_submission import check
from simulator.models import BookOrderView, OrderBookSnapshot, OrderStatus, PrivateOrderEvent, Side, Trade
from simulator.simulator import ExchangeSimulator, SimulationConfig
from simulator.strategy import StrategyContext
from strategies.arena_strategy import ArenaStrategy
from strategies.trend_follower import TrendFollowerStrategy


RISK_CONFIG = dict(max_position=100, max_potential_position=1000,
                  position_breach_penalty_per_second=10000, order_accept_delay_ms=5)
HEADER = 'Time,Operation,OrderId,Side,Volume,Price,Lifespan\n'
ROOT = Path(__file__).resolve().parents[1]


class Gateway:
    def __init__(self, strategy):
        self.sent = []
        strategy._attach_context(StrategyContext(self.submit, self.unused, self.unused, lambda: 0))

    def submit(self, request):
        self.sent.append(request)
        return f'u{len(self.sent):09d}'

    def unused(self, *args):
        raise AssertionError('IOC strategy must not cancel/modify')


def snapshot(now, bid=99, ask=101):
    return OrderBookSnapshot(timestamp_us=now,
        bids=[] if bid is None else [BookOrderView('b', Side.BUY, bid, 100, 'market')],
        asks=[] if ask is None else [BookOrderView('a', Side.SELL, ask, 100, 'market')])


def replay(strategy, rows):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'tape.csv'
        path.write_text(HEADER + rows)
        engine = ExchangeSimulator(strategy, SimulationConfig(**RISK_CONFIG))
        result = engine.run(path)
    return engine, result


class StrategyTests(unittest.TestCase):
    def test_submission_checks(self):
        self.assertEqual(check(ROOT/'strategies/arena_strategy.py'), [])
        self.assertEqual(check(ROOT/'strategies/trend_follower.py'), [])

    def test_documented_starter_cancel_repair(self):
        strategy = TrendFollowerStrategy()
        engine, result = replay(strategy, '''0.000000,Insert,b,B,20,99,G
0.000001,Insert,a,A,20,101,G
0.010000,Insert,t1,B,1,101,F
0.011000,Cancel,a,,,,
0.012000,Insert,a2,A,20,102,G
0.020000,Insert,t2,B,1,102,F
0.030000,Insert,t3,A,1,99,F
0.040000,Cancel,unknown,,,,
''')
        self.assertGreater(engine._user_order_seq, 1)
        self.assertFalse(strategy._order_in_flight)
        self.assertEqual(result.breach_penalty, 0)

    def test_partial_fill_cancel_and_retry_reserve_capacity(self):
        s = ArenaStrategy()
        g = Gateway(s)
        s.inventory = 75
        s._send_toward(0, 1000, 99, 101, 100, 100)
        self.assertEqual(g.sent[-1].quantity, 5)
        s._send_toward(30_000, -80, 99, 101, 100, 100)
        self.assertEqual(len(g.sent), 1)
        order_id = s._pending_id
        s.on_private_order_update(PrivateOrderEvent(timestamp_us=5000, order_id=order_id,
            status=OrderStatus.PARTIALLY_FILLED, filled_quantity=2, fill_price=101, remaining_quantity=3))
        self.assertEqual(s.inventory, 77)
        self.assertEqual(s.cash, -202)
        self.assertEqual(s._pending_remaining, 3)
        s._send_toward(40_000, 80, 99, 101, 100, 100)
        self.assertEqual(len(g.sent), 1)
        s.on_private_order_update(PrivateOrderEvent(timestamp_us=5000, order_id=order_id,
            status=OrderStatus.CANCELED, remaining_quantity=3))
        s._send_toward(50_000, 80, 99, 101, 100, 100)
        self.assertEqual(g.sent[-1].quantity, 3)

    def test_foreign_rejection_does_not_release_reservation(self):
        s = ArenaStrategy()
        Gateway(s)
        s._send_toward(0, 80, 99, 101, 100, 100)
        original = s._pending_id
        s.on_private_order_update(PrivateOrderEvent(timestamp_us=5000, order_id='other', status=OrderStatus.REJECTED))
        self.assertEqual(s._pending_id, original)
        s.on_private_order_update(PrivateOrderEvent(timestamp_us=5000, order_id=original, status=OrderStatus.REJECTED))
        self.assertIsNone(s._pending_id)
        self.assertEqual(s.inventory, 0)

    def test_random_partial_fill_accounting_and_exposure(self):
        rng = random.Random(3519)
        s = ArenaStrategy()
        g = Gateway(s)
        inventory = cash = 0
        for n in range(10_000):
            s._send_toward(n * 30_000, rng.randint(-200, 200), 99, 101, rng.randint(1, 80), rng.randint(1, 80))
            if s._pending_id is None:
                continue
            request = g.sent[-1]
            sign = 1 if request.side == Side.BUY else -1
            self.assertLessEqual(abs(inventory + sign * request.quantity), s.POSITION_LIMIT)
            self.assertLessEqual(request.quantity, s.MAX_ORDER_SIZE)
            order_id = s._pending_id
            remaining = request.quantity
            while remaining and rng.random() < 0.75:
                fill = rng.randint(1, remaining)
                remaining -= fill
                inventory += sign * fill
                cash -= sign * fill * request.price
                s.on_private_order_update(PrivateOrderEvent(timestamp_us=n*30_000+5000,
                    order_id=order_id, status=OrderStatus.FILLED if not remaining else OrderStatus.PARTIALLY_FILLED,
                    filled_quantity=fill, remaining_quantity=remaining, fill_price=request.price))
                self.assertEqual(s.inventory, inventory)
                self.assertEqual(s.cash, cash)
                self.assertLessEqual(abs(s.inventory), s.POSITION_LIMIT)
            if remaining:
                s.on_private_order_update(PrivateOrderEvent(timestamp_us=n*30_000+5000,
                    order_id=order_id, status=OrderStatus.CANCELED, remaining_quantity=remaining))
            self.assertIsNone(s._pending_id)

    def test_labels_cannot_mature_early_and_stale_labels_are_dropped(self):
        s = ArenaStrategy()
        s._observations.append((0, 100, (1.0, 0.0, 0.0)))
        s._learn(s.HORIZON_US - 1, 1000)
        self.assertEqual(s._labels, 0)
        s._learn(s.HORIZON_US, 102)
        self.assertEqual(s._labels, 1)
        self.assertEqual(s._xy[0], 2)
        s._observations.append((0, 100, (1.0, 0.0, 0.0)))
        s._learn(10_000_000, 1000)
        self.assertEqual(s._labels, 1)

    def test_own_trades_do_not_drive_flow(self):
        s = ArenaStrategy()
        Gateway(s)
        trade = Trade(timestamp_us=10000, price=101, quantity=20, taker_order_id='u1',
                      maker_order_id='a', taker_owner='user', maker_owner='market', book_side='ask')
        s.on_order_book_change(snapshot(10000), [trade])
        self.assertEqual(s._flow_net, 0)
        self.assertIsNone(s._last_market_trade_us)

    def test_transient_empty_side_waits_but_persistent_side_reduces(self):
        s = ArenaStrategy()
        g = Gateway(s)
        s.inventory = 20
        s.on_order_book_change(snapshot(0, ask=None), [])
        self.assertFalse(g.sent)
        s.on_order_book_change(snapshot(100_000, ask=None), [])
        self.assertEqual(g.sent[-1].side, Side.SELL)
        self.assertEqual(g.sent[-1].quantity, 20)

    def test_no_orders_before_warmup_or_on_flat_market(self):
        s = ArenaStrategy()
        g = Gateway(s)
        for n in range(2000):
            s.on_order_book_change(snapshot(n * 100_000), [])
        self.assertGreater(s._labels, s.MIN_LABELS)
        self.assertFalse(g.sent)
        self.assertLessEqual(len(s._observations), 64)

    def test_full_simulator_accounting_and_risk(self):
        class Directed(ArenaStrategy):
            def on_order_book_change(self, snap, trades):
                if snap.bids and snap.asks:
                    target = 80 if snap.timestamp_us < 100_000 else -80
                    self._send_toward(snap.timestamp_us, target, 99, 101, 500, 500)
        s = Directed()
        rows = '0.000000,Insert,b,B,500,99,G\n0.000001,Insert,a,A,500,101,G\n'
        rows += ''.join(f'{n/1000:.6f},Cancel,unknown,,,,\n' for n in range(10, 500, 10))
        engine, result = replay(s, rows)
        self.assertEqual(result.inventory, -80)
        self.assertEqual(result.inventory, s.inventory)
        self.assertEqual(result.cash, s.cash)
        self.assertEqual(result.breach_penalty, 0)
        self.assertLessEqual(max(engine._abs_inventory_time_us), 80)
        self.assertIsNone(s._pending_id)

    def test_oversized_ioc_partially_fills_then_releases_in_engine(self):
        class Once(ArenaStrategy):
            def on_order_book_change(self, snap, trades):
                if snap.timestamp_us == 1:
                    self._send_toward(1, 80, 99, 101, 50, 50)
        s = Once()
        engine, result = replay(s, '0.000000,Insert,b,B,50,99,G\n0.000001,Insert,a,A,3,101,G\n0.020000,Cancel,unknown,,,,\n')
        self.assertEqual(result.inventory, 3)
        self.assertEqual(s.inventory, 3)
        self.assertIsNone(s._pending_id)


if __name__ == '__main__':
    unittest.main()
