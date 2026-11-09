import tempfile
import unittest
from pathlib import Path
from scripts.round2_t2_training_spread import build
from simulator.main import load_strategy_from_file


class SpreadTrainingTests(unittest.TestCase):
    def test_observed_weight_applies_to_all_sufficient_statistics(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'s.py';path.write_text(build()['wide_weight0.25'])
            b=load_strategy_from_file(path)
            b._observations.append((0,100,(1.0,)*33,.25))
            b._learn(399999,102)
            self.assertEqual(b._labels,0)
            b._learn(400000,102)
            self.assertEqual(b._mass,.25)
            self.assertEqual(b._xx[0][0],.25)
            self.assertEqual(b._xy[0],.5)

    def test_zero_weight_does_not_count_as_training(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'s.py';path.write_text(build()['wide_weight0.0'])
            b=load_strategy_from_file(path)
            b._observations.append((0,100,(1.0,)*33,0.0))
            b._learn(400000,102)
            self.assertEqual(b._labels,0)
            self.assertEqual(b._mass,0)
            self.assertEqual(b._xy,[0.0]*33)


if __name__=='__main__':unittest.main()
