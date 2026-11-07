"""Full-round tuning of additional promising variants; no fresh validation claim."""
import ast
import json
from concurrent.futures import ProcessPoolExecutor,as_completed
from pathlib import Path
from scripts.search_passive import run

ROOT=Path('logs/round1/expanded_full')


def fingerprint(path):
    tree=ast.parse(Path(path).read_text())
    if tree.body and isinstance(tree.body[0],ast.Expr) and isinstance(tree.body[0].value,ast.Constant) and isinstance(tree.body[0].value.value,str):tree.body=tree.body[1:]
    return ast.dump(tree,include_attributes=False)


def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    if (ROOT/'results.json').exists():raise SystemExit('Results already exist')
    completed=set()
    for path in Path('logs/round1').glob('*/full.json'):
        try:
            for r in json.loads(path.read_text()).values():completed.add(fingerprint(r['source']))
        except (KeyError,FileNotFoundError):pass
    completed.add(fingerprint('strategies/round1_best.py'))
    candidates=[];seen=set(completed)
    for folder in ('search','calibration','nonlinear','target550','joint_policy'):
        path=Path('logs/round1')/folder/'screening.json'
        for name,r in json.loads(path.read_text()).items():
            source=Path('logs/round1')/folder/'sources'/(name+'.py')
            if r['result']['pnl']<135000:continue
            key=fingerprint(source)
            if key in seen:continue
            seen.add(key);candidates.append((folder+'__'+name,source,r['result']['pnl']))
    # Every eligible base-model horizon is retained; other variants are ranked by screening.
    candidates.sort(key=lambda v:(not v[0].startswith('search__'),-v[2]))
    (ROOT/'plan.json').write_text(json.dumps([{'name':n,'source':str(s),'screening_pnl':p} for n,s,p in candidates],indent=2)+'\n')
    print('FULL CANDIDATES',len(candidates),flush=True)
    results={}
    with ProcessPoolExecutor(max_workers=3) as pool:
        jobs={pool.submit(run,s,'data/round1.csv',ROOT/n):n for n,s,p in candidates}
        for job in as_completed(jobs):
            n=jobs[job];r=job.result();results[n]=r
            (ROOT/'progress.json').write_text(json.dumps(results,indent=2)+'\n')
            print(n,'pnl',r['result']['pnl'],'dd',r['max_drawdown_1s'],flush=True)
    (ROOT/'results.json').write_text(json.dumps(results,indent=2)+'\n')
    if results:
        winner=max(results,key=lambda n:results[n]['result']['pnl'])
        (ROOT/'winner.json').write_text(json.dumps({'name':winner,'result':results[winner],
            'limitation':'Full-round sample tuning; no independent holdout remains.'},indent=2)+'\n')
        print('WINNER',winner,results[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
