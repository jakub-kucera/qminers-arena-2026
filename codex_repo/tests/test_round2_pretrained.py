import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.utils.parallel import _get_threadpool_controller

from scripts.benchmark import digest
from scripts.round2_pretrained_alpha import collect,export,BASE
from simulator.main import load_strategy_from_file


class PretrainedAlphaTests(unittest.TestCase):
    def test_inline_predictions_equal_fitted_estimator(self):
        rng=np.random.default_rng(81);x=rng.normal(size=(400,29));y=np.clip(x[:,0]*.3,-1,1)
        model=HistGradientBoostingRegressor(max_iter=3,max_leaf_nodes=5,min_samples_leaf=20,early_stopping=False)
        with _get_threadpool_controller().limit(limits=1):model.fit(x,y)
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'s.py';p.write_text(export(BASE.read_text(),model,.5));s=load_strategy_from_file(p)
        np.testing.assert_allclose([s._predict_fixed_trees(r) for r in x],model.predict(x),rtol=0,atol=1e-12)

    def test_collector_accepts_manifest_paths_and_preserves_cached_training_rows(self):
        tape='''Time,Operation,OrderId,Side,Volume,Price,Lifespan
0.000000,Insert,b,B,100,100,G
0.000001,Insert,a,A,100,101,G
0.100000,Cancel,missing,,,,
0.200000,Cancel,missing,,,,
0.500000,Cancel,missing,,,,
0.600000,Cancel,missing,,,,
'''
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=root/'tape.csv';p.write_text(tape)
            cache=root/'cache';cache.mkdir()
            with patch('scripts.round2_pretrained_alpha.ROOT',cache):
                m=dict(development=str(p),development_sha256=digest(p))
                first=collect(m);second=collect(m)
        self.assertGreater(len(first['y']),0)
        self.assertEqual(first['x'].shape[1],29)
        self.assertTrue(np.all(first['t']+400000<=600000))
        for k in first:np.testing.assert_array_equal(first[k],second[k])


if __name__=='__main__':unittest.main()
