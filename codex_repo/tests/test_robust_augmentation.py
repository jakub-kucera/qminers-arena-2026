"""Feature invariance, label causality, and joint-bootstrap regression checks."""
import ast
import random
import tempfile
import unittest
from pathlib import Path

import numpy as np

from scripts.check_submission import check
from scripts.probe_robust_augmentation import FEATURES, bootstrap_gate, generate
from simulator.main import load_strategy_from_file
from simulator.models import BookOrderView, OrderBookSnapshot, Side
from simulator.strategy import StrategyContext


def attach(strategy):
    sent = []
    def submit(request):
        sent.append(request)
        return 'u'+str(len(sent))
    strategy._attach_context(StrategyContext(submit, lambda *_: None, lambda *_: None, lambda: 0))
    return sent


class AugmentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temp.name)
        cls.sources = generate(Path('strategies/round1_submission.py').read_text())
        for name, text in cls.sources.items():
            (cls.folder/(name+'.py')).write_text(text)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def bot(self, name):
        s = load_strategy_from_file(self.folder/(name+'.py'))
        attach(s)
        return s

    def test_submission_checks_and_execution_are_preserved(self):
        def execution(text):
            cls = next(n for n in ast.parse(text).body if isinstance(n, ast.ClassDef))
            return {n.name: ast.dump(n) for n in cls.body if isinstance(n, ast.FunctionDef)
                    and n.name in ('_quote', '_cancel', 'on_private_order_update')}
        reference = execution(self.sources['original_554347'])
        for name, text in self.sources.items():
            self.assertEqual(check(self.folder/(name+'.py')), [], name)
            self.assertEqual(execution(text), reference, name)

    def test_all_horizons_wait_for_mature_labels(self):
        for name in self.sources:
            s = self.bot(name)
            x = (1.0,)+tuple(0.0 for _ in range(s.FEATURE_COUNT-1))
            s._observations.append((0, 100, x))
            s._learn(s.HORIZON_US-1, 100000)
            self.assertEqual(s._labels, 0, name)
            s._learn(s.HORIZON_US, 102)
            self.assertEqual(s._labels, 1, name)
            self.assertEqual(s._xy[0], 2, name)

    def test_features_are_finite_odd_and_price_translation_invariant(self):
        rng = random.Random(2026110702)
        for _ in range(20):
            sides = []
            for side in (Side.BUY, Side.SELL):
                orders = []
                for depth in range(4):
                    price = 100-depth if side == Side.BUY else 102+depth
                    for k in range(rng.randint(1, 5)):
                        orders.append(BookOrderView(str(side)+str(depth)+str(k), side,
                                                     price, rng.randint(1, 500), 'market'))
                sides.append(orders)
            original = OrderBookSnapshot(0, *sides)
            moved = OrderBookSnapshot(0, *[[BookOrderView(o.order_id, o.side, o.price+10000,
                                                        o.quantity, o.owner) for o in orders] for orders in sides])
            mirrored = OrderBookSnapshot(0, *[[BookOrderView(o.order_id,
                            Side.BUY if o.side == Side.SELL else Side.SELL,
                            202-o.price, o.quantity, o.owner) for o in orders] for orders in reversed(sides)])
            for name in FEATURES:
                vectors = []
                for snapshot in (original, moved, mirrored):
                    bot = self.bot(name)
                    bot.on_order_book_change(snapshot, [])
                    vectors.append(np.array(bot._observations[-1][2]))
                self.assertTrue(np.isfinite(vectors).all(), name)
                np.testing.assert_allclose(vectors[0], vectors[1], atol=1e-9, err_msg=name)
                np.testing.assert_allclose(vectors[0], -vectors[2], atol=1e-9, err_msg=name)
                self.assertLessEqual(np.abs(vectors[0][15:]).max(), 4.0)

    def test_cleanup_preserves_snapshot_features_and_orders(self):
        snapshot = OrderBookSnapshot(0,
            [BookOrderView('u1', Side.BUY, 101, 100, 'user'),
             BookOrderView('b', Side.BUY, 100, 210, 'market')],
            [BookOrderView('a', Side.SELL, 103, 50, 'market'),
             BookOrderView('u2', Side.SELL, 103, 100, 'user')])
        original, clean = self.bot('original_554347'), self.bot('clean_554347')
        a, b = attach(original), attach(clean)
        original.on_order_book_change(snapshot, [])
        clean.on_order_book_change(snapshot, [])
        self.assertEqual(original._observations, clean._observations)
        self.assertEqual(a, b)
        self.assertEqual(original._desired_buy, clean._desired_buy)
        self.assertEqual(original._desired_sell, clean._desired_sell)

    def test_joint_bootstrap_respects_duplicate_columns_and_location_shift(self):
        x = np.random.default_rng(72).normal(size=(20, 1))*100
        lower, errors, critical = bootstrap_gate(x, draws=2000)
        duplicate = bootstrap_gate(np.repeat(x, 2, axis=1), draws=2000)
        np.testing.assert_allclose(duplicate[0], np.repeat(lower, 2))
        self.assertAlmostEqual(duplicate[2], critical)
        shifted = bootstrap_gate(x+25, draws=2000)
        np.testing.assert_allclose(shifted[0]-lower, [500])
        np.testing.assert_allclose(shifted[1], errors)

    def test_bootstrap_rejects_malformed_or_nonfinite_blocks(self):
        with self.assertRaises(ValueError):
            bootstrap_gate(np.ones((19, 2)))
        with self.assertRaises(ValueError):
            bootstrap_gate(np.full((20, 2), np.nan))


if __name__ == '__main__':
    unittest.main()
