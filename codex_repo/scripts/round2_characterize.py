"""Describe predeclared candidates on historical tapes; never select a round-2 winner."""
import argparse
import json
from concurrent.futures import ProcessPoolExecutor,as_completed
from pathlib import Path

from scripts.benchmark import digest
from scripts.round2_workbench import native_stamp,run_candidate,write_json,REGISTRY,REPO


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=REPO/'logs/round2_preparation/historical')
    parser.add_argument('--backtest',type=Path,action='append')
    parser.add_argument('--workers',type=int,default=4)
    args=parser.parse_args()
    if args.workers<1:parser.error('--workers must be positive')
    data=args.backtest or [REPO/'data'/n for n in ('sample.csv','sample_v2.csv','round1.csv')]
    if len({p.stem for p in data})!=len(data):parser.error('Dataset stems must be unique')
    registry=json.loads(REGISTRY.read_text());candidates=registry['candidates']
    for c in candidates:
        c['file']=str(REPO/c['file'])
        assert digest(c['file'])==c['source_sha256']
    protocol=native_stamp();fingerprints={p.stem:digest(p) for p in data}
    preserved=json.loads((REPO/'results/round1_624076.json').read_text())
    output=args.output;output.mkdir(parents=True,exist_ok=True);report_path=output/'report.json'
    report={'native':protocol,'registry_sha256':digest(REGISTRY),'datasets':fingerprints,
        'results':{},'limitation':'All tapes are historical/previously inspected. These are transfer and execution checks, not round-2 validation or a candidate selection.'}
    if report_path.exists():
        previous=json.loads(report_path.read_text())
        for key in ('native','registry_sha256','datasets'):
            if previous[key]!=report[key]:raise ValueError('Historical report provenance changed; use a new directory')
        report=previous
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        jobs={pool.submit(run_candidate,c,p,output/p.stem/c['name']):(p.stem,c['name'])
              for p in data for c in candidates if c['name'] not in report['results'].get(p.stem,{})}
        for job in as_completed(jobs):
            dataset,name=jobs[job];r=job.result()
            report['results'].setdefault(dataset,{})[name]=r
            if name=='round2_transfer' and r['data_sha256']==preserved['data_sha256']:
                expected=preserved['result']['result']
                assert r['result']==expected,'Transfer source no longer reproduces the preserved round-1 result'
            write_json(report_path,report)
            print(dataset,name,'NET',r['result']['pnl'],'fee',r['result']['breach_penalty'],flush=True)
    report['completed']=True;write_json(report_path,report)
    compact={'native':protocol,'registry_sha256':digest(REGISTRY),'datasets':fingerprints,
        'limitation':report['limitation'],'completed':True,'results':{}}
    for dataset,models in report['results'].items():
        compact['results'][dataset]={name:{'result':r['result'],'source_sha256':r['source_sha256'],
            'max_abs_inventory':r['max_abs_inventory'],'max_potential_inventory_at_submission':r['max_potential_inventory_at_submission'],
            'strategy_state':r['strategy_state']} for name,r in models.items()}
    (REPO/'results/round2_historical_characterization.json').write_text(json.dumps(compact,indent=2)+'\n')
    print('Historical characterization complete. No round-2 candidate selected.',flush=True)


if __name__=='__main__':main()
