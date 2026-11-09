"""Fill-conditioned value model; training uses only the first development half."""
from pathlib import Path
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from scripts.benchmark import digest
from scripts.check_submission import check
from scripts.round2_workbench import load_manifest,run_candidate,write_json
from simulator.main import load_strategy_from_file

ROOT=Path('logs/round2_conditional_fill')


def main():
    intake=load_manifest(Path('logs/round2_local_intake'))
    ROOT.mkdir(exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    train_end=intake['first_us']+1800_000_000
    protocol=dict(data_sha256=intake['development_sha256'],train_end_us=train_end,
        horizon_us=400000,clip=3,thresholds=[-.1,0,.1],
        parameters=dict(max_iter=100,max_leaf_nodes=7,max_depth=3,min_samples_leaf=100,
                        l2_regularization=30,learning_rate=.05,early_stopping=False,random_state=23),
        scope='Development only. Fit first 30m, score incremental next 30m. No fresh holdout claim.',
        limitation='Observed fills from robust maker create policy-dependent samples. No counterfactual fill guarantee.',
        native=intake['native'])
    p=ROOT/'protocol.json'
    if p.exists():assert json.loads(p.read_text())==protocol
    else:write_json(p,protocol)
    raw=np.load('logs/round2_nonlinear/public_features.npz');obs=raw['observations']
    raw=np.load('logs/round2_fill_diagnostics/observations.npz');f=raw['fills'];q=raw['quotes']
    selected=[i for i in range(29) if i not in (23,27)]
    before=np.searchsorted(obs[:,0],f[:,4],side='right')-1
    after=np.searchsorted(q[:,0],f[:,0]+400000)
    valid=(before>=0)&(after<len(q))
    before=np.maximum(before,0);after=np.minimum(after,len(q)-1)
    valid&=(q[after,0]-(f[:,0]+400000)<=20000)&(f[:,0]-obs[before,0]<=100000)
    x=obs[before,2:][:,selected].copy()
    signs=f[:,1]
    for j,i in enumerate(selected):
        if i!=24:x[:,j]*=signs
    y=np.clip(signs*(q[after,1]-f[:,3]),-3,3)
    train=valid&(f[:,0]+400000<train_end-10000000)
    test=valid&(f[:,0]>=train_end)
    model=HistGradientBoostingRegressor(**protocol['parameters'])
    model.fit(x[train],y[train],sample_weight=np.sqrt(f[train,2]))
    predicted=model.predict(x[test]);target=y[test]
    metrics=dict(train_events=int(train.sum()),test_events=int(test.sum()),
        correlation=float(np.corrcoef(predicted,target)[0,1]),
        label='Clipped 400ms midpoint markout, not realized round-trip PnL.',
        buckets={str(c):dict(events=int((predicted>=c).sum()),
                  mean_markout=float(target[predicted>=c].mean()) if (predicted>=c).any() else None)
                 for c in protocol['thresholds']})
    write_json(ROOT/'forecast_metrics.json',metrics)
    trees=[]
    for stage in model._predictors:
        tree=[]
        for n in stage[0].nodes:
            assert not n['is_categorical']
            tree.append((selected[int(n['feature_idx'])],float(n['num_threshold']),
                         int(n['left']),int(n['right']),float(n['value']),bool(n['is_leaf'])))
        trees.append(tree)
    intercept=float(model._baseline_prediction[0,0])
    base=Path('logs/round2_structural_batch/sources/robust_labels_3.py').read_text()
    base=base.replace('    FEATURE_COUNT = 29','    TREES = '+repr(trees)+'\n    FEATURE_COUNT = 29',1)
    method=f'''    def _fill_value(self, features, direction):
        value={intercept}
        for tree in self.TREES:
            i=0
            while not tree[i][5]:
                node=tree[i]
                feature=features[node[0]]*(1 if node[0]==24 else direction)
                i=node[2] if feature<=node[1] else node[3]
            value+=tree[i][4]
        return value

'''
    base=base.replace('    def _learn(self, now, mid):',method+'    def _learn(self, now, mid):',1)
    base=base.replace('        self.inventory = 0','''        self.inventory = 0
        self._value_us = None
        self._bid_value = self._ask_value = 0.0''',1)
    candidates=[]
    for threshold in protocol['thresholds']:
        block=f'''        if self._value_us is None or now-self._value_us >= 20000:
            self._bid_value=self._fill_value(features,1)
            self._ask_value=self._fill_value(features,-1)
            self._value_us=now
        if self._bid_value < {threshold}:
            buy=None
        if self._ask_value < {threshold}:
            sell=None
'''
        text=base.replace('        # Withdraw the side vulnerable',block+'        # Withdraw the side vulnerable',1)
        name='fill_value_'+str(threshold).replace('-','minus').replace('.','p')
        path=ROOT/'sources'/(name+'.py')
        if path.exists():assert path.read_text()==text
        else:path.write_text(text)
        assert not check(path),check(path)
        strategy=load_strategy_from_file(path)
        subset=np.flatnonzero(test)[::max(1,int(test.sum()/128))]
        actual=[strategy._fill_value(obs[before[i],2:],int(signs[i])) for i in subset]
        np.testing.assert_allclose(actual,model.predict(x[subset]),rtol=0,atol=1e-12)
        candidates.append(dict(name=name,file=str(path),source_sha256=digest(path),risk='strict100'))
    write_json(ROOT/'source_manifest.json',candidates)
    p=ROOT/'development_results.json';results=json.loads(p.read_text()) if p.exists() else {}
    for c in candidates:
        if c['name'] in results:
            assert results[c['name']]['source_sha256']==c['source_sha256']
            assert results[c['name']]['data_sha256']==intake['development_sha256']
    with ProcessPoolExecutor(max_workers=3) as pool:
        jobs={pool.submit(run_candidate,c,intake['development'],ROOT/c['name'],
                         (train_end,intake['development_cutoff_us'])):c['name']
              for c in candidates if c['name'] not in results}
        for job in as_completed(jobs):
            name=jobs[job];r=job.result()
            r['out_of_time_net']=r['boundary_pnl'][str(intake['development_cutoff_us'])]-r['boundary_pnl'][str(train_end)]
            r['training_period_not_valid_evaluation']=True
            results[name]=r;write_json(p,results)
            print(name,'out-of-time',r['out_of_time_net'],'total TRAINING INCLUDED',r['result']['pnl'],flush=True)


if __name__=='__main__':main()
