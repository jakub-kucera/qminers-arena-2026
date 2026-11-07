"""Causal rolling gradient-boosted trees; only matured observations enter fits."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT = Path('logs/round1/online_trees')


def source_for(iterations, leaves, window, gain=1.0):
    base = Path('strategies/round1_private_554347.py').read_text()
    base = base.replace('isfinite\n', 'isfinite, log\n')
    base = base.replace('from simulator.models import', '''import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.utils.parallel import _get_threadpool_controller

from simulator.models import''')
    base = base.replace('FEATURE_COUNT = 15', 'FEATURE_COUNT = 20')
    base = base.replace('        self._orders = {}', f'''        self._orders = {{}}
        self._tree_rows = deque(maxlen={window})
        self._tree_last_fit = None
        self._trees = []
        self._tree_intercept = 0.0''', 1)
    base = base.replace('            self._labels += 1', '''            self._labels += 1
            self._tree_rows.append(features+(response,))''')
    helper = f'''    def _fit_trees(self, now):
        if len(self._tree_rows) < 1000:
            return
        if self._tree_last_fit is not None and now-self._tree_last_fit < 60000000:
            return
        data = np.asarray(self._tree_rows,dtype=float)
        model = HistGradientBoostingRegressor(max_iter={iterations},max_leaf_nodes={leaves},
            max_bins=32,min_samples_leaf=100,l2_regularization=10.0,learning_rate=0.1,
            early_stopping=False,random_state=1729)
        with _get_threadpool_controller().limit(limits=1):
            model.fit(data[:,:-1],data[:,-1])
        trees = []
        for stage in model._predictors:
            nodes = stage[0].nodes
            trees.append(tuple((int(n['feature_idx']),float(n['num_threshold']),
                int(n['left']),int(n['right']),float(n['value']),bool(n['is_leaf'])) for n in nodes))
        self._trees = trees
        self._tree_intercept = float(model._baseline_prediction[0,0])
        self._tree_last_fit = now

    def _predict_trees(self, features):
        prediction = self._tree_intercept
        for tree in self._trees:
            node = 0
            while not tree[node][5]:
                item = tree[node]
                node = item[2] if features[item[0]] <= item[1] else item[3]
            prediction += tree[node][4]
        return prediction

'''
    base = base.replace('    def _cancel(self, order_id):', helper+'    def _cancel(self, order_id):')
    base = base.replace('robust_imbalance*abs(robust_imbalance))', '''robust_imbalance*abs(robust_imbalance),
                  spread,(bn+an)/20,(bd_n+ad_n)/40,log(1+bq+aq)/10,
                  (bq/max(1,bn)-aq/max(1,an))/max(1,bq/max(1,bn)+aq/max(1,an)))''')
    base = base.replace('        self._learn(now,mid)', '''        self._learn(now,mid)
        self._fit_trees(now)''')
    base = base.replace('        fair = mid + ', f'''        if self._trees:
            prediction = max(-2.0,min(2.0,{gain}*self._predict_trees(features)))
        fair = mid + ''')
    return base


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():
        raise SystemExit('Results already exist')
    search_queue.ROOT = ROOT
    specs = {}
    for iterations, leaves in ((40,7),(40,15),(80,15),(80,31)):
        for window in (6000,15000):
            name = f'trees_{iterations}_{leaves}_{window}'
            path = ROOT/'sources'/(name+'.py')
            path.write_text(source_for(iterations,leaves,window))
            assert not check(path),check(path)
            specs[name] = dict(iterations=iterations,leaves=leaves,window=window,source_sha256=digest(path))
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screened = search_queue.batch(specs,'logs/round1/screening.csv','screening',workers=4)
    finalists = sorted(screened,key=lambda n:screened[n]['result']['pnl'],reverse=True)[:3]
    full = search_queue.batch(finalists,'data/round1.csv','full',workers=3)
    winner = max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],parameters=specs[winner],
        limitation='Repeated sample tuning, but every tree fit uses only labels matured by simulation time.'),indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':
    main()
