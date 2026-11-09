"""Train small, exportable models with strictly chronological development splits."""
import copy
import json
import time
from datetime import datetime, timezone

import catboost
import numpy as np
from catboost import CatBoostRegressor
from sklearn.linear_model import Ridge
from sklearn.neural_network import MLPRegressor
from threadpoolctl import threadpool_limits

from ml_round1_common import (DEST, FIT_END, MODEL_VALID_END, POLICY_END, ROOT,
    WORK, export, file_hash, future_change, load_features)
from run_study import dump, load_bot


def metrics(y, pred):
    return dict(mse=float(np.mean((y - pred) ** 2)),
                correlation=float(np.corrcoef(y, pred)[0, 1]) if np.std(pred) else None)


def fit_ridge(x, y):
    mean, std = x.mean(axis=0), x.std(axis=0)
    std[std < 1e-12] = 1
    model = Ridge(alpha=100.0).fit((x - mean) / std, y)
    coef = model.coef_ / std
    base = float(model.intercept_ - mean @ coef)
    return dict(ML_KIND='ridge', ML_COEF=coef.tolist(), ML_BASE=base)


def fit_cat(name, x, y, time_us, horizon, weights=None):
    train = time_us + horizon * 1e6 < FIT_END * 1e6
    valid = (time_us >= FIT_END * 1e6) & (time_us + horizon * 1e6 < MODEL_VALID_END * 1e6)
    final = time_us + horizon * 1e6 < MODEL_VALID_END * 1e6
    config = dict(iterations=192, depth=4, learning_rate=.05, l2_leaf_reg=10,
        loss_function='RMSE', random_seed=20261107, task_type='GPU', devices='0',
        thread_count=8, gpu_ram_part=.65, verbose=False, allow_writing_files=False)
    before = time.perf_counter()
    probe = CatBoostRegressor(**config)
    probe.fit(x[train], y[train], sample_weight=weights[train] if weights is not None else None,
              eval_set=(x[valid], y[valid]), early_stopping_rounds=24)
    count = int(probe.tree_count_)
    internal = metrics(y[valid], probe.predict(x[valid]))
    fitted = CatBoostRegressor(**dict(config, iterations=count))
    fitted.fit(x[final], y[final], sample_weight=weights[final] if weights is not None else None)
    fitted.save_model(str(DEST / f'{name}.cbm'))
    fitted.save_model(str(DEST / f'{name}_catboost.json'), format='json')
    raw = json.loads((DEST / f'{name}_catboost.json').read_text())
    mapping = {v['feature_index']: v['flat_feature_index'] for v in raw['features_info']['float_features']}
    trees = []
    for tree in raw['oblivious_trees']:
        splits = [(mapping[s['float_feature_index']], s['border']) for s in (tree['splits'] or [])]
        trees.append((splits, tree['leaf_values']))
    spec = dict(ML_KIND='catboost', ML_BASE=raw['scale_and_bias'][1][0],
                ML_CB_SCALE=raw['scale_and_bias'][0], ML_TREES=trees)
    return spec, fitted, dict(iterations=count, internal_validation=internal,
        seconds=time.perf_counter() - before, gpu=True, rows_fit=int(final.sum()), configuration=config)


