"""Describe the new market and evaluate frozen forecasts without refitting."""
import json
from pathlib import Path

import numpy as np
from run_study import ROOT, dump
from round1_study import DEST


def profile_trace(path):
    trace = np.load(path)
    f = trace['features']
    t = f[:, 0]
    mid = (f[:, 1] + f[:, 2]) / 2
    spread = f[:, 2] - f[:, 1]
    depth = f[:, 3:5]
    valid = t + 1e6 <= t[-1]
    target = np.interp(t[valid] + 1e6, t, mid) - mid[valid]
    return dict(sample_count=len(t), first_mid=float(mid[0]), last_mid=float(mid[-1]),
        net_mid_change=float(mid[-1] - mid[0]), min_mid=float(mid.min()), max_mid=float(mid.max()),
        spread_quantiles=dict(zip(['q10', 'q50', 'q90', 'q99'], np.quantile(spread, [.1, .5, .9, .99]).tolist())),
        spread_one_fraction=float(np.mean(spread == 1)), spread_two_fraction=float(np.mean(spread == 2)),
        median_bid_depth=float(np.median(depth[:, 0])), median_ask_depth=float(np.median(depth[:, 1])),
        one_second_absolute_mid_move_mean=float(np.mean(abs(target))),
        one_second_mid_move_std=float(np.std(target)),
        method='Event snapshots sampled no faster than 100 ms; quantiles are sample-weighted, not exact time-weighted.'), f


def main():
    new_profile, f = profile_trace(DEST / 'record_trace.npz')
    old_profile, _ = profile_trace(ROOT / 'research/results/record_trace.npz')
    p = json.loads((ROOT / 'research/composite_results/model_params.json').read_text())
    t, x = f[:, 0], f[:, 5:]
    assert x.shape[1] == len(p['COEF1']) == 9
    mid = (f[:, 1] + f[:, 2]) / 2
    valid = t + 1e6 <= t[-1]
    x = x[valid]
    y = np.interp(t[valid] + 1e6, t, mid) - mid[valid]
    one = p['INTERCEPT1'] + x @ np.asarray(p['COEF1'])
    five = p['INTERCEPT5'] + x @ np.asarray(p['COEF5'])
    boosted = np.full(len(x), p['TREE_BASE'], dtype=float)
    for tree in p['TREES']:
        tree = np.asarray(tree, dtype=float)
        nodes = np.zeros(len(x), dtype=int)
        while True:
            active = np.flatnonzero(tree[nodes, 0] >= 0)
            if not len(active):
                break
            rows = tree[nodes[active]]
            nodes[active] = np.where(x[active, rows[:, 0].astype(int)] <= rows[:, 1], rows[:, 2], rows[:, 3]).astype(int)
        boosted += p['TREE_RATE'] * tree[nodes, 4]
    w = p['WEIGHTS']
    preds = {'ridge_1s': np.clip(one, -2, 2), 'ridge_5s_as_1s_predictor': np.clip(five, -2, 2),
             'boosted_1s': boosted, 'raw_microprice': x[:, 8],
             'ensemble': np.clip(w[0] * one + w[1] * five + w[2] * boosted + w[3] * x[:, 8], -2, 2),
             'zero': np.zeros(len(y))}
    metrics = {}
    for name, prediction in preds.items():
        metrics[name] = dict(mse=float(np.mean((prediction - y) ** 2)),
            correlation=float(np.corrcoef(prediction, y)[0, 1]) if np.std(prediction) else None,
            abs_prediction_q95=float(np.quantile(abs(prediction), .95)))
    result = dict(round1_market=new_profile, sample_v2_market=old_profile,
        frozen_forecast_metrics=metrics, target='One-second future mid, linearly interpolated on the sampled no-trade tape.',
        no_refitting=True, model_source='research/composite_results/model_params.json')
    dump(DEST / 'market_diagnostics.json', result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
