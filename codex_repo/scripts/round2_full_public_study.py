"""Audited full-public comparisons after the initial public holdout was consumed."""
import json
from concurrent.futures import ProcessPoolExecutor,as_completed
from pathlib import Path

from scripts.benchmark import digest
from scripts.check_submission import check
from scripts.round2_workbench import load_manifest,native_stamp,run_candidate,write_json


def run_public_study(cases,output,workers=2):
    m=load_manifest(Path('logs/round2'));output=Path(output)
    (output/'sources').mkdir(parents=True,exist_ok=True)
    candidates=[]
    for name,text in cases.items():
        p=output/'sources'/(name+'.py')
        if p.exists():assert p.read_text()==text
        else:p.write_text(text)
        assert not check(p),check(p)
        candidates.append(dict(name=name,file=str(p),source_sha256=digest(p),risk='native'))
    scope='Reused FULL PUBLIC sample tuning after the first frozen public check. Not fresh validation or private scoring. Native matching/fees unchanged.'
    path=output/'results.json'
    report=json.loads(path.read_text()) if path.exists() else dict(scope=scope,results={},
        native=native_stamp(),data_sha256=m['data_sha256'])
    assert report['native']==native_stamp() and report['data_sha256']==m['data_sha256']
    for c in candidates:
        if c['name'] in report['results']:assert report['results'][c['name']]['source_sha256']==c['source_sha256']
    write_json(output/'specs.json',dict(candidates=candidates,native=native_stamp(),
        data_sha256=m['data_sha256'],scope=scope))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        jobs={pool.submit(run_candidate,c,m['data'],output/'full'/c['name'],
            (m['development_cutoff_us'],m['validation_cutoff_us'])):c['name']
            for c in candidates if c['name'] not in report['results']}
        for job in as_completed(jobs):
            name=jobs[job];r=job.result()
            r['first60_pnl']=r['boundary_pnl'][str(m['development_cutoff_us'])]
            r['later40_pnl']=r['result']['pnl']-r['first60_pnl']
            r['last20_pnl']=r['result']['pnl']-r['boundary_pnl'][str(m['validation_cutoff_us'])]
            report['results'][name]=r;write_json(path,report)
            print(name,'PUBLIC NET',r['result']['pnl'],'FIRST60',r['first60_pnl'],
                  'LATER40',r['later40_pnl'],flush=True)
    return report
