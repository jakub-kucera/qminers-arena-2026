"""Predeclared nearby-parameter checks; supplied defaults remain frozen."""
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
import json
from scripts.benchmark import digest,evaluate
from scripts.round2_workbench import load_manifest,write_json
from scripts.audit_round2_supplied_m2 import SuppliedAudit
from scripts.check_submission import check
from simulator.main import load_strategy_from_file

ROOT=Path('logs/round2_m2_robustness')


def run(name,path):
    m=load_manifest(Path('logs/round2_local_intake'))
    SuppliedAudit.delay=5;SuppliedAudit.boundaries=(m['development_cutoff_us'],m['validation_cutoff_us'])
    r=evaluate(load_strategy_from_file(path),Path(m['validation_prefix']),ROOT/name,600,SuppliedAudit)
    assert r['max_potential_inventory_at_submission']<=100 and r['result']['breach_penalty']==0
    r.update(source_sha256=digest(path),data_sha256=m['validation_prefix_sha256'])
    r['minute60to80']=r['boundary_pnl'][str(m['validation_cutoff_us'])]-r['boundary_pnl'][str(m['development_cutoff_us'])]
    return r


def main():
    ROOT.mkdir(exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    base=Path('strategies/round2_big_aggressor_supplied.py').read_text()
    cases={'lots400':base.replace('MIN_LOTS = 500','MIN_LOTS = 400',1),
           'lots600':base.replace('MIN_LOTS = 500','MIN_LOTS = 600',1),
           'gate5':base.replace('GATE_TICKS = 10','GATE_TICKS = 5',1),
           'gate20':base.replace('GATE_TICKS = 10','GATE_TICKS = 20',1)}
    sources={}
    for name,text in cases.items():
        path=ROOT/'sources'/(name+'.py')
        if path.exists():assert path.read_text()==text
        else:path.write_text(text)
        assert not check(path),check(path)
        sources[name]=dict(file=str(path),sha256=digest(path))
    protocol=dict(scope='Previously consumed first80%; robustness description, not independent validation.',
                  choice='Keep exact supplied defaults. Do not select a different threshold from these probes.',sources=sources)
    p=ROOT/'protocol.json'
    if p.exists():assert json.loads(p.read_text())==protocol
    else:write_json(p,protocol)
    p=ROOT/'results.json';results=json.loads(p.read_text()) if p.exists() else {}
    with ProcessPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(run,name,Path(spec['file'])):name for name,spec in sources.items() if name not in results}
        for job in as_completed(jobs):
            name=jobs[job];results[name]=job.result();write_json(p,results)
            print(name,results[name]['result']['pnl'],'last20',results[name]['minute60to80'],flush=True)


if __name__=='__main__':main()
