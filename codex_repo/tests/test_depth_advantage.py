"""Causality, numerical stability, scan equivalence, and boundary regression."""
import random
import tempfile
import unittest
from pathlib import Path

import numpy as np

from scripts.check_submission import check
from scripts.probe_depth_advantage import ProbeEngine, prepare
from simulator.main import load_strategy_from_file
from simulator.models import BookOrderView, OrderBookSnapshot, Side
from simulator.simulator import ExchangeSimulator, SimulationConfig
from simulator.strategy import StrategyContext

SOURCES = Path('logs/depth_advantage/sources')


def load(name):
    return load_strategy_from_file(SOURCES/(name+'.py'))


def attach(strategy):
    requests = []
    def send(request):
        requests.append(request)
        return 'u'+str(len(requests))
    strategy._attach_context(StrategyContext(send, lambda *_: None, lambda *_: None, lambda: 0))
    return requests


class DepthAdvantageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global SOURCES
        cls.scratch = tempfile.TemporaryDirectory()
        folder = Path(cls.scratch.name)
        tape = folder/'stub.csv'
        tape.write_text('Time,Operation,OrderId,Side,Volume,Price,Lifespan\n')
        prepare(Path('strategies/round1_depth_524k.py'), folder, tape, tape)
        SOURCES = folder/'sources'

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    def test_all_sources_pass_restrictions_and_labels_cannot_arrive_early(self):
        for path in SOURCES.glob('*.py'):
            with self.subTest(path=path.name):
                self.assertEqual(check(path), [])
                s = load_strategy_from_file(path)
                features = tuple([1.0]+[0.0]*(s.FEATURE_COUNT-1))
                s._observations.append((0, 100, features))
                s._learn(99999, 10000)
                self.assertEqual(s._labels, 0)
                self.assertEqual(s._weights, [0.0]*s.FEATURE_COUNT)
                s._learn(100000, 102)
                self.assertEqual(s._labels, 1)
                self.assertEqual(s._xy[0], 2.0)

    def test_auxiliary_labels_respect_their_own_horizon(self):
        for name, horizon in [('memory_blend', 100000), ('horizon_blend', 500000)]:
            s = load(name)
            features = tuple([1.0]+[0.0]*12)
            s._aux_observations.append((0, 100, features))
            s._learn_aux(horizon-1, 10000)
            self.assertEqual(s._aux_labels, 0)
            s._learn_aux(horizon, 103)
            self.assertEqual(s._aux_xy[0], 3.0)

    def test_stale_observations_are_discarded(self):
        s = load('supplied_13')
        s._observations.append((0, 100, tuple([1.0]*13)))
        s._learn(1100001, 120)
        self.assertEqual(s._labels, 0)
        self.assertFalse(s._observations)

    def test_thirteen_dimensional_solver_matches_regularized_numpy_solution(self):
        rng = np.random.default_rng(20261107)
        x = rng.normal(size=(300, 13))
        x[:, 12] = x[:, 11]*0.999999  # Near collinearity, protected by ridge.
        y = rng.normal(size=300)
        s = load('supplied_13')
        s._labels = 300
        s._mass = 300
        s._xx = (x.T@x).tolist()
        s._xy = (x.T@y).tolist()
        s._learn(1000000, 100)
        expected = np.linalg.solve(x.T@x+10*np.eye(13), x.T@y)
        np.testing.assert_allclose(s._weights, expected, rtol=1e-10, atol=1e-12)

    def test_cleanup_preserves_market_features_and_quotes_with_own_orders(self):
        rng = random.Random(20261107)
        for _ in range(100):
            orders = []
            for side in (Side.BUY, Side.SELL):
                one_side = []
                for level in range(5):
                    price = 99-level if side == Side.BUY else 101+level
                    for k in range(rng.randint(1, 5)):
                        owner = 'user' if rng.random() < 0.25 else 'market'
                        one_side.append(BookOrderView(str(side)+str(level)+str(k), side,
                                                     price, rng.randint(1, 1000), owner))
                orders.append(one_side)
            snap = OrderBookSnapshot(100000, *orders)
            original, clean = load('supplied_13'), load('clean_13')
            r1, r2 = attach(original), attach(clean)
            original.on_order_book_change(snap, [])
            clean.on_order_book_change(snap, [])
            self.assertEqual(original._observations, clean._observations)
            self.assertEqual(r1, r2)

    def test_boundary_observer_preserves_official_result(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'tape.csv'
            path.write_text('Time,Operation,OrderId,Side,Volume,Price,Lifespan\n'
                            '0,Insert,b,B,100,99,G\n0.000001,Insert,a,A,1000,101,G\n'
                            '0.020000,Insert,t,A,200,99,F\n0.030000,Cancel,b,,,,\n')
            config = SimulationConfig(max_position=100, max_potential_position=1000,
                                      position_breach_penalty_per_second=10000,
                                      order_accept_delay_ms=5, public_depth=20)
            original = ExchangeSimulator(load('supplied_13'), config).run(path)
            engine = ProbeEngine(load('supplied_13'), config, [3000, 10000, 25000])
            probed = engine.run(path)
            self.assertEqual(original.model_dump(), probed.model_dump())
            self.assertEqual(len(engine.boundary_pnl), 3)

    def test_all_inventory_states_reserve_each_side_independently(self):
        for inventory in range(-100, 101):
            s = load('clean_13')
            attach(s)
            s.inventory = inventory
            s._quote(0, 1, 99)
            s._quote(0, -1, 101)
            self.assertLessEqual(inventory+sum(r[2] for r in s._orders.values() if r[0] > 0), 100)
            self.assertGreaterEqual(inventory-sum(r[2] for r in s._orders.values() if r[0] < 0), -100)


if __name__ == '__main__':
    unittest.main()
