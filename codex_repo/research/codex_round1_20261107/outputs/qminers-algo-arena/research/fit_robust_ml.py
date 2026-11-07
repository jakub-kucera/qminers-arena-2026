"""Predeclared 250ms experiments; fitting never consumes the policy-validation tail."""
import json
import time
import warnings
from datetime import datetime, timezone

import numpy as np
from catboost import CatBoostRegressor
from scipy.optimize import minimize_scalar
from scipy.special import softmax
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.linear_model import ElasticNet, HuberRegressor, LogisticRegression, Ridge
from sklearn.metrics import log_loss
from threadpoolctl import threadpool_limits

from ml_round1_common import file_hash, future_change, load_features
from robust_ml_common import DEST, PREVIOUS, export, load_json
from run_study import dump, load_strategy_from_file


def stats(y, p):
    return dict(mse=float(np.mean((p-y)**2)), correlation=float(np.corrcoef(y, p)[0, 1])
        if np.std(p) > 1e-12 else None, mean=float(np.mean(p)), std=float(np.std(p)))


def linear_fit(model, x, y):
    mean, std = x.mean(axis=0), x.std(axis=0)
    std[std < 1e-12] = 1
    model.fit((x-mean)/std, y)
    coef = model.coef_ / std
    base = model.intercept_ - np.dot(mean, coef)
    return dict(kind='linear', coef=coef.tolist(), base=float(base)), model


