import tempfile
import unittest
from math import exp
from pathlib import Path

from scripts.round2_volatility_exposure import volatility_model
from simulator.main import load_strategy_from_file


class AbsoluteVolatilityTests(unittest.TestCase):
    def strategy(self):
        text=volatility_model(Path('strategies/round2/round2_transfer.py').read_text(),10,100,1)
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'s.py';p.write_text(text)
            return load_strategy_from_file(p)

    def test_regular_sample_uses_only_preceding_price_and_correct_time_units(self):
        s=self.strategy();s._update_absolute_volatility(0,100)
        s._update_absolute_volatility(50000,101)
        s._update_absolute_volatility(100000,999)
        alpha=1-exp(-.1/10)
        self.assertAlmostEqual(s._vol_variance,(1-alpha)*1+alpha*1**2/.1)
        self.assertEqual(s._vol_sample_mid,101)
        self.assertEqual(s._vol_samples,1)

    def test_flat_price_decays_absolute_variance(self):
        s=self.strategy();s._update_absolute_volatility(0,100)
        s._update_absolute_volatility(1000000,100)
        self.assertAlmostEqual(s._vol_variance,exp(-1/10))

    def test_absolute_volatility_scales_with_tick_move(self):
        low=self.strategy();high=self.strategy()
        for s in (low,high):s._vol_variance=0;s._update_absolute_volatility(0,100)
        low._update_absolute_volatility(50000,101)
        high._update_absolute_volatility(50000,102)
        for s in (low,high):s._update_absolute_volatility(100000,100)
        self.assertAlmostEqual(high._vol_sigma,2*low._vol_sigma)


if __name__=='__main__':unittest.main()
