import math
import tempfile
import unittest
from pathlib import Path

from scripts.round1_claude_combo import second_group
from scripts.round1_claude_capped_flow import source as capped_source
from scripts.round1_claude_improvements import transfer_features
from scripts.round1_aggressor_groups import source_for
from scripts.round1_size_cohorts import bucket_source
from simulator.main import load_strategy_from_file
from simulator.models import BookOrderView, OrderBookSnapshot, Side, Trade
from test_strategy import Gateway


class ClaudeExtensionTests(unittest.TestCase):
    def setUp(self):
        self.base = Path('strategies/round1_claude_595k.py').read_text()
        self.group = transfer_features(self.base, source_for(100000,100000))
        self.bids = [BookOrderView('rest_buy',Side.BUY,100,40,'market')]
        self.asks = [BookOrderView('ask',Side.SELL,102,100,'market')]

    def load(self, source):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'strategy.py'
            path.write_text(source)
            strategy=load_strategy_from_file(path)
        Gateway(strategy)
        return strategy

    def trades(self):
        return [Trade(timestamp_us=0,price=100,quantity=q,taker_order_id='rest_buy',
                      maker_order_id='ask'+str(i),taker_owner='market',maker_owner=owner,book_side='ask')
                for i,(q,owner) in enumerate(((10,'market'),(15,'user')))] + [
            Trade(timestamp_us=0,price=99,quantity=7,taker_order_id='not_visible',
                  maker_order_id='bid',taker_owner='market',maker_owner='market',book_side='bid')]

    def test_grouping_counts_remaining_taker_once_across_multiple_fills(self):
        s=self.load(self.group)
        s.on_order_book_change(OrderBookSnapshot(0,self.bids,self.asks),self.trades())
        self.assertEqual(s._group_volume,[65,7,15])
        self.assertEqual(s._group_net,[65,-7,15])
        self.assertEqual(s._rest_count,1)
        features=s._observations[-1][2]
        self.assertEqual(len(features),23)
        self.assertEqual(features[15:18],(65/66,-7/8,15/16))

    def test_feature_transfer_keeps_supplied_training_and_execution_settings(self):
        source=transfer_features(transfer_features(self.base,bucket_source()),source_for(100000,100000))
        s=self.load(source)
        self.assertEqual((s.HORIZON_US,s.MODEL_MEMORY_US,s.POSITION_LIMIT),(400000,100000000000,1000))
        s.on_order_book_change(OrderBookSnapshot(0,self.bids,self.asks),[])
        self.assertEqual(len(s._observations[-1][2]),31)
        self.assertEqual(s.FEATURE_COUNT,31)

    def test_multiple_group_windows_decay_separately(self):
        s=self.load(second_group(self.group,500000))
        s.on_order_book_change(OrderBookSnapshot(0,self.bids,self.asks),self.trades())
        s.on_order_book_change(OrderBookSnapshot(100000,self.bids,self.asks),[])
        self.assertEqual(len(s._observations[-1][2]),31)
        self.assertAlmostEqual(s._group_net[0],65*math.exp(-1))
        self.assertAlmostEqual(s._second_group_net[0],65*math.exp(-0.2))

    def test_size_cap_applies_once_to_whole_aggressive_order(self):
        s=self.load(capped_source(500000,20))
        s.on_order_book_change(OrderBookSnapshot(0,self.bids,self.asks),self.trades())
        self.assertEqual(s._group_volume,[20,7,15])
        self.assertEqual(s._group_net,[20,-7,15])
        self.assertEqual(s._group_price,[2000,693,1500])

    def test_count_flow_counts_orders_instead_of_execution_fragments(self):
        s=self.load(capped_source(1000000,1))
        s.on_order_book_change(OrderBookSnapshot(0,self.bids,self.asks),self.trades())
        self.assertEqual(s._group_volume,[1,1,1])
        self.assertEqual(s._group_net,[1,-1,1])


if __name__=='__main__':
    unittest.main()
