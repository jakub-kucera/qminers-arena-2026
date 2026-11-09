import tempfile
import unittest
from pathlib import Path
from scripts.validate_round1 import BoundaryEngine,final_timestamp_us
from simulator.simulator import ExchangeSimulator,SimulationConfig
from strategies.round1_ofi_base import PassiveStrategy


class BuyOnce(PassiveStrategy):
    def on_order_book_change(self,snapshot,trades):
        if snapshot.timestamp_us==1:self._quote(1,1,101)


class BoundaryTests(unittest.TestCase):
    def test_marks_respect_latency_and_do_not_change_final_result(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'data.csv'
            path.write_text('Time,Operation,OrderId,Side,Volume,Price,Lifespan\n'
                '0,Insert,b,B,100,99,G\n0.000001,Insert,a,A,1000,101,G\n'
                '0.020000,Cancel,unknown,,,,\n0.030000,Cancel,b,,,,\n')
            BoundaryEngine.boundaries=(3000,10000)
            config=SimulationConfig(max_position=100,max_potential_position=1000,
                position_breach_penalty_per_second=10000,order_accept_delay_ms=5)
            engine=BoundaryEngine(BuyOnce(),config)
            marked=engine.run(path)
            original=ExchangeSimulator(BuyOnce(),config).run(path)
            self.assertEqual(engine.boundary_pnl,{'3000':0,'10000':-200})
            self.assertEqual(marked.model_dump(),original.model_dump())
            self.assertEqual(final_timestamp_us(path),30000)


if __name__=='__main__':unittest.main()
