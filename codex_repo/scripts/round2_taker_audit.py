"""Native replays with an independent private-fill ledger for both strategy APIs.

Supports the imported maker's inventory/cash fields and flow trader's _pos.
Exchange/evaluator files are unchanged. Strict candidates must retain every
live reservation and pay zero breach penalty under the native rules.
"""
import json
from concurrent.futures import ProcessPoolExecutor,as_completed
from pathlib import Path

from scripts.benchmark import AuditedSimulator,digest,evaluate
from scripts.check_submission import check
from scripts.round2_workbench import BoundaryMarkEngine,native_stamp,write_json
from simulator.main import load_strategy_from_file
from simulator.models import OrderStatus,Side


class TakerAuditEngine(BoundaryMarkEngine):
    def __init__(self,strategy,config):
        super().__init__(strategy,config)
        self._audit_signs={};self._audit_inventory=0;self._audit_cash=0

    def submit_order(self,request):
        oid=super().submit_order(request)
        self._audit_signs[oid]=1 if request.side==Side.BUY else -1
        return oid

    def _private_notify(self,event):
        # Bypass only CandidateEngine's field-name-specific diagnostic. The
        # original native notification and existing generic audit still run.
        if event.status in (OrderStatus.FILLED,OrderStatus.PARTIALLY_FILLED):
            sign=self._audit_signs[event.order_id]
            self._audit_inventory+=sign*event.filled_quantity
            self._audit_cash-=sign*event.filled_quantity*event.fill_price
        AuditedSimulator._private_notify(self,event)
        assert self._audit_inventory==self._inventory,'Independent fill-position ledger mismatch'
        assert self._audit_cash==self._cash,'Independent fill-cash ledger mismatch'
        s=self.strategy
        position=s.inventory if hasattr(s,'inventory') else s._pos
        assert position==self._inventory,'Strategy position differs from native engine'
        if hasattr(s,'cash'):assert s.cash==self._cash,'Strategy cash differs from native engine'
        if event.status in (OrderStatus.FILLED,OrderStatus.CANCELED):self._audit_signs.pop(event.order_id,None)


def run(candidate,data,out,boundaries=()):
    source=Path(candidate['file']);assert digest(source)==candidate['source_sha256']
    assert not check(source),check(source)
    TakerAuditEngine.boundaries=tuple(sorted(boundaries))
    r=evaluate(load_strategy_from_file(source),Path(data),Path(out),1000,TakerAuditEngine)
    assert all(v is not None for v in r['boundary_pnl'].values())
    assert r['max_potential_inventory_at_submission']<=1000
    if candidate.get('risk')=='strict100':
        assert r['max_abs_inventory']<=100 and r['max_potential_inventory_at_submission']<=100
        assert r['result']['breach_penalty']==0
    r.update(source=str(source),source_sha256=digest(source),data_sha256=digest(data),
        independent_private_ledger=True,risk_contract=candidate.get('risk','native'))
    return r


def batch(candidates,data,out,boundaries=(),workers=3,scope='Reused public diagnostic'):
    out=Path(out);out.mkdir(parents=True,exist_ok=True);path=out/'results.json'
    stamp=dict(native=native_stamp(),data_sha256=digest(data),runner_sha256=digest(__file__))
    report=json.loads(path.read_text()) if path.exists() else dict(**stamp,scope=scope,results={})
    assert all(report[k]==v for k,v in stamp.items()),'Cache input/evaluator changed'
    for c in candidates:
        if c['name'] in report['results']:assert report['results'][c['name']]['source_sha256']==c['source_sha256']
    write_json(out/'specs.json',dict(**stamp,candidates=candidates,boundaries_us=list(boundaries),scope=scope))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        jobs={pool.submit(run,c,data,out/c['name'],boundaries):c['name'] for c in candidates if c['name'] not in report['results']}
        for job in as_completed(jobs):
            name=jobs[job];r=job.result();report['results'][name]=r;write_json(path,report)
            print(name,'NET',r['result']['pnl'],'FEE',r['result']['breach_penalty'],
                'MAX',r['max_abs_inventory'],'POTENTIAL',r['max_potential_inventory_at_submission'],flush=True)
    return report