def fit_neural(x, y, t):
    early = t + 1e6 < FIT_END * 1e6
    tune = (t >= FIT_END * 1e6) & (t + 1e6 < MODEL_VALID_END * 1e6)
    final = t + 1e6 < MODEL_VALID_END * 1e6
    config = dict(hidden_layer_sizes=(32, 16), activation='relu', solver='adam',
        alpha=.1, batch_size=512, learning_rate_init=.001, max_iter=1,
        random_state=20261107, shuffle=True)
    mean, std = x[early].mean(axis=0), x[early].std(axis=0)
    std[std < 1e-12] = 1
    train, val = (x[early] - mean) / std, (x[tune] - mean) / std
    model = MLPRegressor(**config)
    best_epoch, best_loss, stale = 0, float('inf'), 0
    before = time.perf_counter()
    history = []
    with threadpool_limits(limits=4):
        for epoch in range(1, 101):
            model.partial_fit(train, y[early])
            loss = float(np.mean((model.predict(val) - y[tune]) ** 2))
            history.append(loss)
            if loss < best_loss - 1e-5:
                best_epoch, best_loss, stale = epoch, loss, 0
            else:
                stale += 1
            if stale >= 12:
                break
        mean, std = x[final].mean(axis=0), x[final].std(axis=0)
        std[std < 1e-12] = 1
        model = MLPRegressor(**config)
        normalized = (x[final] - mean) / std
        for _ in range(best_epoch):
            model.partial_fit(normalized, y[final])
    spec = dict(ML_KIND='mlp', ML_MEAN=mean.tolist(), ML_STD=std.tolist(),
        ML_W=[w.T.tolist() for w in model.coefs_], ML_B=[b.tolist() for b in model.intercepts_])
    return spec, model, dict(epochs=best_epoch, internal_validation_mse=best_loss,
                            epoch_validation_mse=history, seconds=time.perf_counter() - before, gpu=False)


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    plan = dict(created_utc=datetime.now(timezone.utc).isoformat(),
        internal_fit_s=[0, FIT_END], early_stopping_s=[FIT_END, MODEL_VALID_END],
        final_model_fit_s=[0, MODEL_VALID_END], policy_validation_s=[MODEL_VALID_END, POLICY_END],
        diagnostic_tail_s=[POLICY_END, 12000],
        models=['ridge9_1s','ridge24_1s','cat9_1s','cat24_1s','cat24_025s','mlp24_1s','cat_fill25'],
        policy_variants=[dict(TARGET_ALPHA=0.0, EDGE_FLOOR=.15), dict(TARGET_ALPHA=40.0, EDGE_FLOOR=.15)],
        baselines=['F4 parity control', 'raw microprice with the same two policy variants'],
        selection='Highest 6000–9000s PnL among ML policies with zero penalties and reserved exposure <=100. Lock one ML finalist before a full-tape replay; compare to F4 and any better simple baseline. No refit on the diagnostic tail.',
        tail_limitation='The entire round was already inspected in preceding comparisons. This is a reused diagnostic tail, not an untouched holdout.',
        models_fit_on='round1 only, first half; labels crossing split boundaries are excluded',
        catboost_version=catboost.__version__, gpu='NVIDIA RTX 3070 Ti Laptop GPU 8GB',
        gpu_nondeterminism='GPU fitting is not bitwise deterministic. Trained files, exported literal weights, and their hashes are retained.')
    assert not (DEST / 'fit_results.json').exists(), 'Training already frozen; do not overwrite fitted models.'
    dump(DEST / 'experiment_plan.json', plan)
    f, small, history = load_features()
    t = f[:, 0]
    y1, yquarter = future_change(f, 1), future_change(f, .25)
    fit = t + 1e6 < MODEL_VALID_END * 1e6
    valid = (t >= MODEL_VALID_END * 1e6) & (t + 1e6 < POLICY_END * 1e6)
    models, results = {}, {}

    def save(name, spec, x, target, native=None, info=None):
        spec['ML_HISTORY'] = x.shape[1] >= 24
        path = export(f'predict_{name}', spec)
        bot = load_bot(path, {})
        sample_index = np.linspace(0, len(x) - 1, min(2500, len(x))).astype(int)
        sample = x[sample_index]
        predicted = np.array([bot.predict(row.tolist()) for row in sample])
        if spec['ML_KIND'] in ('catboost', 'fillcat'):
            expected = native.predict(sample)
        elif spec['ML_KIND'] == 'mlp':
            expected = native.predict((sample - np.asarray(spec['ML_MEAN'])) / np.asarray(spec['ML_STD']))
        else:
            expected = spec['ML_BASE'] + sample @ np.asarray(spec['ML_COEF'])
        error = float(np.max(abs(expected - predicted)))
        assert error < 1e-8, (name, error)
        models[name] = spec
        dump(DEST / f'{name}_parameters.json', spec)
        results[name] = dict(info or {}, export_max_error=error, file_sha256=file_hash(path),
                             prediction_source=str(path), input_features=x.shape[1])
        if len(x) == len(t):
            prediction = np.array([bot.predict(row.tolist()) for row in x[valid]])
            results[name]['policy_validation_forecast'] = metrics(target[valid], prediction)
        dump(DEST / 'fit_results_progress.json', results)
        print(json.dumps(dict(model=name, **results[name])), flush=True)

    for name, x in [('ridge9_1s', small), ('ridge24_1s', history)]:
        save(name, fit_ridge(x[fit], y1[fit]), x, y1, info=dict(gpu=False, rows_fit=int(fit.sum())))
    for name, x, y, horizon in [('cat9_1s',small,y1,1), ('cat24_1s',history,y1,1),
                                 ('cat24_025s',history,yquarter,.25)]:
        spec, native, info = fit_cat(name, x, y, t, horizon)
        save(name, spec, x, y, native, info)
    spec, native, info = fit_neural(history, y1, t)
    save('mlp24_1s', spec, history, y1, native, info)

    fills = np.load(ROOT / 'research/round1_results/team_F4_trace.npz')['private_fills']
    fills = fills[(fills[:, 0] + 1e6 < MODEL_VALID_END * 1e6) & (fills[:, 0] - 5000 >= t[0])]
    before = np.searchsorted(t, fills[:, 0] - 5000, side='right') - 1
    future = np.searchsorted(t, fills[:, 0] + 1e6, side='right') - 1
    signs = np.sign(fills[:, 2])
    inputs = np.column_stack([history[before], signs])
    mid = (f[:, 1] + f[:, 2]) / 2
    decision_touch = np.where(signs > 0, f[before, 1], f[before, 2])
    target = signs * (mid[future] - decision_touch)
    spec, native, info = fit_cat('cat_fill25', inputs, target, fills[:, 0], 1, np.minimum(abs(fills[:, 2]),100))
    spec['ML_KIND'] = 'fillcat'
    info['target'] = 'One-second signed mid markout from the earlier decision touch, conditioned on actual F4 fills. Features are from >=5ms before fill; quantity weights capped at 100.'
    save('cat_fill25', spec, inputs, target, native, info)

    # Streaming history export must exactly match batch causal feature construction.
    bot = load_bot(DEST / 'sources/predict_cat24_1s.py', {})
    error = 0.0
    for i in range(len(f)):
        actual = bot.expand_features(t[i], (f[i,1]+f[i,2])/2, small[i].tolist())
        error = max(error, float(np.max(abs(np.asarray(actual) - history[i]))))
    assert error < 1e-10, error
    dump(DEST / 'feature_parity.json', dict(rows=len(f), maximum_error=error,
        current_feature_count=9, history_feature_count=24, lags_ms=[250,1000,5000]))
    results['_verification'] = dict(feature_parity_max_error=error, training_tail_excluded=True)
    dump(DEST / 'fit_results.json', results)
    dump(DEST / 'all_model_parameters.json', models)


if __name__ == '__main__':
    main()
