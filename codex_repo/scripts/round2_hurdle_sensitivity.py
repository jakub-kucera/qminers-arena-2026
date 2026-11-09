"""Diagnostics around a frozen winner; never select a replacement from this run."""
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
import json
from scripts.benchmark import digest
from scripts.check_submission import check
from scripts.round2_workbench import load_manifest, run_candidate, write_json

ROOT=Path('logs/round2_hurdle_sensitivity')


def main():
    selected=json.loads(Path('logs/round2_regime_hurdles/full_selection.json').read_text())['candidate']
    source=Path(selected['file'])
    assert digest(source)==selected['source_sha256']
    base=source.read_text()
    candidates=[]
    ROOT.mkdir(exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    for seconds,gate in ((60,15),(60,25),(45,20),(90,20)):
        text=base.replace('score-self._m2_history[0][1]>20:',f'score-self._m2_history[0][1]>{gate}:')
        text=text.replace('boundary=now-60000000',f'boundary=now-{seconds*1000000}')
        text=text.replace('now-self._m2_start>=60000000',f'now-self._m2_start>={seconds*1000000}')
        name=f'window{seconds}_gate{gate}';p=ROOT/'sources'/(name+'.py')
        if p.exists():assert p.read_text()==text
        else:p.write_text(text)
        assert not check(p)
        candidates.append(dict(name=name,file=str(p),source_sha256=digest(p),risk='strict100'))
    protocol=dict(frozen_reference=selected,candidates=candidates,
        purpose='Sensitivity only; do not replace frozen winner or infer fresh validation.',
        scope='Previously consumed first80% public prefix.')
    p=ROOT/'protocol.json'
    if p.exists():assert json.loads(p.read_text())==protocol
    else:write_json(p,protocol)
    m=load_manifest(Path('logs/round2_local_intake'))
    p=ROOT/'results.json';results=json.loads(p.read_text()) if p.exists() else {}
    with ProcessPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(run_candidate,c,m['validation_prefix'],ROOT/c['name'],
            (m['first_us']+1800000000,m['development_cutoff_us'],m['validation_cutoff_us'])):c['name']
            for c in candidates if c['name'] not in results}
        for job in as_completed(jobs):
            name=jobs[job];r=job.result();b=r['boundary_pnl']
            r['later30']=b[str(m['development_cutoff_us'])]-b[str(m['first_us']+1800000000)]
            r['last20']=b[str(m['validation_cutoff_us'])]-b[str(m['development_cutoff_us'])]
            results[name]=r;write_json(p,results)
            print(name,r['result']['pnl'],r['later30'],r['last20'],flush=True)


if __name__=='__main__':main()
