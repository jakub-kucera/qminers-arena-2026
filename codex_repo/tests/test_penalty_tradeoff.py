"""Economic fee boundaries and asynchronous recovery safety."""
import tempfile
import unittest
from pathlib import Path

from scripts.check_submission import check
from scripts.probe_penalty_tradeoff import PenaltyAudit, activation_variants, generate
from simulator.main import load_strategy_from_file
from simulator.models import OrderStatus, OrderType, PrivateOrderEvent, Side
from simulator.simulator import ExchangeSimulator, SimulationConfig
from simulator.strategy import StrategyContext


class Gateway:
    def __init__(self, strategy):
        self.sent = []
        self.canceled = []
        strategy._attach_context(StrategyContext(self.send, self.cancel, lambda *_: None, lambda: 0))
    def send(self, request):
        self.sent.append(request)
        return 'u'+str(len(self.sent))
    def cancel(self, oid):
        self.canceled.append(oid)


class PenaltyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temp.name)
        cls.sources, cls.specs = generate(Path('strategies/round1_robust_candidate.py').read_text())
        more, specs = activation_variants(Path('strategies/round1_robust_candidate.py').read_text())
        cls.sources.update(more);cls.specs.update(specs)
        for name, text in cls.sources.items():
            (cls.folder/(name+'.py')).write_text(text)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def bot(self, name='burst_500_hold0_edge0p5'):
        return load_strategy_from_file(self.folder/(name+'.py'))

    def config(self):
        return SimulationConfig(max_position=100, max_potential_position=1000,
                                position_breach_penalty_per_second=10000,
                                order_accept_delay_ms=5, public_depth=20)

    def test_fee_is_flat_strict_and_time_proportional(self):
        for inventory in (101, 250, 1000, -101, -1000):
            engine = ExchangeSimulator(self.bot('baseline'), self.config())
            engine._advance_time(0)
            engine._inventory = inventory
            engine._advance_time(5000)
            self.assertAlmostEqual(engine._breach_penalty, 50)
            engine._inventory = 100
            engine._advance_time(105000)
            self.assertAlmostEqual(engine._breach_penalty, 50)
        engine = ExchangeSimulator(self.bot('baseline'), self.config())
        engine._advance_time(0)
        engine._last_trade_price = 100
        engine._inventory = -100
        engine._advance_time(1000000)
        self.assertEqual(engine._breach_penalty, 0)

    def test_hard_limit_is_not_the_soft_penalty_threshold(self):
        engine = ExchangeSimulator(self.bot('baseline'), self.config())
        self.assertFalse(engine._exceeds_position_limit(Side.BUY, 1000))
        self.assertTrue(engine._exceeds_position_limit(Side.BUY, 1001))
        self.assertFalse(engine._exceeds_position_limit(Side.SELL, 1000))

    def test_all_variants_pass_static_submission_checks(self):
        for name in self.sources:
            self.assertEqual(check(self.folder/(name+'.py')), [], name)

    def test_extra_budget_requires_signal_and_already_aligned_inventory(self):
        for inventory, signal, expected in [(0, 2, 100), (80, .4, 20), (80, .6, 420), (100, .6, 400)]:
            s = self.bot();g = Gateway(s)
            s.inventory = inventory;s._signal_edge = signal
            s._quote(0, 1, 99)
            self.assertEqual(g.sent[-1].quantity, expected)
            self.assertLessEqual(s.inventory+sum(r[2] for r in s._orders.values() if r[0]>0), 500)

    def test_activation_probe_exercises_budget_from_flat_inventory(self):
        s=self.bot('active_1000_hold0_edge0p0');g=Gateway(s)
        s._signal_edge=.1
        s._quote(0,1,99)
        self.assertEqual(g.sent[-1].quantity,1000)
        self.assertEqual(sum(r[2] for r in s._orders.values()),1000)

    def test_pending_cancel_does_not_release_extra_budget(self):
        s = self.bot();g = Gateway(s)
        s.inventory = 100;s._signal_edge = 1
        s._quote(0, 1, 99)
        s.on_private_order_update(PrivateOrderEvent(timestamp_us=5000, order_id='u1',
                                  status=OrderStatus.ACCEPTED, remaining_quantity=400))
        s._quote(6000, 1, 98)
        self.assertEqual(g.canceled, ['u1'])
        self.assertEqual(len(g.sent), 1)
        self.assertEqual(s._orders['u1'][2], 400)

    def test_exit_reserves_existing_opposite_quotes_and_partial_ioc(self):
        s = self.bot();g = Gateway(s)
        s.inventory = 100;s._signal_edge = 1;s._market_bid = 99;s._market_ask = 101
        s._quote(0, 1, 99);s._quote(0, -1, 101)
        for oid, qty in [('u1',400),('u2',200)]:
            s.on_private_order_update(PrivateOrderEvent(timestamp_us=5000,order_id=oid,
                                     status=OrderStatus.ACCEPTED,remaining_quantity=qty))
        s.on_private_order_update(PrivateOrderEvent(timestamp_us=6000,order_id='u1',
            status=OrderStatus.PARTIALLY_FILLED,filled_quantity=200,remaining_quantity=200,fill_price=99))
        self.assertTrue(s._closing)
        self.assertEqual(g.sent[-1].order_type, OrderType.IOC)
        self.assertEqual(g.sent[-1].quantity, 200)
        self.assertGreaterEqual(s.inventory-sum(r[2] for r in s._orders.values() if r[0]<0), -100)
        s.on_private_order_update(PrivateOrderEvent(timestamp_us=11000,order_id='u3',
            status=OrderStatus.ACCEPTED,remaining_quantity=200))
        count = len(g.sent)
        s.on_private_order_update(PrivateOrderEvent(timestamp_us=11000,order_id='u3',
            status=OrderStatus.PARTIALLY_FILLED,filled_quantity=50,remaining_quantity=150,fill_price=99))
        self.assertEqual(len(g.sent), count)
        self.assertEqual(s._orders['u3'][2], 150)
        self.assertLessEqual(s.inventory+sum(r[2] for r in s._orders.values() if r[0]>0), 500)

    def test_real_engine_burst_pays_latency_fee_and_returns_to_soft_limit(self):
        path = self.folder/'burst.csv'
        path.write_text('Time,Operation,OrderId,Side,Volume,Price,Lifespan\n'
            '0,Insert,b,B,1000,99,G\n0.000001,Insert,a,A,10,101,G\n'
            '0.010000,Insert,t1,A,100,100,F\n0.020000,Insert,t2,A,200,100,F\n'
            '0.026000,Cancel,unknown,,,,\n0.030000,Cancel,unknown,,,,\n')
        s = self.bot();s.BURST_EDGE = 0
        engine = PenaltyAudit(s, self.config(), [15000, 22000, 28000])
        result = engine.run(path)
        self.assertEqual(result.inventory, 100)
        self.assertAlmostEqual(result.breach_penalty, 50)
        self.assertEqual(engine.breach_us, 5000)
        self.assertEqual(engine.max_inventory, 300)
        self.assertLessEqual(engine.max_potential, 500)
        self.assertAlmostEqual(result.pnl, -350)
        self.assertEqual(engine.new_order_rejections, 0)

    def test_observer_and_disabled_controller_preserve_official_result(self):
        path = self.folder/'burst.csv'
        path.write_text('Time,Operation,OrderId,Side,Volume,Price,Lifespan\n'
            '0,Insert,b,B,1000,99,G\n0.000001,Insert,a,A,10,101,G\n'
            '0.010000,Insert,t1,A,100,100,F\n0.020000,Insert,t2,A,200,100,F\n'
            '0.026000,Cancel,unknown,,,,\n0.030000,Cancel,unknown,,,,\n')
        original = ExchangeSimulator(self.bot('baseline'), self.config()).run(path)
        for name in ('baseline','guard_disabled'):
            audit = PenaltyAudit(self.bot(name), self.config(), [15000,22000,28000]).run(path)
            self.assertEqual(original.model_dump(), audit.model_dump())


if __name__=='__main__':unittest.main()
