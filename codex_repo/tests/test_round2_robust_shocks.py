import tempfile
import unittest
from pathlib import Path
from scripts.round2_t2_robust_shocks import build
from simulator.main import load_strategy_from_file


class RobustShockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.path=Path(cls.temp.name)/'s.py'
        cls.path.write_text(build()['huber3.0'])

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_large_error_downweights_all_statistics_after_maturity(self):
        b=load_strategy_from_file(self.path)
        b._observations.append((0,100,(1.0,)*35,0.0))
        b._learn(399999,110);self.assertEqual(b._labels,0)
        b._learn(400000,110)
        self.assertAlmostEqual(b._mass,.3)
        self.assertAlmostEqual(b._xx[0][0],.3)
        self.assertAlmostEqual(b._xy[0],3)

    def test_uses_stored_forecast_not_current_weights(self):
        b=load_strategy_from_file(self.path);b._weights=[99.0]*35
        b._observations.append((0,100,(1.0,)*35,2.0))
        b._learn(400000,104)
        self.assertEqual(b._mass,1)
        self.assertEqual(b._xy[0],4)


if __name__=='__main__':unittest.main()
