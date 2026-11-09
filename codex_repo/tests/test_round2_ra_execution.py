"""Partial fills and cancellation reservations in passive-first execution."""
import tempfile
import unittest
from pathlib import Path
from scripts.round2_ra_execution import build
from simulator.main import load_strategy_from_file
from simulator.models import OrderStatus,OrderType,PrivateOrderEvent
from simulator.strategy import StrategyContext


class RAExecutionTests(unittest.TestCase):
    def test_passive_timeout_waits_for_cancel_and_crosses_only_remainder(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'s.py';p.write_text(build()['wait20_improve1'])
            bot=load_strategy_from_file(p);sent=[];cancels=[]
            def submit(request):sent.append(request);return str(len(sent))
            bot._attach_context(StrategyContext(submit,cancels.append,lambda *_:None,lambda:0))
            bot._execute(0,100,99,102)
            self.assertEqual(sent[0].order_type,OrderType.LIMIT)
            self.assertEqual(sent[0].price,100)
            bot.on_private_order_update(PrivateOrderEvent(timestamp_us=5000,order_id='1',status=OrderStatus.ACCEPTED,remaining_quantity=100))
            bot.on_private_order_update(PrivateOrderEvent(timestamp_us=6000,order_id='1',status=OrderStatus.PARTIALLY_FILLED,filled_quantity=60,remaining_quantity=40,fill_price=100))
            bot._execute(20000,100,99,102)
            self.assertEqual(cancels,['1'])
            bot._execute(21000,100,99,102)
            self.assertEqual(len(sent),1)
            self.assertEqual(bot._room(1),0)
            bot.on_private_order_update(PrivateOrderEvent(timestamp_us=25000,order_id='1',status=OrderStatus.CANCELED,remaining_quantity=0))
            bot._execute(26000,100,99,102)
            self.assertEqual(sent[1].order_type,OrderType.IOC)
            self.assertEqual(sent[1].quantity,40)

    def test_flat_target_does_not_wait_passively(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'s.py';p.write_text(build()['wait100_improve0'])
            bot=load_strategy_from_file(p);sent=[]
            def submit(request):sent.append(request);return str(len(sent))
            bot._attach_context(StrategyContext(submit,lambda *_:None,lambda *_:None,lambda:0))
            bot._pos=100;bot._execute(0,0,99,101)
            self.assertEqual(sent[0].order_type,OrderType.IOC)
            self.assertEqual(sent[0].quantity,100)


if __name__=='__main__':unittest.main()
