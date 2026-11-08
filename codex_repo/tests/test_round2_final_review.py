"""Causality checks for the exact user-supplied round-2 final submission."""
import math
import unittest
from pathlib import Path
from types import SimpleNamespace

from simulator.main import load_strategy_from_file


SOURCE=Path('strategies/round2_final_317057.py')


class FinalSubmissionReviewTests(unittest.TestCase):
    def test_label_matures_and_uses_forecast_saved_before_its_outcome(self):
        s=load_strategy_from_file(SOURCE)
        features=(1.0,)+(0.0,)*(s.FEATURE_COUNT-1)
        s._observations.append((0,100,features,0.0))
        # A later model revision must not rewrite the stored forecast error.
        s._weights[0]=100.0
        s._learn(399999,110)
        self.assertEqual(s._labels,0)
        self.assertEqual(s._mass,0)
        s._learn(400000,110)
        self.assertEqual(s._labels,1)
        self.assertAlmostEqual(s._mass,0.6)
        self.assertAlmostEqual(s._xy[0],6.0)
        self.assertAlmostEqual(s._xx[0][0],0.6)

    def test_impact_uses_external_flow_and_decays_when_trading_stops(self):
        s=load_strategy_from_file(SOURCE)
        trades=[SimpleNamespace(quantity=600,book_side='ask',taker_owner='market'),
            SimpleNamespace(quantity=300,book_side='bid',taker_owner='market'),
            SimpleNamespace(quantity=1000,book_side='ask',taker_owner='user')]
        features=s._impact_features(0,trades)
        self.assertAlmostEqual(s._impact_net[0],300)
        self.assertAlmostEqual(s._impact_volume[0],900)
        self.assertAlmostEqual(features[0],0.6)
        s._impact_features(500000,[])
        self.assertAlmostEqual(s._impact_net[0],300*math.exp(-1))


if __name__=='__main__':unittest.main()
