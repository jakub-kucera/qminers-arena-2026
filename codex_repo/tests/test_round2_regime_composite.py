"""Shared-budget transitions and causal regime selection."""
import tempfile
import unittest
from pathlib import Path
from scripts.round2_regime_composite import build
from simulator.main import load_strategy_from_file
from simulator.models import OrderStatus, PrivateOrderEvent, Trade
from simulator.strategy import StrategyContext


class RegimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.source = Path(cls.temp.name)/'strategy.py'
        cls.source.write_text(build()['mix_300s_gate0'])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def bot(self):
        bot = load_strategy_from_file(self.source)
        sent, canceled = [], []
        def submit(request):
            sent.append(request)
            return str(len(sent))
        bot._attach_context(StrategyContext(submit,canceled.append,lambda *_:None,lambda:0))
        return bot,sent,canceled

    def test_transition_reserves_unconfirmed_maker_cancel(self):
        bot,sent,canceled = self.bot()
        bot.inventory = -100
        bot._orders['maker'] = [1,99,80,True,False,0]
        bot._m2_trade(1000,100,99,101)
        self.assertIn('maker',canceled)
        self.assertEqual(sent[0].quantity,120)
        self.assertEqual(sum(r[2] for r in bot._orders.values()),200)
        bot._m2_trade(2000,100,99,101)
        self.assertEqual(len(sent),1)

    def test_ioc_fill_not_used_as_maker_calibration_label(self):
        bot,sent,_ = self.bot()
        bot._value_us = 0
        bot._m2_trade(1000,100,99,101)
        oid = bot._m2_pending
        before = len(bot._cal_labels)
        bot.on_private_order_update(PrivateOrderEvent(timestamp_us=6000,order_id=oid,
            status=OrderStatus.FILLED,filled_quantity=100,remaining_quantity=0,fill_price=101))
        self.assertEqual(len(bot._cal_labels),before)
        self.assertEqual(bot.inventory,100)
        self.assertIsNone(bot._m2_pending)
        self.assertNotIn(oid,bot._m2_ids)

    def test_shadow_requires_elapsed_window_and_observed_gain(self):
        bot,_,_ = self.bot()
        trade = Trade(timestamp_us=0,price=101,quantity=500,taker_order_id='t',
            maker_order_id='m',taker_owner='market',maker_owner='market',book_side='ask')
        self.assertIsNone(bot._m2_target(0,99,101,[trade]))
        self.assertIsNone(bot._m2_target(299000000,120,122,[]))
        self.assertEqual(bot._m2_target(300000000,120,122,[]),100)


if __name__ == '__main__':
    unittest.main()
