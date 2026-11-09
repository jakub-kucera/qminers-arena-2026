"""Small, deterministic integration probes of official order lifecycle and risk."""
import csv
import tempfile
import unittest
from pathlib import Path
from run_study import config, dump, OUT
from simulator.models import OrderRequest, OrderStatus, OrderType, Side
from simulator.simulator import ExchangeSimulator
from simulator.strategy import BaseStrategy


class Scripted(BaseStrategy):
    def __init__(self, quantity=5, cancel_at=None, modify_at=None, ioc=False):
        super().__init__()
        self.quantity, self.cancel_at, self.modify_at, self.ioc = quantity, cancel_at, modify_at, ioc
        self.oid = None
        self.events = []
        self.cancel_sent = self.modify_sent = False

    def on_order_book_change(self, snapshot, trades):
        if not snapshot.bids or not snapshot.asks:
            return
        if self.oid is None:
            self.oid = self.send_order(OrderRequest(side=Side.BUY,price=101,quantity=self.quantity,
                order_type=OrderType.IOC if self.ioc else OrderType.LIMIT))
        if self.cancel_at is not None and snapshot.timestamp_us >= self.cancel_at and not self.cancel_sent:
            self.cancel_order(self.oid)
            self.cancel_sent = True
        if self.modify_at is not None and snapshot.timestamp_us >= self.modify_at and not self.modify_sent:
            self.modify_order(self.oid, self.quantity+1)
            self.modify_sent = True

    def on_private_order_update(self,event):
        self.events.append(event.model_dump(mode='json'))


def replay(bot, rows):
    with tempfile.TemporaryDirectory() as folder:
        path=Path(folder)/'tape.csv'
        with path.open('w',newline='') as f:
            w=csv.writer(f)
            w.writerow(['Time','Operation','OrderId','Side','Volume','Price','Lifespan'])
            w.writerows(rows)
        result=ExchangeSimulator(bot,config()).run(path)
    return result


BASE = [[0,'Insert','b','B',100,100,'G'],[0,'Insert','a','A',200,104,'G']]


class EngineProbes(unittest.TestCase):
    records = {}

    def test_delayed_accept_partial_fill_and_cancel_race(self):
        bot=Scripted(cancel_at=6000)
        result=replay(bot,BASE+[
            [.003,'Insert','early','A',3,101,'F'],
            [.006,'Insert','partial','A',2,101,'F'],
            [.008,'Insert','race','A',3,101,'F'],
            [.012,'Cancel','missing','','','','']])
        fills=[e for e in bot.events if e['filled_quantity']]
        accepted=[e for e in bot.events if e['status']==OrderStatus.ACCEPTED.value]
        self.assertEqual(accepted[0]['timestamp_us'],5000)
        self.assertEqual([(e['timestamp_us'],e['filled_quantity']) for e in fills],[(6000,2),(8000,3)])
        self.assertEqual(result.inventory,5)
        self.records['cancel_race']={'result':result.model_dump(mode='json'),'events':bot.events}

    def test_rejected_modify_keeps_original_order(self):
        bot=Scripted(modify_at=6000)
        result=replay(bot,BASE+[[.006,'Cancel','missing','','','',''],
            [.012,'Insert','seller','A',5,101,'F']])
        self.assertTrue(any(e['status']==OrderStatus.REJECTED.value for e in bot.events))
        self.assertEqual(result.inventory,5)
        self.records['modify_rejection']={'result':result.model_dump(mode='json'),'events':bot.events}

    def test_price_time_queue_and_maker_price(self):
        bot=Scripted()
        result=replay(bot,[[0,'Insert','oldbid','B',100,101,'G'],[0,'Insert','ask','A',200,104,'G'],
            [.006,'Insert','seller1','A',103,100,'F'],
            [.007,'Insert','seller2','A',2,100,'F']])
        fills=[e for e in bot.events if e['filled_quantity']]
        self.assertEqual([e['filled_quantity'] for e in fills],[3,2])
        self.assertTrue(all(e['fill_price']==101 for e in fills))
        self.assertEqual(result.inventory,5)
        self.records['queue_priority']={'result':result.model_dump(mode='json'),'events':bot.events}

    def test_penalty_is_time_above_100(self):
        bot=Scripted(quantity=101,ioc=True)
        result=replay(bot,[[0,'Insert','b','B',500,100,'G'],[0,'Insert','a','A',500,101,'G'],
            [1.005,'Cancel','missing','','','','']])
        self.assertEqual(result.inventory,101)
        self.assertAlmostEqual(result.breach_penalty,10000)
        self.records['penalty']={'result':result.model_dump(mode='json'),'events':bot.events}

    def test_potential_limit_rejects_1001(self):
        bot=Scripted(quantity=1001,ioc=True)
        result=replay(bot,[[0,'Insert','b','B',5000,100,'G'],[0,'Insert','a','A',5000,101,'G'],
            [.010,'Cancel','missing','','','','']])
        self.assertEqual(result.inventory,0)
        self.assertTrue(any(e['status']==OrderStatus.REJECTED.value for e in bot.events))
        self.records['hard_limit']={'result':result.model_dump(mode='json'),'events':bot.events}

    @classmethod
    def tearDownClass(cls):
        dump(OUT/'engine_probes.json',cls.records)


if __name__=='__main__':
    unittest.main(verbosity=2)
