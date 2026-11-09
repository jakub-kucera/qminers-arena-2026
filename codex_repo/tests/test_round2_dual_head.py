import tempfile
import unittest
from pathlib import Path
from scripts.round2_t2_dual_head import build
from simulator.main import load_strategy_from_file


class DualHeadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.path=Path(cls.temp.name)/'s.py'
        cls.path.write_text(build()['narrow_blend0.5'])

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_heads_keep_separate_causal_statistics(self):
        b=load_strategy_from_file(self.path)
        b._observations.append((0,100,(1.0,)*33))
        b._learn(399999,101)
        self.assertEqual(b._labels,0)
        b._learn(400000,101)
        self.assertEqual(b._labels,1)
        self.assertEqual(b._narrow_state['_labels'],0)
        for queue in (b._observations,b._narrow_observations):queue.append((500000,100,(1.0,)*33))
        b._learn(900000,102)
        self.assertEqual(b._labels,2)
        self.assertEqual(b._narrow_state['_labels'],1)
        self.assertGreater(b._xx[0][0],1.99)
        self.assertEqual(b._narrow_state['_xx'][0][0],1.0)
        self.assertIsNot(b._xx,b._narrow_state['_xx'])

    def test_warmup_fallback_then_convex_blend(self):
        b=load_strategy_from_file(self.path);features=(1.0,)+(0.0,)*32
        b._narrow_state['_weights'][0]=-1
        self.assertEqual(b._blend_forecast(1,features),1)
        b._narrow_state['_labels']=200
        self.assertEqual(b._blend_forecast(1,features),0)


if __name__=='__main__':unittest.main()
