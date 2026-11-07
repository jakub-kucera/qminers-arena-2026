"""Small frozen boosting study; fit first 30m, assess subsequent development only."""
from pathlib import Path
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from scripts.benchmark import digest
from scripts.check_submission import check
from scripts.round2_workbench import load_manifest, run_candidate, write_json
from simulator.main import load_strategy_from_file

ROOT=Path('logs/round2_nonlinear')


def predict(trees, intercept, features):
    value=intercept
    for tree in trees:
        i=0
        while not tree[i][5]:
            node=tree[i];i=node[2] if features[node[0]]<=node[1] else node[3]
        value+=tree[i][4]
    return value


def main():
    intake=load_manifest(Path('logs/round2_local_intake'))
    ROOT.mkdir(exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    train_end=intake['first_us']+1800_000_000
    protocol=dict(data_sha256=intake['development_sha256'],train_end_us=train_end,
        training_purge_us=10_000_000,evaluation='Only PnL increment after train_end counts as out-of-time.',
        parameters=dict(max_iter=100,max_leaf_nodes=15,max_depth=4,min_samples_leaf=200,
                        l2_regularization=30,learning_rate=.05,early_stopping=False,random_state=19),
        models=[dict(horizon_us=100000,clip=1),dict(horizon_us=400000,clip=3)],
        online_blend_weights=[0.0,0.5],mirror_augmentation=True,
        excluded_features=[23,27],native=intake['native'])
    frozen=ROOT/'protocol.json'
    if frozen.exists():assert json.loads(frozen.read_text())==protocol
    else:write_json(frozen,protocol)
    z=np.load(ROOT/'public_features.npz');obs=z['observations'];market=z['market']
    selected=[i for i in range(29) if i not in (23,27)]
    x=obs[:,2:][:,selected];mirror=np.full(len(selected),-1.0);mirror[selected.index(24)]=1
    original=Path('logs/round2_structural_batch/sources/robust_labels_3.py').read_text()
    reports={};candidates=[]
    for spec in protocol['models']:
        h,clip=spec['horizon_us'],spec['clip']
        idx=np.searchsorted(market[:,0],obs[:,0]+h)
        valid=idx<len(market);idx=np.minimum(idx,len(market)-1)
        valid &= market[idx,0]-(obs[:,0]+h)<=20000
        y=np.clip(market[idx,1]-obs[:,1],-clip,clip)
        train=valid & (obs[:,0]+h<train_end-10_000_000)
        test=valid & (obs[:,0]>=train_end)
        model=HistGradientBoostingRegressor(**protocol['parameters'])
        model.fit(np.concatenate([x[train],x[train]*mirror]),np.concatenate([y[train],-y[train]]))
        trees=[]
        for stage in model._predictors:
            tree=[]
            for n in stage[0].nodes:
                assert not n['is_categorical']
                tree.append((selected[int(n['feature_idx'])],float(n['num_threshold']),
                             int(n['left']),int(n['right']),float(n['value']),bool(n['is_leaf'])))
            trees.append(tree)
        intercept=float(model._baseline_prediction[0,0])
        # Export parity on unseen observations and reflected feature vectors.
        subset=np.flatnonzero(test)[::max(1,int(test.sum()/128))]
        native=model.predict(x[subset])
        exported=np.array([predict(trees,intercept,obs[i,2:]) for i in subset])
        np.testing.assert_allclose(exported,native,rtol=0,atol=1e-12)
        forecast=(model.predict(x[test])-model.predict(x[test]*mirror))/2
        label=y[test]
        reports[str(h)]={'train_samples':int(train.sum()),'test_samples':int(test.sum()),
                        'future_return_correlation':float(np.corrcoef(forecast,label)[0,1]),
                        'mae':float(np.mean(abs(forecast-label))),
                        'zero_mae':float(np.mean(abs(label))),'export_max_error':float(abs(exported-native).max())}
        for blend in protocol['online_blend_weights']:
            name=f'hgb_{h//1000}ms_blend{int(blend*100)}'
            text=original.replace('    FEATURE_COUNT = 29','    TREES = '+repr(trees)+'\n    FEATURE_COUNT = 29',1)
            text=text.replace('        self.inventory = 0','''        self.inventory = 0
        self._tree_us = None
        self._tree_forecast = 0.0''',1)
            method='''    def _tree_predict(self, features):
        value = 0.0
        for direction in (1,-1):
            prediction = 0.0
            for tree in self.TREES:
                i=0
                while not tree[i][5]:
                    node=tree[i]
                    feature=features[node[0]]*(1 if node[0]==24 else direction)
                    i=node[2] if feature<=node[1] else node[3]
                prediction+=tree[i][4]
            value+=direction*prediction*.5
        return value

'''
            text=text.replace('    def _learn(self, now, mid):',method+'    def _learn(self, now, mid):',1)
            block=f'''        if self._tree_us is None or now-self._tree_us >= 20000:
            self._tree_forecast=self._tree_predict(features)
            self._tree_us=now
        prediction={blend}*prediction+{1-blend}*self._tree_forecast
'''
            text=text.replace('        fair = mid +',block+'        fair = mid +',1)
            path=ROOT/'sources'/(name+'.py')
            if path.exists():assert path.read_text()==text
            else:path.write_text(text)
            assert path.stat().st_size<1048576
            assert not check(path),check(path)
            exported_strategy=load_strategy_from_file(path)
            expected=(model.predict(x[subset])-model.predict(x[subset]*mirror))/2
            actual=np.array([exported_strategy._tree_predict(obs[i,2:]) for i in subset])
            np.testing.assert_allclose(actual,expected,rtol=0,atol=1e-12)
            candidates.append(dict(name=name,file=str(path),source_sha256=digest(path),risk='strict100'))
    write_json(ROOT/'forecast_metrics.json',reports)
    write_json(ROOT/'source_manifest.json',candidates)
    result_path=ROOT/'development_results.json'
    results=json.loads(result_path.read_text()) if result_path.exists() else {}
    for c in candidates:
        if c['name'] in results:
            assert results[c['name']]['source_sha256']==c['source_sha256']
            assert results[c['name']]['data_sha256']==intake['development_sha256']
    with ProcessPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(run_candidate,c,intake['development'],ROOT/c['name'],
                         (train_end,intake['development_cutoff_us'])):c['name']
              for c in candidates if c['name'] not in results}
        for job in as_completed(jobs):
            name=jobs[job];r=job.result()
            r['out_of_time_net']=r['boundary_pnl'][str(intake['development_cutoff_us'])]-r['boundary_pnl'][str(train_end)]
            r['training_period_not_valid_evaluation']=True
            results[name]=r;write_json(result_path,results)
            print(name,'out-of-time',r['out_of_time_net'],'total TRAINING INCLUDED',r['result']['pnl'],flush=True)


if __name__=='__main__':main()
