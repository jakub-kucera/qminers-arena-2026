"""Short passive-entry grace periods followed by native IOC execution."""
from concurrent.futures import ProcessPoolExecutor,as_completed
from pathlib import Path
import json
from scripts.audit_round2_supplied_m2 import SuppliedAudit
from scripts.benchmark import digest,evaluate
from scripts.check_submission import check
from scripts.round2_workbench import load_manifest,write_json
from simulator.main import load_strategy_from_file

ROOT=Path('logs/round2_ra_execution')


def build():
    original=Path('research/round2_ra_supplied_20261107/original_submission.py').read_text()
    body=original.split('"""',2)[2]
    base='"""Experimental passive-first RA execution. Prior scores do not apply."""'+body
    base=base.replace('        self._pos = 0','''        self._exec_target=None
        self._exec_deadline=0
        self._exec_passive=False
        self._exec_accepted=False
        self._exec_cancel=False
        self._pos = 0''',1)
    base=base.replace('order_type=OrderType.IOC)','order_type=OrderType.LIMIT if self._exec_passive else OrderType.IOC)',1)
    begin=base.index('        if self._taker_id is not None:\n            return')
    end=base.index('    def on_private_order_update',begin)
    base=base[:begin]+'''        self._execute(now,target,best_bid,best_ask)

'''+base[end:]
    anchor='        status = event.status'
    base=base.replace(anchor,'''        if event.order_id==self._taker_id and event.status==OrderStatus.ACCEPTED:
            self._exec_accepted=True
'''+anchor,1)
    cases={}
    for wait_ms,improve in ((20,0),(20,1),(100,0),(100,1)):
        method=f'''    def _execute(self,now,target,bid,ask):
        changed=target!=self._exec_target
        if changed:
            self._exec_target=target
            self._exec_deadline=now+{wait_ms*1000}
        if self._taker_id is not None:
            if self._exec_passive and self._exec_accepted and not self._exec_cancel:
                if changed or target==self._pos or now>=self._exec_deadline:
                    self.cancel_order(self._taker_id)
                    self._exec_cancel=True
            return
        want=target-self._pos
        if not want:
            return
        # Stops flatten immediately; directional entries/flips get one short grace period.
        self._exec_passive=target!=0 and now<self._exec_deadline
        self._exec_accepted=False
        self._exec_cancel=False
        sign=1 if want>0 else -1
        if self._exec_passive:
            price=min(ask-1,bid+{improve}) if sign>0 else max(bid+1,ask-{improve})
        else:
            price=ask if sign>0 else bid
        self._taker_id=self._send(sign,price,abs(want))

'''
        cases[f'wait{wait_ms}_improve{improve}']=base.replace('    def on_private_order_update',method+'    def on_private_order_update',1)
    return cases


def run(candidate):
    m=load_manifest(Path('logs/round2_local_intake'))
    SuppliedAudit.delay=5
    SuppliedAudit.boundaries=(m['first_us']+1800000000,m['development_cutoff_us'],m['validation_cutoff_us'])
    r=evaluate(load_strategy_from_file(candidate['file']),Path(m['validation_prefix']),ROOT/candidate['name'],600,SuppliedAudit)
    r.update(source_sha256=digest(candidate['file']),data_sha256=m['validation_prefix_sha256'])
    b=r['boundary_pnl']
    r['later30']=b[str(m['development_cutoff_us'])]-b[str(m['first_us']+1800000000)]
    r['last20']=b[str(m['validation_cutoff_us'])]-b[str(m['development_cutoff_us'])]
    return r


def main():
    ROOT.mkdir(exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    candidates=[]
    for name,text in build().items():
        p=ROOT/'sources'/(name+'.py')
        if p.exists():assert p.read_text()==text
        else:p.write_text(text)
        assert not check(p),check(p)
        candidates.append(dict(name=name,file=str(p),source_sha256=digest(p)))
    protocol=dict(goal=250000,candidates=candidates,scope='Consumed first80% local public data.',
        hypothesis='Reduce entry spread cost with 20/100ms passive grace and 0/1 tick improvement, then cross. Stops remain immediate IOC.',
        safeguards='One outstanding order. Cancellations remain reserved until terminal confirmation.',
        selection='Positive later30 and last20; maximize combined gain; freeze before full replay.')
    p=ROOT/'protocol.json'
    if p.exists():assert json.loads(p.read_text())==protocol
    else:write_json(p,protocol)
    p=ROOT/'results.json';results=json.loads(p.read_text()) if p.exists() else {}
    with ProcessPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(run,c):c['name'] for c in candidates if c['name'] not in results}
        for job in as_completed(jobs):
            name=jobs[job];r=job.result();results[name]=r;write_json(p,results)
            print(name,r['result']['pnl'],r['later30'],r['last20'],flush=True)


if __name__=='__main__':main()
