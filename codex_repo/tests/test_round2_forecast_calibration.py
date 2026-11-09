import tempfile
import unittest
from pathlib import Path
from scripts.round2_t2_forecast_calibration import build
from simulator.main import load_strategy_from_file


class ForecastCalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.path=Path(cls.temp.name)/'s.py'
        cls.path.write_text(build()['memory300_blend1.0'])

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_stored_forecast_only_after_maturity(self):
        b=load_strategy_from_file(self.path)
        b._weights=[9.0]*33
        b._observations.append((0,100,(1.0,)*33,.5,1))
        b._learn(399999,101)
        self.assertEqual(b._fc_count,0)
        b._learn(400000,101)
        self.assertEqual(b._fc_count,1)
        self.assertAlmostEqual(b._fc_xx,.25)
        self.assertAlmostEqual(b._fc_xy,.5)

    def test_stale_and_wide_labels_excluded(self):
        for now,spread in ((1400001,1),(400000,2)):
            b=load_strategy_from_file(self.path)
            b._observations.append((0,100,(0.0,)*33,.5,spread))
            b._learn(now,101)
            self.assertEqual(b._fc_count,0)

    def test_gain_is_bounded_and_decays_to_identity(self):
        b=load_strategy_from_file(self.path)
        b._fc_time=0;b._fc_xx=100;b._fc_xy=10000
        self.assertEqual(b._calibrate_forecast(0,1),1.5)
        self.assertEqual(b._calibrate_forecast(0,2),2)
        self.assertAlmostEqual(b._calibrate_forecast(30000000000,1),1)
        b._fc_xy=-10000
        self.assertEqual(b._calibrate_forecast(0,1),.5)
        self.assertEqual(b._calibrate_forecast(0,-1),-.5)


if __name__=='__main__':unittest.main()
