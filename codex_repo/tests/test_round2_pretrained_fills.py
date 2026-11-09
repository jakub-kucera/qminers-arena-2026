import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.utils.parallel import _get_threadpool_controller

from scripts.benchmark import digest
from scripts.round2_pretrained_alpha import BASE
from scripts.round2_pretrained_fill_value import collect,fill_value_source
from simulator.main import load_strategy_from_file
from simulator.models import BookOrderView,OrderBookSnapshot,Side
from test_strategy import Gateway


class PretrainedFillValueTests(unittest.TestCase):
    def test_negative_fill_edge_allows_only_closing_budget(self):
        x=np.zeros((40,18));y=np.full(40,-1.)
        model=HistGradientBoostingRegressor(max_iter=1,min_samples_leaf=5,early_stopping=False)
        with _get_threadpool_controller().limit(limits=1):model.fit(x,y)
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'s.py';p.write_text(fill_value_source(BASE.read_text(),model,0));s=load_strategy_from_file(p)
        g=Gateway(s);s.inventory=-40
        s.on_order_book_change(OrderBookSnapshot(0,
            [BookOrderView('b',Side.BUY,100,100,'market')],
            [BookOrderView('a',Side.SELL,101,100,'market')]),[])
        self.assertEqual([(r.side,r.quantity) for r in g.sent],[(Side.BUY,40)])

    def test_training_frame_precedes_fill_by_at_least_native_latency(self):
        tape='''Time,Operation,OrderId,Side,Volume,Price,Lifespan
0.000000,Insert,b,B,100,100,G
0.000001,Insert,a,A,100,101,G
0.004000,Insert,t0,A,10,100,F
0.010000,Insert,t1,A,10,100,F
0.200000,Cancel,missing,,,,
0.500000,Cancel,missing,,,,
0.600000,Cancel,missing,,,,
'''
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=root/'tape.csv';p.write_text(tape);out=root/'cache';out.mkdir()
            with patch('scripts.round2_pretrained_fill_value.ROOT',out):
                data=collect(dict(development=str(p),development_sha256=digest(p)))
        self.assertEqual(list(data['t']),[10000])
        self.assertAlmostEqual(data['x'][0,2],-10/11)
        self.assertEqual(data['y'][0],.5)


if __name__=='__main__':unittest.main()
