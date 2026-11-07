import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from scripts.benchmark import digest
from scripts.round2_distribution_collect import collect
from scripts.round2_distribution_features import augment,ODD_NAMES,EVEN_NAMES
from scripts.round2_distribution_stats import labels
from scripts.round2_distribution_shock_exit import shock_exit
from scripts.round2_distribution_ensemble import blend
from scripts.round2_pretrained_alpha import BASE
from simulator.main import load_strategy_from_file
from simulator.models import BookOrderView,OrderBookSnapshot,Side
from test_strategy import Gateway


class DistributionTests(unittest.TestCase):
    def strategy(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'s.py';p.write_text(augment(BASE.read_text()))
            return load_strategy_from_file(p)

    def test_features_reflect_price_direction_and_preserve_even_state(self):
        def views(rows,side):return [BookOrderView(oid,side,p,q,'market') for oid,p,q in rows]
        bids=[('b1',100,4),('b2',100,350),('b3',99,20),('b4',95,4)]
        asks=[('a1',101,90),('a2',102,5)]
        snap=OrderBookSnapshot(0,views(bids,Side.BUY),views(asks,Side.SELL))
        reflected=OrderBookSnapshot(0,views([(a,201-p,q) for a,p,q in asks],Side.BUY),
            views([(a,201-p,q) for a,p,q in bids],Side.SELL))
        a=self.strategy();b=self.strategy()
        ao,ae=a._distribution_features(0,snap,100,101,100.5)
        bo,be=b._distribution_features(0,reflected,100,101,100.5)
        self.assertEqual(len(ao),len(ODD_NAMES));self.assertEqual(len(ae),len(EVEN_NAMES))
        np.testing.assert_allclose(ao,-np.array(bo),atol=1e-12)
        np.testing.assert_allclose(ae,be,atol=1e-12)
        # Age is based on first observation, and an unchanged ID is not a new quote.
        a._distribution_features(200000,snap,100,101,100.5)
        self.assertTrue(all(t==0 for t in a._distribution_seen.values()))
        self.assertEqual(a._distribution_frame[1][-3],0)

    def test_multihorizon_label_uses_mid_strictly_before_target_and_discards_tail(self):
        data={'mid_t':np.array([0,9,10,20]),'mid':np.array([100.,101.,1000.,2000.])}
        valid,y=labels(data,np.array([0,11]),np.array([100,100]),np.array([1,-1]),10,20)
        np.testing.assert_array_equal(valid,[True,False])
        self.assertEqual(y[0],1.)

    def test_shock_exit_closes_only_opposed_inventory_and_expires(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'s.py';p.write_text(shock_exit(BASE.read_text(),2));s=load_strategy_from_file(p)
        g=Gateway(s);s.inventory=-40;s._shock_sign=1;s._shock_until=100000
        s._cached_bid=102;s._cached_ask=103;s._cached_time=0
        s._hedge(100000)
        self.assertEqual(g.sent,[])
        s._hedge(1000)
        self.assertEqual(len(g.sent),1)
        self.assertEqual(g.sent[0].side,Side.BUY)
        self.assertEqual(g.sent[0].quantity,40)
        self.assertEqual(g.sent[0].price,104)
        s._hedge(2000)
        self.assertEqual(len(g.sent),1)

    def test_ensemble_predictions_equal_arithmetic_average(self):
        a=Path('strategies/round2_distribution_rich_167958.py')
        b=Path('strategies/round2_distribution_mixed_170252.py')
        sa=load_strategy_from_file(a);sb=load_strategy_from_file(b)
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'s.py';p.write_text(blend(a.read_text(),b.read_text()));s=load_strategy_from_file(p)
        for frame in (np.zeros(55),np.linspace(-1,1,55),np.linspace(2,-2,55)):
            expected=(sa._predict_fixed_trees(frame)+sb._predict_fixed_trees(frame))*.5
            self.assertAlmostEqual(s._predict_fixed_trees(frame),expected,places=12)

    def test_latency_and_exhaustion_labels_are_separate_from_features(self):
        tape='''Time,Operation,OrderId,Side,Volume,Price,Lifespan
0.000000,Insert,b,B,100,100,G
0.000001,Insert,a,A,100,101,G
0.004000,Insert,t0,A,10,100,F
0.010000,Insert,t1,A,90,100,F
0.020000,Insert,b2,B,100,99,G
0.500000,Cancel,missing,,,,
'''
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=root/'tape.csv';p.write_text(tape)
            data=collect(p,root/'output')
        np.testing.assert_array_equal(data['fill_t'],[10000])
        self.assertTrue(data['fill_t'][0]-data['fill_frame_t'][0]>=5000)
        self.assertTrue(data['fill_depleted'][0])
        self.assertEqual(data['fill_remaining'][0],0)
        self.assertEqual(data['fill_x'].shape[1],55)
        # Historical frame sees the first smaller trade, but cannot see the draining one.
        self.assertAlmostEqual(data['fill_x'][0,2],-10/11)


if __name__=='__main__':unittest.main()
