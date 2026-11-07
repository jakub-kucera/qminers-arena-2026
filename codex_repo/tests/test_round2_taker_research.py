import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from scripts.round2_taker_audit import run
from scripts.round2_taker_variants import BASE,shock_override,flow_bias,liquidity_features
from scripts.benchmark import digest
from simulator.main import load_strategy_from_file
from simulator.models import BookOrderView,OrderBookSnapshot,Side
from test_strategy import Gateway


class TakerResearchTests(unittest.TestCase):
    def load_text(self,text):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'s.py';p.write_text(text);return load_strategy_from_file(p)

    def snapshot(self,t):
        return OrderBookSnapshot(t,[BookOrderView('bid',Side.BUY,100,1000,'market')],
            [BookOrderView('ask',Side.SELL,101,1000,'market')])

    def trade(self,t,qty,side='ask',owner='market'):
        return SimpleNamespace(timestamp_us=t,quantity=qty,book_side=side,taker_owner=owner,
            maker_owner='market',taker_order_id=f't{t}',maker_order_id='ask',price=101)

    def test_take_reserves_cancelling_unaccepted_and_resting_orders(self):
        s=load_strategy_from_file(BASE);g=Gateway(s);s.inventory=20
        s._orders={'cancel':[1,100,20,True,True,0,0,0],
            'pending':[1,100,30,False,False,0,0,0],
            'resting':[1,100,25,True,False,0,0,0]}
        s._take(10000,1,1,100,101)
        self.assertEqual(len(g.sent),1);self.assertEqual(g.sent[0].quantity,5)
        self.assertEqual(s.inventory+sum(r[2] for r in s._orders.values() if r[0]==1),100)
        s._take(20000,1,1,100,101)
        self.assertEqual(len(g.sent),1)

    def test_shock_override_expires_and_respects_one_tick_spread(self):
        s=self.load_text(shock_override(BASE.read_text()));g=Gateway(s)
        s._shock_sign=1;s._shock_until=100000
        s._take(0,0,2,100,102);self.assertFalse(g.sent)
        s._take(100000,0,1,100,101);self.assertFalse(g.sent)
        s._take(99999,0,1,100,101);self.assertEqual(g.sent[0].side,Side.BUY)
        self.assertEqual(g.sent[0].quantity,100)

    def test_flow_window_only_uses_external_flow_and_consumes_trigger(self):
        s=self.load_text(flow_bias(BASE.read_text(),125000,575));Gateway(s)
        s.on_order_book_change(self.snapshot(0),[self.trade(0,400)])
        self.assertEqual(s._trend_direction,0)
        s.on_order_book_change(self.snapshot(10000),[self.trade(10000,400,owner='user')])
        self.assertEqual(s._trend_direction,0)
        s.on_order_book_change(self.snapshot(20000),[self.trade(20000,200)])
        self.assertEqual(s._trend_direction,1);self.assertEqual(s._trend_flow_sum,0)
        s.on_order_book_change(self.snapshot(30000),[self.trade(30000,400,'bid')])
        s.on_order_book_change(self.snapshot(200000),[self.trade(200000,200,'bid')])
        self.assertEqual(s._trend_direction,1)

    def test_new_online_features_are_33_dimensional_and_ignore_own_orders(self):
        s=self.load_text(liquidity_features(BASE.read_text()));Gateway(s)
        s.on_order_book_change(self.snapshot(0),[])
        first=s._observations[-1][2]
        self.assertEqual(len(first),33)
        snap=self.snapshot(20000)
        snap.bids.append(BookOrderView('own',Side.BUY,100,999999,'user'))
        s.on_order_book_change(snap,[])
        self.assertEqual(s._observations[-1][2][-4:],first[-4:])

    def test_generic_audit_supports_flow_strategy_private_position_field(self):
        source=Path('strategies/round2_imported/r2_M2_flow_trend.py').read_text().replace('SELF_GATE = 1','SELF_GATE = 0',1)
        tape='''Time,Operation,OrderId,Side,Volume,Price,Lifespan
0,Insert,b,B,1000,100,G
0.000001,Insert,a,A,2000,101,G
0.010000,Insert,t,B,600,101,F
0.020000,Cancel,missing,,,,
0.050000,Cancel,missing,,,,
'''
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=root/'s.py';p.write_text(source);d=root/'data.csv';d.write_text(tape)
            result=run(dict(file=str(p),source_sha256=digest(p),risk='strict100'),d,root/'out')
        self.assertEqual(result['result']['inventory'],100)
        self.assertEqual(result['result']['traded_volume'],100)
        self.assertTrue(result['independent_private_ledger'])


if __name__=='__main__':unittest.main()
