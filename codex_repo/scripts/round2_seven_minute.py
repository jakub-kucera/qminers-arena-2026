"""Three frozen full-tape comparisons within a user-imposed seven-minute budget."""
import csv
import json
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor,as_completed
from pathlib import Path
from scripts.benchmark import digest
from scripts.check_submission import check
from scripts.round2_workbench import load_manifest,run_candidate,write_json

ROOT=Path('logs/round2_seven_minute_20261108')


def build():
    p=Path('strategies/round2/round2_local_316031.py')
    assert digest(p)=='088c20f7cf726b9e1e5047e2adc8c305e5c2a9ed0f1064aced4b097042f608f6'
    base=p.read_text();anchor='        features+=self._impact_frame'
    assert base.count(anchor)==1
    depth='max(-3.0,min(3.0,self._impact_net[0]/(1+(aq if self._impact_net[0]>=0 else bq))))'
    return {name:base.replace('    FEATURE_COUNT = 35',f'    FEATURE_COUNT = {count}',1).replace(anchor,'        features+='+expression,1)
            for name,count,expression in (
                ('robust_depth',36,f'self._impact_frame+({depth},)'),
                ('robust_sqrt',34,'(self._impact_frame[1],)'),
                ('robust_sqrt_depth',35,f'(self._impact_frame[1],{depth})'))}


def native(candidate,data):
    folder=ROOT/candidate['name']/'official_cli'
    subprocess.run([sys.executable,'-m','simulator.main','--backtest',str(data),'--strategy',candidate['file'],
                    '--log-dir',str(folder),'--no-logs'],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    return json.loads((folder/'result.json').read_text())


def main():
    m=load_manifest(Path('logs/round2_local_intake'))
    ROOT.mkdir(exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    candidates=[]
    for name,text in build().items():
        p=ROOT/'sources'/(name+'.py')
        if p.exists():assert p.read_text()==text
        else:p.write_text(text)
        assert not check(p),check(p)
        candidates.append(dict(name=name,file=str(p),source_sha256=digest(p),risk='strict100'))
    protocol=dict(candidates=candidates,goal=326031,reference=316031,
        main_commit=subprocess.check_output(['git','rev-parse','origin/main'],text=True).strip(),
        data_sha256=m['data_sha256'],native=m['native'],
        selection='Positive30-60 and60-80; maximize combined30-80 gain. Rank before inspecting final20.',
        scope='Consumed public full tape. Parallel audit/native checks for three frozen cases under seven-minute limit; no untouched holdout.',
        crash='Inspect1s-derived largest100s decline3936-4036 and rebound5398-5400; never used in trading rules.')
    write_json(ROOT/'protocol.json',protocol)
    boundaries=(m['first_us']+1800000000,m['development_cutoff_us'],m['validation_cutoff_us'],
                m['first_us']+3936000000,m['first_us']+4036000000,m['first_us']+5398000000,m['first_us']+5400000000)
    results={};native_results={}
    with ProcessPoolExecutor(max_workers=6) as pool:
        jobs={}
        for c in candidates:
            jobs[pool.submit(run_candidate,c,m['data'],ROOT/c['name']/'audit',boundaries)]=(c['name'],'audit')
            jobs[pool.submit(native,c,m['data'])]=(c['name'],'native')
        for future in as_completed(jobs):
            name,kind=jobs[future];r=future.result()
            if kind=='audit':
                b=r['boundary_pnl'];r['later30']=b[str(m['development_cutoff_us'])]-b[str(m['first_us']+1800000000)]
                r['later20']=b[str(m['validation_cutoff_us'])]-b[str(m['development_cutoff_us'])]
                results[name]=r;write_json(ROOT/'results.json',results)
            else:native_results[name]=r;write_json(ROOT/'native_results.json',native_results)
            print(name,kind,'finished',flush=True)
    for name,r in results.items():assert r['result']==native_results[name]
    eligible=[c for c in candidates if results[c['name']]['later30']>0 and results[c['name']]['later20']>0]
    winner=max(eligible,key=lambda c:results[c['name']]['later30']+results[c['name']]['later20'])
    write_json(ROOT/'selection.json',dict(candidate=winner,criterion=protocol['selection'],goal=326031))
    print('Selected',winner['name'],results[winner['name']]['result'],flush=True)


if __name__=='__main__':main()
