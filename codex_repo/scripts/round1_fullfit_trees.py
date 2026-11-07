"""Explicit IN-SAMPLE model benchmark: all supplied round-1 labels used in fitting.

No time/IDs/trade sequence are inputs. Full replay is training-overlap evidence,
not validation. Exports only numerical tree parameters with observable inputs.
"""
import json
from pathlib import Path
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.utils.parallel import _get_threadpool_controller
from simulator.main import load_strategy_from_file
from scripts.round1_fixed_trees import collect,export_inline,ROOT as DATA_ROOT
from scripts import search_queue
from scripts.check_submission import check
from scripts.benchmark import digest

ROOT=Path('logs/round1/fullfit_trees')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'full.json').exists():raise SystemExit('Results already exist')
    data=collect();x,y=data['x'],np.clip(data['y'],-5,5)
    reflected=x.copy();reflected[:,list(range(15))+[19]]*=-1
    xx=np.concatenate((x,reflected));yy=np.concatenate((y,-y))
    specs={};search_queue.ROOT=ROOT
    for iterations,leaves,minleaf in ((128,31,200),(256,31,200),(256,63,100),(384,63,100)):
        model=HistGradientBoostingRegressor(max_iter=iterations,max_leaf_nodes=leaves,
            min_samples_leaf=minleaf,l2_regularization=1,learning_rate=0.1,max_bins=128,
            early_stopping=False,random_state=1729)
        with _get_threadpool_controller().limit(limits=1):model.fit(xx,yy)
        for gain in (1.0,1.5):
            name=f'fullfit_{iterations}_{leaves}_{minleaf}_gain_{gain}'
            path=ROOT/'sources'/(name+'.py');path.write_text(export_inline(model,gain))
            assert not check(path),check(path)
            s=load_strategy_from_file(path);test=x[::10000]
            assert np.max(np.abs(np.array([s._predict_trees(tuple(row)) for row in test])-model.predict(test)))<1e-10
            specs[name]=dict(iterations=iterations,leaves=leaves,minleaf=minleaf,gain=gain,
                training_fraction=1.0,in_sample=True,training_rows=len(x),source_sha256=digest(path),bytes=path.stat().st_size)
        print('FIT IN-SAMPLE',iterations,leaves,minleaf,flush=True)
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/round1/screening.csv','screening',workers=4)
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    full=search_queue.batch(finalists,'data/round1.csv','full',workers=3)
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],parameters=specs[winner],
        limitation='IN-SAMPLE: trained on labels from the entire supplied file. Runtime uses current features only. No independent validation.'),indent=2)+'\n')
    print('WINNER IN-SAMPLE',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
