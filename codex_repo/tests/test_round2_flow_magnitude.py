import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from scripts.round2_t2_flow_magnitude import build
from simulator.main import load_strategy_from_file


class FlowMagnitudeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.path=Path(cls.temp.name)/'s.py'
        cls.path.write_text(build()['multiscale'])

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_market_only_and_decay(self):
        b=load_strategy_from_file(self.path)
        trades=[SimpleNamespace(taker_owner=owner,book_side=side,quantity=q)
                for owner,side,q in [('market','ask',1000),('market','bid',500),('user','ask',900)]]
        x=b._impact_features(0,trades)
        self.assertEqual(len(x),6)
        self.assertEqual(x[0],1)
        self.assertAlmostEqual(x[1],500/1501*math.sqrt(3))
        b._impact_features(100000,[])
        self.assertAlmostEqual(b._impact_net[0],500/math.e)
        self.assertGreater(b._impact_net[2],b._impact_net[0])

    def test_bounded_and_direction_symmetric(self):
        a=load_strategy_from_file(self.path);b=load_strategy_from_file(self.path)
        x=a._impact_features(0,[SimpleNamespace(taker_owner='market',book_side='ask',quantity=1000000)])
        y=b._impact_features(0,[SimpleNamespace(taker_owner='market',book_side='bid',quantity=1000000)])
        self.assertTrue(all(abs(v)<=3 for v in x))
        self.assertEqual(tuple(-v for v in x),y)


if __name__=='__main__':unittest.main()