def cat_fit(name, x, y, weight, seed):
    model = CatBoostRegressor(iterations=192, depth=4, learning_rate=.05, l2_leaf_reg=10,
        loss_function='RMSE', random_seed=seed, task_type='GPU', devices='0', thread_count=8,
        gpu_ram_part=.65, verbose=False, allow_writing_files=False)
    model.fit(x, y, sample_weight=weight)
    model.save_model(str(DEST / f'{name}.cbm'))
    path = DEST / f'{name}_catboost.json'
    model.save_model(str(path), format='json')
    raw = load_json(path)
    mapping = {v['feature_index']: v['flat_feature_index'] for v in raw['features_info']['float_features']}
    trees = [([(mapping[s['float_feature_index']], s['border']) for s in tree['splits'] or []],
              tree['leaf_values']) for tree in raw['oblivious_trees']]
    return dict(kind='cat', base=raw['scale_and_bias'][1][0], scale=raw['scale_and_bias'][0],
        trees=trees), model


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    assert not (DEST / 'fit_results.json').exists(), 'Do not overwrite a completed experiment.'
    plan = dict(created_utc=datetime.now(timezone.utc).isoformat(),
        horizon_seconds=.25, feature_count=24, training_end=6000,
        linear_cv='Expanding windows: 0-1500 -> 1500-3000; 0-3000 -> 3000-4500; 0-4500 -> 4500-6000. Targets crossing each boundary removed.',
        policy_validation=[6000, 9000], blocks=[6000,7000,8000,9000], delays_ms=[5,20],
        candidates=['ridge250','elastic250','huber250','forest250','window_ensemble',
                    'guarded_ensemble','diverse_composite','calibrated_logit'],
        ridge=dict(alpha=100), elastic=dict(alpha=[.0001,.001,.01],l1_ratio=.5),
        huber=dict(epsilon=1.35,alpha=.01),
        forest=dict(n_estimators=64,max_depth=4,min_samples_leaf=128,max_features=.75),
        ensemble='Equal weight: frozen prior full-window CatBoost; new 3000-6000 rolling-window CatBoost; new full-window CatBoost with exponential 1800s recency weights. New trees: 192, depth4, lr.05, l2=10.',
        guard='Shrink ensemble mean toward zero by one weighted standard deviation of model disagreement. This is not a calibrated confidence interval.',
        composite='Equal weight ElasticNet, ExtraTrees, and the three-window CatBoost mean.',
        logit='L2 multinomial logistic C=.1, fit 0-4800; temperature calibrated only on 4800-6000; signed classes and training class mean returns; no refit after calibration.',
        execution=dict(TARGET_ALPHA=40,EDGE_FLOOR=.15,CAP=100,SESSION_S=12000),
        selection='Require positive validation excess over F4 at both delays and improvement in at least 4 of 6 paired 1000s blocks. Rank by the smaller of the two relative total improvements. Lock top two new candidates; if none pass, evaluate top two as research only.',
        followup='Locked top two: full round1 at 5/20/50ms; sample_v2 stress at 5ms with SESSION_S=5750 and frozen weights. Existing F4 and CatBoost controls for both tapes.',
        limitation='All of round1 and sample_v2 were inspected in prior work. Chronological exclusion from fitting is not a fresh untouched test. No guarantee of winning or statistical significance.',
        gpu='Two CatBoost fits on RTX3070Ti; GPU training may be nondeterministic; exact exported parameters frozen and hashed.')
    dump(DEST / 'experiment_plan.json', plan)
    f, _, x = load_features()
    t = f[:,0] / 1e6
    y = future_change(f,.25)
    train = t + .25 < 6000
    valid = (t >= 6000) & (t + .25 < 9000)
    models, native, details = {}, {}, {}
    started = time.perf_counter()

    for name, estimator in [('ridge250', Ridge(alpha=100)),
                            ('huber250', HuberRegressor(epsilon=1.35,alpha=.01,max_iter=1000,tol=1e-7))]:
        with warnings.catch_warnings(record=True) as caught:
            spec, fitted = linear_fit(estimator,x[train],y[train])
        models[name] = [spec]
        details[name] = dict(rows_fit=int(train.sum()), warnings=[str(w.message) for w in caught],
            iterations=int(fitted.n_iter_) if name == 'huber250' else None,
            scale=float(fitted.scale_) if name == 'huber250' else None)
        native[name] = lambda z, s=spec: s['base'] + z @ np.array(s['coef'])

    cv = []
    for alpha in (.0001,.001,.01):
        fold_scores=[]
        for cut in (1500,3000,4500):
            a = t+.25 < cut
            b = (t >= cut) & (t+.25 < cut+1500)
            spec, _ = linear_fit(ElasticNet(alpha=alpha,l1_ratio=.5,max_iter=10000,tol=1e-7),x[a],y[a])
            pred=spec['base']+x[b] @ np.array(spec['coef'])
            fold_scores.append(stats(y[b],pred))
        cv.append(dict(alpha=alpha,folds=fold_scores,mse=float(np.mean([r['mse'] for r in fold_scores]))))
    alpha=min(cv,key=lambda r:r['mse'])['alpha']
    spec, fitted=linear_fit(ElasticNet(alpha=alpha,l1_ratio=.5,max_iter=10000,tol=1e-7),x[train],y[train])
    models['elastic250']=[spec]
    native['elastic250']=lambda z,s=spec:s['base']+z @ np.array(s['coef'])
    details['elastic250']=dict(alpha=alpha,cv=cv,nonzero_coefficients=int(np.count_nonzero(fitted.coef_)),rows_fit=int(train.sum()))

    forest=ExtraTreesRegressor(n_estimators=64,max_depth=4,min_samples_leaf=128,max_features=.75,
        bootstrap=False,n_jobs=20,random_state=20261108).fit(x[train],y[train])
    trees=[]
    for e in forest.estimators_:
        tr=e.tree_
        trees.append([[int(tr.feature[i]),float(tr.threshold[i]),int(tr.children_left[i]),
            int(tr.children_right[i]),float(tr.value[i,0,0])] for i in range(tr.node_count)])
    forest_spec=dict(kind='forest',trees=trees)
    models['forest250']=[forest_spec]
    native['forest250']=forest.predict
    details['forest250']=dict(rows_fit=int(train.sum()),trees=64,max_depth=4,total_nodes=sum(map(len,trees)))

    prior=load_json(PREVIOUS/'cat24_025s_parameters.json')
    old=dict(kind='cat',base=prior['ML_BASE'],scale=prior['ML_CB_SCALE'],trees=prior['ML_TREES'])
    old_model=CatBoostRegressor().load_model(str(PREVIOUS/'cat24_025s.cbm'))
    recent=train & (t>=3000)
    recent_spec,recent_model=cat_fit('recent_cat',x[recent],y[recent],None,20261108)
    weights=np.exp((t[train]-6000)/1800)
    decay_spec,decay_model=cat_fit('decay_cat',x[train],y[train],weights,20261109)
    members=[old,recent_spec,decay_spec]
    models['window_ensemble']=members
    models['guarded_ensemble']=members
    native['window_ensemble']=lambda z:np.column_stack([m.predict(z) for m in (old_model,recent_model,decay_model)]).mean(axis=1)
    def guard(z):
        values=np.column_stack([m.predict(z) for m in (old_model,recent_model,decay_model)])
        mean=values.mean(axis=1)
        return np.sign(mean)*np.maximum(0,np.abs(mean)-values.std(axis=1))
    native['guarded_ensemble']=guard
    details['window_ensemble']=dict(member_rows=[int(train.sum()),int(recent.sum()),int(train.sum())],gpu=True)
    details['guarded_ensemble']=dict(guard_standard_deviations=1)
    models['diverse_composite']=members+[models['elastic250'][0],forest_spec]
    native['diverse_composite']=lambda z:(native['window_ensemble'](z)+native['elastic250'](z)+forest.predict(z))/3
    details['diverse_composite']=dict(weights=[1/9,1/9,1/9,1/3,1/3])

    fit=t+.25<4800
    calibration=(t>=4800)&(t+.25<6000)
    mean,std=x[fit].mean(axis=0),x[fit].std(axis=0)
    std[std<1e-12]=1
    classes=np.sign(y).astype(int)
    classifier=LogisticRegression(C=.1,max_iter=2000,tol=1e-7).fit((x[fit]-mean)/std,classes[fit])
    logits=classifier.decision_function((x[calibration]-mean)/std)
    objective=lambda temp:log_loss(classes[calibration],softmax(logits/temp,axis=1),labels=classifier.classes_)
    temperature=float(minimize_scalar(objective,bounds=(.25,4),method='bounded').x)
    class_values=np.array([y[fit & (classes==c)].mean() for c in classifier.classes_])
    coef=classifier.coef_/std
    base=classifier.intercept_-coef@mean
    spec=dict(kind='logit',coef=coef.tolist(),base=base.tolist(),temperature=temperature,class_values=class_values.tolist())
    models['calibrated_logit']=[spec]
    native['calibrated_logit']=lambda z:softmax((z@coef.T+base)/temperature,axis=1)@class_values
    details['calibrated_logit']=dict(rows_fit=int(fit.sum()),calibration_rows=int(calibration.sum()),
        temperature=temperature,uncalibrated_logloss=objective(1),calibrated_logloss=objective(temperature),
        class_values=class_values.tolist(),classes=classifier.classes_.tolist())

    rows=[]
    for name, members in models.items():
        guard_value=1.0 if name=='guarded_ensemble' else 0.0
        weight=[1/9,1/9,1/9,1/3,1/3] if name=='diverse_composite' else None
        path=export(name,members,weight,guard_value)
        bot=load_strategy_from_file(path)
        test_x=x[valid][::11]
        expected=native[name](test_x)
        actual=np.array([bot.predict(row.tolist()) for row in test_x])
        error=float(np.max(np.abs(actual-expected)))
        assert error<1e-10,(name,error)
        prediction=native[name](x[valid])
        row=dict(name=name,source=str(path),sha256=file_hash(path),bytes=path.stat().st_size,
            export_max_error=error,forecast_validation=stats(y[valid],prediction),
            inactive_alpha_fraction=float(np.mean(np.abs(prediction)<1e-10)),details=details[name])
        rows.append(row)
        dump(DEST/'fit_progress.json',rows)
        print(json.dumps(row),flush=True)
    dump(DEST/'all_parameters.json',models)
    dump(DEST/'fit_results.json',dict(models=rows,seconds=time.perf_counter()-started))


if __name__=='__main__':
    with threadpool_limits(limits=8):
        main()
