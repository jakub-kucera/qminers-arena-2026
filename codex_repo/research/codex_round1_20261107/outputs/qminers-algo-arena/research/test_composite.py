"""Reservation and lifecycle tests for composite quote replenishment."""
import unittest
from run_study import ROOT,load_bot
from simulator.models import OrderStatus,PrivateOrderEvent,BookOrderView,OrderBookSnapshot,Side
from simulator.strategy import StrategyContext


class CompositeRiskTests(unittest.TestCase):
    strategy_file='composite_template.py'
    def bot(self):
        bot=load_bot(ROOT/'strategies'/self.strategy_file,{'TOPUP':1,'CAP':100})
        sent=[];canceled=[]
        def send(request):
            sent.append(request)
            return 'new-'+str(len(sent))
        bot._attach_context(StrategyContext(submit_order=send,cancel_order=canceled.append,
            modify_order=lambda oid,q:None,now_us=lambda:0))
        return bot,sent,canceled

    def test_pending_cancel_keeps_reservation(self):
        bot,sent,canceled=self.bot()
        bot.position=90
        bot.orders={'old':[1,100,10,True]}
        bot.keep(1,101,200)
        self.assertEqual(len(sent),0)
        bot.on_private_order_update(PrivateOrderEvent(timestamp_us=5000,order_id='old',status=OrderStatus.CANCELED))
        bot.keep(1,101,200)
        self.assertEqual(sent[0].quantity,10)

    def test_opposite_quotes_are_not_netted(self):
        bot,sent,canceled=self.bot()
        bot.orders={'bid':[1,100,70,True],'ask':[-1,102,100,False]}
        bot.keep(1,101,200)
        self.assertEqual(sent[0].quantity,30)
        self.assertEqual(sum(o[2] for o in bot.orders.values() if o[0]==1),100)

    def test_refill_preserves_old_quote_and_respects_late_fill(self):
        bot,sent,canceled=self.bot()
        bot.orders={'old':[1,100,40,False]}
        bot.keep(1,100,100)
        self.assertEqual(sent[0].quantity,60)
        self.assertEqual(canceled,[])
        bot.keep(1,101,100)
        self.assertEqual(set(canceled),{'old','new-1'})
        self.assertEqual(len(sent),1)
        bot.on_private_order_update(PrivateOrderEvent(timestamp_us=7000,order_id='old',
            status=OrderStatus.FILLED,filled_quantity=40,remaining_quantity=0,fill_price=100))
        bot.keep(1,101,100)
        self.assertEqual(bot.position,40)
        self.assertEqual(len(sent),1)
        bot.on_private_order_update(PrivateOrderEvent(timestamp_us=10000,order_id='new-1',status=OrderStatus.CANCELED))
        bot.keep(1,101,100)
        self.assertEqual(sent[-1].quantity,60)

    def test_reducing_quote_can_cross_zero_without_breaching(self):
        bot,sent,canceled=self.bot()
        bot.position=80
        bot.keep(-1,102,200)
        self.assertEqual(sent[0].quantity,180)
        bot.on_private_order_update(PrivateOrderEvent(timestamp_us=5000,order_id='new-1',
            status=OrderStatus.FILLED,filled_quantity=180,remaining_quantity=0,fill_price=102))
        self.assertEqual(bot.position,-100)

    def test_nonterminal_reject_keeps_original(self):
        bot,sent,canceled=self.bot()
        bot.orders={'old':[1,100,100,False]}
        bot.on_private_order_update(PrivateOrderEvent(timestamp_us=5000,order_id='old',
            status=OrderStatus.REJECTED,remaining_quantity=100,message='invalid modify'))
        bot.keep(1,101,100)
        self.assertIn('old',bot.orders)
        self.assertEqual(len(sent),0)


class RoomRiskTests(CompositeRiskTests):
    strategy_file='composite_room_template.py'

    def test_depleted_market_queue_pulls_quote_but_keeps_reservation(self):
        bot,sent,canceled=self.bot()
        import sys
        module=sys.modules['user_strategy_module']
        module.DEPLETE_LOTS=20
        bot.orders={'bid-old':[1,100,100,False]}
        snapshot=OrderBookSnapshot(timestamp_us=1000,
            bids=[BookOrderView('m-b',Side.BUY,100,10,'market')],
            asks=[BookOrderView('m-a',Side.SELL,102,1000,'market')])
        bot.on_order_book_change(snapshot,[])
        self.assertIn('bid-old',canceled)
        self.assertIn('bid-old',bot.orders)
        self.assertFalse(any(o.side==Side.BUY for o in sent))

    def test_high_inventory_steps_adding_quote_back_after_cancel_ack(self):
        bot,sent,canceled=self.bot()
        import sys
        module=sys.modules['user_strategy_module']
        module.BACK_POS=95
        module.SKEW=100
        module.QUOTE=200
        bot.position=95
        bot.orders={'bid-old':[1,100,5,False]}
        snapshot=OrderBookSnapshot(timestamp_us=1000,
            bids=[BookOrderView('m-b',Side.BUY,100,1000,'market')],
            asks=[BookOrderView('m-a',Side.SELL,102,1000,'market')])
        bot.on_order_book_change(snapshot,[])
        self.assertIn('bid-old',canceled)
        self.assertFalse(any(o.side==Side.BUY for o in sent))
        bot.on_private_order_update(PrivateOrderEvent(timestamp_us=6000,order_id='bid-old',status=OrderStatus.CANCELED))
        bot.on_order_book_change(snapshot,[])
        bid=[o for o in sent if o.side==Side.BUY][-1]
        self.assertEqual((bid.price,bid.quantity),(99,5))


if __name__=='__main__':
    unittest.main(verbosity=2)
