import tempfile
import unittest
from pathlib import Path

from scripts.round2_fill_attribution import AttributionEngine
from simulator.main import load_strategy_from_file
from simulator.simulator import ExchangeSimulator,SimulationConfig


class AttributionTests(unittest.TestCase):
    def test_exact_identity_and_unchanged_native_fields_after_fills(self):
        tape='''Time,Operation,OrderId,Side,Volume,Price,Lifespan
0.000000,Insert,b,B,20,99,G
0.000001,Insert,a,A,20,101,G
0.010000,Insert,t,A,25,99,F
0.020000,Insert,b2,B,20,98,G
0.030000,Cancel,missing,,,,
'''
        config=SimulationConfig(max_position=100,max_potential_position=1000,
            position_breach_penalty_per_second=10000,order_accept_delay_ms=5,public_depth=20)
        source=Path('strategies/round2/round2_transfer.py')
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'tape.csv';p.write_text(tape)
            baseline=ExchangeSimulator(load_strategy_from_file(source),config).run(p)
            engine=AttributionEngine(load_strategy_from_file(source),config)
            actual=engine.run(p)
        self.assertEqual(actual.model_dump(),baseline.model_dump())
        self.assertGreater(actual.traded_volume,0)
        attribution=engine.attribution(actual)
        self.assertAlmostEqual(attribution['identity_net_pnl'],actual.pnl)
        self.assertNotEqual(attribution['execution_edge_at_previous_mid'],0)


if __name__=='__main__':unittest.main()
