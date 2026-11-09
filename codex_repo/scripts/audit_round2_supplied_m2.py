"""Audit the exact user-supplied IOC strategy and latency sensitivity."""
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
import hashlib
import json
from scripts.benchmark import AuditedSimulator,digest,evaluate
from scripts.round2_workbench import BoundaryMarkEngine,load_manifest,write_json
from simulator.main import load_strategy_from_file
from simulator.models import OrderStatus
from simulator.simulator import SimulationConfig

ROOT=Path('logs/round2_supplied_m2')
SOURCE=Path('strategies/round2_big_aggressor_supplied.py')


class SuppliedAudit(AuditedSimulator):
    boundaries=()
    delay=5
    def __init__(self,strategy,config):
        config=config.model_copy(update={'order_accept_delay_ms':self.delay})
        super().__init__(strategy,config)
        self.boundary_pnl={str(t):None for t in self.boundaries}
        self._audited_cash=0
    _boundary_value=BoundaryMarkEngine._boundary_value
    def _advance_time(self,timestamp_us):
        for boundary in self.boundaries:
            key=str(boundary)
            if self.boundary_pnl[key] is None and self.current_ts_us<boundary<=timestamp_us:
                self.boundary_pnl[key]=self._boundary_value(boundary)
        super()._advance_time(timestamp_us)

    def run(self,path):
        result=super().run(path)
        for boundary in self.boundaries:
            if self.boundary_pnl[str(boundary)] is None and boundary>=self.current_ts_us:
                self.boundary_pnl[str(boundary)]=self._boundary_value(boundary)
        return result

    def _private_notify(self,event):
        record=self.strategy._orders.get(event.order_id)
        if event.status in (OrderStatus.FILLED,OrderStatus.PARTIALLY_FILLED):
            assert record is not None
            self._audited_cash-=record[0]*event.filled_quantity*event.fill_price
        super()._private_notify(event)
        assert self.strategy._pos==self._inventory
        assert self._audited_cash==self._cash
        assert abs(self._inventory)<=100
        for sign in (-1,1):
            reserved=sum(r[2] for r in self.strategy._orders.values() if r[0]==sign)
            assert sign*self._inventory+reserved<=100


def run(delay):
    m=load_manifest(Path('logs/round2_local_intake'))
    SuppliedAudit.delay=delay
    SuppliedAudit.boundaries=(m['first_us']+1800_000_000,m['development_cutoff_us'],m['validation_cutoff_us'])
    strategy=load_strategy_from_file(SOURCE)
    r=evaluate(strategy,Path(m['data']),ROOT/f'delay{delay}',600,SuppliedAudit)
    assert r['max_potential_inventory_at_submission']<=100
    assert r['result']['breach_penalty']==0
    r.update(source_sha256=digest(SOURCE),data_sha256=m['data_sha256'],delay_ms=delay,
             first80=r['boundary_pnl'][str(m['validation_cutoff_us'])])
    r['last20']=r['result']['pnl']-r['first80']
    # evaluate() prints its input config, so record the effective stress config explicitly.
    r['config']['order_accept_delay_ms']=delay
    return r


def main():
    ROOT.mkdir(exist_ok=True)
    p=ROOT/'audit_results.json'
    results=json.loads(p.read_text()) if p.exists() else {}
    for r in results.values():assert r['source_sha256']==digest(SOURCE)
    with ProcessPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(run,delay):str(delay) for delay in (5,10,20,50) if str(delay) not in results}
        for job in as_completed(jobs):
            delay=jobs[job];results[delay]=job.result();write_json(p,results)
            print(delay,'ms',results[delay]['result']['pnl'],'first80',results[delay]['first80'],'last20',results[delay]['last20'],flush=True)


if __name__=='__main__':main()
