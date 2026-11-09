"""Fixed models of direction conditional on a nonzero future move.

This deliberately changes the learning target: movement direction, rather
than the unconditional return diluted by unchanged midpoints. Full-file
training overlap is explicit, and runtime inputs contain no time or IDs.
"""
import json
from pathlib import Path
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.utils.parallel import _get_threadpool_controller
from simulator.main import load_strategy_from_file
from scripts.round1_fixed_trees import collect,export_inline
from scripts import search_queue
from scripts.check_submission import check
from scripts.benchmark import digest

ROOT=Path('logs/round1/move_conditioned')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'full.json').exists():raise SystemExit('Results already exist')
    data=collect();mask=data['y']!=0;x=data['x'][mask];y=np.sign(data['y'][mask])
    reflected=x.copy();reflected[:,list(range(15))+[19]]*=-1
    xx=np.concatenate((x,reflected));yy=np.concatenate((y,-y))
    print('NONZERO TRAINING ROWS',len(x),'of',len(mask),flush=True)
    specs={};search_queue.ROOT=ROOT
    for iterations,leaves in ((64,15),(128,31)):
        model=HistGradientBoostingRegressor(max_iter=iterations,max_leaf_nodes=leaves,min_samples_leaf=200,
            l2_regularization=10,learning_rate=0.08,max_bins=64,early_stopping=False,random_state=1729)
        with _get_threadpool_controller().limit(limits=1):model.fit(xx,yy)
        for gain in (0.25,0.5,1.0):
            name=f'direction_{iterations}_{leaves}_gain_{gain}'
            path=ROOT/'sources'/(name+'.py');path.write_text(export_inline(model,gain))
            assert not check(path),check(path)
            s=load_strategy_from_file(path);test=x[::5000]
            assert np.max(np.abs(np.array([s._predict_trees(tuple(row)) for row in test])-model.predict(test)))<1e-10
            specs[name]=dict(iterations=iterations,leaves=leaves,gain=gain,training_fraction=1.0,
                in_sample=True,nonzero_training_rows=len(x),source_sha256=digest(path))
        print('FIT CONDITIONAL DIRECTION',iterations,leaves,flush=True)
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/round1/screening.csv','screening',workers=3)
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:2]
    full=search_queue.batch(finalists,'data/round1.csv','full',workers=2)
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],parameters=specs[winner],
        limitation='IN-SAMPLE: trained on all supplied nonzero future-move labels. Runtime uses only current public features.'),indent=2)+'\n')
    print('WINNER CONDITIONAL DIRECTION',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
