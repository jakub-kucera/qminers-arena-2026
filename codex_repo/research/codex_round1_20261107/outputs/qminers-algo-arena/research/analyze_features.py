"""Chronological, purged linear fit and descriptive signal probes; no shuffled events."""
import json
from pathlib import Path
import numpy as np
from run_study import ROOT, OUT, dump

NAMES = ['spread','touch_imbalance','depth5_imbalance','flow_1s',
         'mid_minus_ema1s','mid_minus_ema5s','log_touch_depth','log_flow_volume','microprice_minus_mid']


def corr(a, b):
    if len(a) < 3 or np.std(a) == 0 or np.std(b) == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def main():
    arrays = np.load(OUT/'record_trace.npz')
    f = arrays['features']
    t, bid, ask = f[:, 0], f[:, 1], f[:, 2]
    mid = (bid+ask)/2
    x = f[:, 5:]
    cutoff1 = t[0] + (t[-1]-t[0])*0.5
    cutoff2 = t[0] + (t[-1]-t[0])*0.75
    stats = dict(observations=len(t), observation='First book event at least 100 ms after last sampled event; event-time sampled, not wall-time weighted.',
                 feature_names=NAMES, spread_quantiles=np.quantile(ask-bid,[0,.25,.5,.75,.95,1]).tolist(),
                 touch_depth_quantiles=np.quantile(f[:,3:5],[.1,.5,.9],axis=0).tolist(),
                 mid_range=[float(mid.min()),float(mid.max())], mid_start_end=[float(mid[0]),float(mid[-1])],
                 split_seconds=[float(cutoff1/1e6),float(cutoff2/1e6)], horizons={})
    for seconds in (0.1,1,5):
        future = np.searchsorted(t, t+seconds*1e6, side='right')-1
        y = mid[future]-mid
        # Purge each label crossing a partition boundary. Require 10 s warm-up.
        train = (t>=t[0]+10e6)&(t+seconds*1e6<cutoff1)
        valid = (t>=cutoff1)&(t+seconds*1e6<cutoff2)
        diagnostic = (t>=cutoff2)&(t+seconds*1e6<=t[-1])
        mu, sd = x[train].mean(axis=0), x[train].std(axis=0)
        sd = np.maximum(sd,1e-9)
        z = (x-mu)/sd
        ybar = float(y[train].mean())
        # Fixed regularization, no test-set parameter selection.
        coef_scaled = np.linalg.solve(z[train].T@z[train]+100*np.eye(x.shape[1]), z[train].T@(y[train]-ybar))
        coef = coef_scaled/sd
        intercept = ybar-float(mu@coef)
        pred = x@coef+intercept
        horizon = {'ridge_alpha':100,'coefficients':coef.tolist(),'intercept':intercept,'splits':{}}
        for label, mask in [('train',train),('validation',valid),('diagnostic_tail',diagnostic)]:
            horizon['splits'][label] = dict(n=int(mask.sum()),mean_move=float(y[mask].mean()),
                ridge_correlation=corr(pred[mask],y[mask]),
                ridge_mse=float(np.mean((pred[mask]-y[mask])**2)),zero_mse=float(np.mean(y[mask]**2)),
                prediction_abs_q95=float(np.quantile(np.abs(pred[mask]),.95)),
                feature_correlations={n:corr(x[mask,i],y[mask]) for i,n in enumerate(NAMES)})
        stats['horizons'][str(seconds)] = horizon
        if seconds == 1:
            one_second = horizon

    flow = arrays['flow_events']
    # Quantity-weighted signed mid changes after actual market-market matches.
    marks = {}
    for seconds in (.1,1,5):
        eligible = (flow[:,0]>=t[0]) & (flow[:,0]+seconds*1e6<=t[-1])
        tr = flow[eligible]
        at = np.searchsorted(t,tr[:,0],side='right')-1
        after = np.searchsorted(t,tr[:,0]+seconds*1e6,side='right')-1
        values = tr[:,1]*(mid[after]-mid[at])
        marks[str(seconds)] = dict(matches=len(tr),lots=int(tr[:,2].sum()),
             quantity_weighted_signed_mid_change=float(np.average(values,weights=tr[:,2])))
    stats['trade_markouts_sampled_mid'] = marks
    stats['markout_caveat'] = 'Mid uses last sample at or before each timestamp (up to about 100 ms stale). Label horizons are diagnostic, not executable PnL.'
    dump(OUT/'signal_analysis.json',stats)
    duration = json.loads((OUT/'dataset_profile.json').read_text())['duration_s']
    own = ROOT/'strategies/research_candidate.py'
    modelparams = dict(COEFFICIENTS=one_second['coefficients'],INTERCEPT=one_second['intercept'],SESSION_S=duration)
    tasks = [[n,str(own),str(ROOT/'data/sample_v2.csv'),dict(modelparams,MODE=mode),5]
             for n,mode in [('ridge_ioc','ridge_ioc'),('ridge_maker','ridge_maker')]]
    dump(OUT/'models_plan.json', tasks)
    print(json.dumps({k:v for k,v in stats.items() if k!='horizons'},indent=2))
    print('Ridge 1-second validation:',one_second['splits']['validation'])


if __name__ == '__main__':
    main()
