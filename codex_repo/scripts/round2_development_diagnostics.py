"""Small causal ablations on development data only; no round-2 selection."""
import json
from concurrent.futures import ProcessPoolExecutor,as_completed
from pathlib import Path

from scripts.benchmark import digest
from scripts.check_submission import check
from scripts.round2_workbench import load_manifest,run_candidate,write_json

ROOT=Path('logs/round2/development_diagnostics')


def main():
    m=load_manifest(Path('logs/round2'))
    source=next(c for c in m['candidates'] if c['name']=='round2_transfer')
    base=Path(source['file']).read_text()
    no_alpha=base.replace('        self._learn(now,mid)\n','').replace(
        '        fair = mid + ','        prediction = 0.0\n        fair = mid + ',1)
    cases={'symmetric_touch':no_alpha,
        'inverted_forecast':base.replace('        fair = mid + ','        prediction = -prediction\n        fair = mid + ',1)}
    for label,text in (('wide_symmetric',no_alpha),('wide_forecast',base)):
        cases[label]=text.replace('floor(fair-0.45)','floor(fair-1.0)').replace('ceil(fair+0.45)','ceil(fair+1.0)').replace(
            'prediction-skew > 0.3','prediction-skew > 2.1').replace('prediction-skew < -0.3','prediction-skew < -2.1')
    (ROOT/'sources').mkdir(parents=True,exist_ok=True)
    candidates=[]
    for name,text in cases.items():
        path=ROOT/'sources'/(name+'.py')
        if path.exists():assert path.read_text()==text
        else:path.write_text(text)
        assert not check(path),check(path)
        candidates.append({'name':name,'file':str(path),'source_sha256':digest(path),'risk':'native'})
    path=ROOT/'results.json'
    results=json.loads(path.read_text())['results'] if path.exists() else {}
    with ProcessPoolExecutor(max_workers=3) as pool:
        jobs={pool.submit(run_candidate,c,m['development'],ROOT/c['name'],(m['development_cutoff_us'],)):c['name']
              for c in candidates if c['name'] not in results}
        for job in as_completed(jobs):
            name=jobs[job];r=job.result();results[name]=r
            write_json(path,{'scope':'Public development only; diagnostics, not frozen selection.',
                'data_sha256':m['development_sha256'],'results':results})
            print(name,'NET',r['result']['pnl'],'fee',r['result']['breach_penalty'],flush=True)


if __name__=='__main__':main()
