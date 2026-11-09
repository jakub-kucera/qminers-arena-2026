"""Bounded large-aggressor feature/execution alternatives, consumed first80% only."""
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
import json
from scripts.benchmark import digest,evaluate
from scripts.round2_workbench import load_manifest,write_json
from scripts.audit_round2_supplied_m2 import SuppliedAudit
from scripts.check_submission import check
from simulator.main import load_strategy_from_file

ROOT=Path('logs/round2_m2_alternatives')


def build():
    original=Path('strategies/round2_big_aggressor_supplied.py').read_text()
    _,_,body=original.split('"""',2)
    base='"""Experimental M2 extension. Scores must come from its own replay."""'+body
    cases={'cross1':base.replace('CROSS = 0','CROSS = 1',1),
           'hold5s':base.replace('HOLD_MS = 0','HOLD_MS = 5000',1)}
    begin=base.index('        net = 0\n')
    end=base.index('        if net >= MIN_LOTS:',begin)
    for kind in ('executed_plus_rest','resting_only','nonresting_only'):
        code='''        visible={o.order_id:o for side in (snapshot.bids,snapshot.asks) for o in side if o.owner=='market'}
        aggressors={}
        for trade in trades:
            if trade.taker_owner=='market':
                row=aggressors.setdefault(trade.taker_order_id,[1 if trade.book_side=='ask' else -1,0])
                row[1]+=trade.quantity
        net=0
        for oid,(sign,quantity) in aggressors.items():
'''
        if kind=='executed_plus_rest':
            code+='''            if oid in visible:
                quantity+=visible[oid].quantity
            net+=sign*quantity
'''
        elif kind=='resting_only':
            code+='''            if oid in visible:
                net+=sign*quantity
'''
        else:
            code+='''            if oid not in visible:
                net+=sign*quantity
'''
        cases[kind]=base[:begin]+code+base[end:]
    return cases


def run(name,path):
    m=load_manifest(Path('logs/round2_local_intake'))
    SuppliedAudit.delay=5;SuppliedAudit.boundaries=(m['first_us']+1800000000,m['development_cutoff_us'],m['validation_cutoff_us'])
    r=evaluate(load_strategy_from_file(path),Path(m['validation_prefix']),ROOT/name,600,SuppliedAudit)
    assert r['max_potential_inventory_at_submission']<=100 and r['result']['breach_penalty']==0
    r.update(source_sha256=digest(path),data_sha256=m['validation_prefix_sha256'])
    marks=r['boundary_pnl']
    r['later30']=marks[str(m['development_cutoff_us'])]-marks[str(m['first_us']+1800000000)]
    r['last20']=marks[str(m['validation_cutoff_us'])]-marks[str(m['development_cutoff_us'])]
    return r


def main():
    ROOT.mkdir(exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    sources={}
    for name,text in build().items():
        path=ROOT/'sources'/(name+'.py')
        if path.exists():assert path.read_text()==text
        else:path.write_text(text)
        assert not check(path),check(path)
        sources[name]=dict(file=str(path),sha256=digest(path))
    protocol=dict(goal=150000,sources=sources,scope='Consumed first80%; no new independent holdout.',
                  selection='Require positive 30-60m and 60-80m increments; compare their combined gain before freezing a full replay.',
                  caveat='Resting visibility is observable, not a reliable identification of participant or original order type.')
    p=ROOT/'protocol.json'
    if p.exists():assert json.loads(p.read_text())==protocol
    else:write_json(p,protocol)
    p=ROOT/'results.json';results=json.loads(p.read_text()) if p.exists() else {}
    with ProcessPoolExecutor(max_workers=5) as pool:
        jobs={pool.submit(run,name,Path(spec['file'])):name for name,spec in sources.items() if name not in results}
        for job in as_completed(jobs):
            name=jobs[job];results[name]=job.result();write_json(p,results)
            print(name,results[name]['result']['pnl'],'later30',results[name]['later30'],'last20',results[name]['last20'],flush=True)


if __name__=='__main__':main()
