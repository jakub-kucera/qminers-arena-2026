import tempfile
import unittest
from pathlib import Path

from scripts.round2_risk_weighted_learning import weighted_learning
from simulator.main import load_strategy_from_file
from simulator.models import BookOrderView,OrderBookSnapshot,Side
from test_strategy import Gateway


class RiskWeightedLearningTests(unittest.TestCase):
    def strategy(self):
        text=weighted_learning(Path('strategies/round2_research/round2_absolute_variance_112379.py').read_text())
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'s.py';p.write_text(text)
            return load_strategy_from_file(p)

    def test_delayed_label_updates_all_moments_with_saved_weight(self):
        s=self.strategy()
        s._observations.append((0,100,(1.0,)*29,.2))
        s._learn(399999,101)
        self.assertEqual(s._mass,0)
        s._learn(400000,101)
        self.assertEqual(s._mass,.2)
        self.assertEqual(s._xy[0],.2)
        self.assertEqual(s._xx[0][0],.2)

    def test_future_volatility_cannot_change_observation_weight(self):
        s=self.strategy();Gateway(s);s._vol_variance=10
        s.on_order_book_change(OrderBookSnapshot(0,
            [BookOrderView('b',Side.BUY,100,100,'market')],
            [BookOrderView('a',Side.SELL,101,100,'market')]),[])
        self.assertAlmostEqual(s._observations[0][3],.1)
        s._vol_variance=.01
        s._learn(400000,101.5)
        self.assertAlmostEqual(s._mass,.1)


if __name__=='__main__':unittest.main()
