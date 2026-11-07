"""Direct native-PnL search over residual signals on top of the online learner."""
import json
from pathlib import Path
import numpy as np
from scripts.round1_fixed_trees import collect
from scripts import search_queue
from scripts.check_submission import check
from scripts.benchmark import digest

ROOT=Path('logs/round1/pnl_residual')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'full.json').exists():raise SystemExit('Results already exist')
    data=collect();x=data['x'][data['t']<3600000000,:15]
    gram=x.T@x/len(x)
    values,vectors=np.linalg.eigh(gram)
    whitening=vectors@np.diag(1/np.sqrt(np.maximum(values,0.02)))@vectors.T
    rng=np.random.default_rng(650001);mean=np.zeros(15)
    base=Path('strategies/round1_private_554347.py').read_text();specs={};all_results={};search_queue.ROOT=ROOT
    for generation,scale in enumerate((0.02,0.01)):
        names=[]
        proposals=[np.zeros(15)] if generation==0 else [mean]
        proposals += [mean+whitening@rng.normal(0,scale,15) for _ in range(23)]
        for i,delta in enumerate(proposals):
            name=f'g{generation}_{i:02d}';names.append(name)
            coefficients=tuple(float(v) for v in delta)
            text=base.replace('        fair = mid + ',f'''        prediction = max(-2.0,min(2.0,prediction+sum(w*x for w,x in zip({coefficients!r},features))))
        fair = mid + ''')
            path=ROOT/'sources'/(name+'.py');path.write_text(text)
            assert not check(path),check(path)
            specs[name]=dict(delta=coefficients,generation=generation,source_sha256=digest(path))
        (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
        results=search_queue.batch(names,'logs/round1/screening.csv',f'generation_{generation}',workers=4)
        all_results.update(results)
        best=max(all_results,key=lambda n:all_results[n]['result']['pnl'])
        mean=np.array(specs[best]['delta'])
        print('GENERATION BEST',generation,best,all_results[best]['result']['pnl'],flush=True)
    finalists=sorted(all_results,key=lambda n:all_results[n]['result']['pnl'],reverse=True)[:4]
    full=search_queue.batch(finalists,'data/round1.csv','full',workers=4)
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],parameters=specs[winner],
        limitation='Residual coefficients optimized directly on native first-hour PnL; full file was already consumed in previous research.'),indent=2)+'\n')
    print('WINNER PNL SEARCH',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
