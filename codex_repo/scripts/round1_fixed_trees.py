"""Train fixed microstructure models on first 60%; report later periods separately.

Full-file PnL includes the training period and is an in-sample benchmark there.
Only current observable features enter the exported predictor, never time or IDs.
"""
from array import array
from collections import deque
import json
from pathlib import Path
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.utils.parallel import _get_threadpool_controller
from simulator.main import load_strategy_from_file
from simulator.simulator import ExchangeSimulator,SimulationConfig
from scripts import search_queue
from scripts.round1_online_trees import source_for
from scripts.check_submission import check
from scripts.benchmark import digest

ROOT=Path('logs/round1/fixed_trees')


def collect():
    path=ROOT/'features.npz'
    if path.exists():return np.load(path)
    source=ROOT/'collector_base.py';source.write_text(source_for(40,7,15000))
    parent=load_strategy_from_file(source).__class__
    class Collector(parent):
        def __init__(self):
            super().__init__();self.rows=array('d')
        def _quote(self,*args):pass
        def _fit_trees(self,*args):pass
        def _learn(self,now,mid):
            while self._observations and self._observations[0][0]+100000 <= now:
                stamp,origin,features=self._observations.popleft()
                if now-stamp <= 1100000:
                    self.rows.extend((stamp,mid-origin,*features))
    s=Collector()
    ExchangeSimulator(s,SimulationConfig(order_accept_delay_ms=5,public_depth=20,
        max_position=100,max_potential_position=1000,position_breach_penalty_per_second=10000)).run(Path('data/round1.csv'))
    data=np.asarray(s.rows).reshape(-1,22)
    np.savez(path,t=data[:,0],y=data[:,1],x=data[:,2:])
    print('COLLECTED',data.shape,flush=True)
    return np.load(path)


def export(model,gain):
    source=source_for(40,7,15000,gain)
    for line in ('import numpy as np\n','from sklearn.ensemble import HistGradientBoostingRegressor\n',
                 'from sklearn.utils.parallel import _get_threadpool_controller\n'):
        source=source.replace(line,'')
    start=source.index('    def _learn(');end=source.index('    def _predict_trees(',start)
    source=source[:start]+source[end:]
    for line in ('        self._learn(now,mid)\n','        self._fit_trees(now)\n',
                 '        self._tree_rows = deque(maxlen=15000)\n','        self._tree_last_fit = None\n'):
        source=source.replace(line,'')
    trees=[]
    for stage in model._predictors:
        trees.append(tuple((int(n['feature_idx']),float(n['num_threshold']),int(n['left']),
                            int(n['right']),float(n['value']),bool(n['is_leaf'])) for n in stage[0].nodes))
    source=source.replace('        self._trees = []',f'        self._trees = {trees!r}')
    source=source.replace('        self._tree_intercept = 0.0',f'        self._tree_intercept = {float(model._baseline_prediction[0,0])!r}')
    return source


def export_inline(model,gain):
    source=export(model,gain)
    start=source.index('        self._trees = ')
    end=source.index('\n',start)
    source=source[:start]+'        self._trees = True'+source[end:]
    lines=['    def _predict_trees(self, features):',
           '        '+','.join(f'f{i}' for i in range(20))+' = features',
           '        value = self._tree_intercept']
    def emit(nodes,index,indent):
        node=nodes[index];space=' '*indent
        if node['is_leaf']:
            lines.append(space+'value += '+repr(float(node['value'])))
        else:
            lines.append(space+f"if f{int(node['feature_idx'])} <= {float(node['num_threshold'])!r}:")
            emit(nodes,int(node['left']),indent+4)
            lines.append(space+'else:')
            emit(nodes,int(node['right']),indent+4)
    for stage in model._predictors:emit(stage[0].nodes,0,8)
    lines.extend(['        return value',''])
    start=source.index('    def _predict_trees(');end=source.index('    def _cancel(',start)
    return source[:start]+'\n'.join(lines)+'\n'+source[end:]


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'full.json').exists():raise SystemExit('Results already exist')
    data=collect();x,y,t=data['x'],data['y'],data['t']
    train=t<7200002879
    xx=x[train];yy=np.clip(y[train],-5,5)
    # Bid/ask reflection augmentation: even features are spread and total depths.
    reflected=xx.copy();odd=list(range(15))+[19];reflected[:,odd]*=-1
    xx=np.concatenate((xx,reflected));yy=np.concatenate((yy,-yy))
    specs={};search_queue.ROOT=ROOT
    for iterations,leaves in ((64,7),(64,15),(128,15),(128,31)):
        model=HistGradientBoostingRegressor(max_iter=iterations,max_leaf_nodes=leaves,
            min_samples_leaf=1000,l2_regularization=100,learning_rate=0.05,max_bins=64,
            early_stopping=False,random_state=1729)
        with _get_threadpool_controller().limit(limits=1):model.fit(xx,yy)
        prediction=model.predict(x[t>=7200002879])
        mse=float(np.mean((prediction-y[t>=7200002879])**2))
        for gain in (0.75,1.25):
            name=f'fixed_{iterations}_{leaves}_gain_{gain}'
            path=ROOT/'sources'/(name+'.py');path.write_text(export(model,gain))
            assert not check(path),check(path)
            s=load_strategy_from_file(path)
            test=x[::5000]
            actual=np.array([s._predict_trees(tuple(row)) for row in test])
            expected=model.predict(test)
            assert np.max(np.abs(actual-expected))<1e-10
            specs[name]=dict(iterations=iterations,leaves=leaves,gain=gain,
                training_end_us=7200002879,training_rows=int(train.sum()),later_mse=mse,
                source_sha256=digest(path))
        print('FIT',iterations,leaves,'later MSE',mse,flush=True)
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/round1/screening.csv','screening',workers=4)
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    full=search_queue.batch(finalists,'data/round1.csv','full',workers=3)
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],parameters=specs[winner],
        limitation='Pretrained on first 60%; full replay includes training-period PnL. Final 40% is later than training but has been used in prior strategy research.'),indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
