"""Four predeclared hypotheses from order-size and fill-tail distributions.

Risk sizing and all exchange rules stay fixed. Fits use only public first60%;
all full-public comparisons are reused-sample selection, not hidden validation.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.utils.parallel import _get_threadpool_controller

from scripts.benchmark import digest
from scripts.build_round2_candidates import describe
from scripts.check_submission import check
from scripts.round2_distribution_features import augment
from scripts.round2_distribution_stats import labels
from scripts.round2_full_public_study import run_public_study
from scripts.round2_jump_models import replace_once
from scripts.round2_pretrained_alpha import BASE
from scripts.round2_pretrained_fill_value import fill_value_source
from scripts.round2_workbench import load_manifest,write_json
from simulator.main import load_strategy_from_file

ROOT=Path('logs/round2/distribution_research')
SPECS=[
    dict(name='distribution_rich400',rich=True,horizon_us=400000,clip=3,weight_cap=20,depletion_weight=1),
    dict(name='distribution_tail400',rich=False,horizon_us=400000,clip=10,weight_cap=100,depletion_weight=1),
    dict(name='distribution_queue400',rich=True,horizon_us=400000,clip=10,weight_cap=100,depletion_weight=4),
    dict(name='distribution_long1000',rich=True,horizon_us=1000000,clip=10,weight_cap=100,depletion_weight=1),
]


def export_fill(model,rich):
    text=fill_value_source(BASE.read_text(),model,0.0)
    if rich:
        text=augment(text)
        text=replace_once(text,'return (1.0,min(3,sign*(mid-price)))+tuple(sign*features[i] for i in indices)',
            'return ((1.0,min(3,sign*(mid-price)))+tuple(sign*features[i] for i in indices)\n'
            '                +tuple(sign*x for x in self._distribution_frame[0])+self._distribution_frame[1])')
    return text


def score_groups(pred,y,w,depleted):
    out={}
    for name,m in [('all',np.ones(len(y),dtype=bool)),('gate_open',pred>=0),('gate_closed',pred<0),
        ('exhausted_gate_open',(pred>=0)&depleted),('surviving_gate_open',(pred>=0)&~depleted)]:
        if not m.any():out[name]={'n':0};continue
        out[name]=dict(n=int(m.sum()),weight_fraction=float(w[m].sum()/w.sum()),
            actual_mean=float(np.average(y[m],weights=w[m])),prediction_mean=float(np.average(pred[m],weights=w[m])),
            loss_gt3_fraction=float(np.mean(y[m]<-3)))
    return out


def fit_models():
    m=load_manifest(Path('logs/round2'));data=dict(np.load(ROOT/'observations.npz'))
    metadata=json.loads((ROOT/'metadata.json').read_text())
    assert metadata['data_sha256']==m['data_sha256']
    assert metadata['features_sha256']==digest('scripts/round2_distribution_features.py')
    assert metadata['collector_sha256']==digest('scripts/round2_distribution_collect.py')
    out=ROOT/'models';out.mkdir(exist_ok=True);cases={};specs={}
    t=data['fill_t'];end=metadata['last_event_us'];cut=m['development_cutoff_us']
    for spec in SPECS:
        h=spec['horizon_us'];valid,y=labels(data,t,data['fill_price'],data['fill_sign'],h,end)
        fit=valid&(t+h<cut)
        w=np.minimum(data['fill_quantity'],spec['weight_cap']).astype(float)
        w*=np.where(data['fill_depleted'],spec['depletion_weight'],1)
        x=data['fill_x'] if spec['rich'] else data['fill_x'][:,:18]
        model=HistGradientBoostingRegressor(max_iter=64,max_leaf_nodes=15,min_samples_leaf=300,
            l2_regularization=100,learning_rate=.05,max_bins=64,early_stopping=False,random_state=44890)
        with _get_threadpool_controller().limit(limits=1):
            model.fit(x[fit],np.clip(y[fit],-spec['clip'],spec['clip']),sample_weight=w[fit])
            predictions=model.predict(x)
        name=spec['name'];source=describe(export_fill(model,spec['rich']),
            'Round2 distribution-derived '+name+'. First60% public fit; subsequent public tuning reused. Native rules and risk sizing unchanged.')
        path=out/(name+'.py')
        if path.exists():assert path.read_text()==source
        else:path.write_text(source)
        assert not check(path),check(path)
        s=load_strategy_from_file(path);sample=np.arange(0,len(x),max(1,len(x)//500))
        delta=float(np.max(np.abs(np.array([s._predict_fixed_trees(x[i]) for i in sample])-predictions[sample])))
        assert delta<1e-10
        diagnostics={}
        # Evaluation horizon fixed400ms/1s for comparison, without clipping in reports.
        for eval_h in (400000,1000000):
            ok,raw=labels(data,t,data['fill_price'],data['fill_sign'],eval_h,end)
            for segment,select in [('fit_first60',t+max(h,eval_h)<cut),('beyond_fit_later40',t>=cut)]:
                mask=ok&select
                diagnostics[f'{segment}_{eval_h}']=score_groups(predictions[mask],raw[mask],
                    np.minimum(data['fill_quantity'][mask],100),data['fill_depleted'][mask])
        specs[name]=dict(**spec,training_rows=int(fit.sum()),training_last_label_before_us=cut,
            source_sha256=digest(path),export_max_error=delta,diagnostics=diagnostics)
        cases[name]=source
        print('FIT',name,'rows',int(fit.sum()),'later400',diagnostics['beyond_fit_later40_400000'],flush=True)
    write_json(out/'fit_specs.json',dict(data_sha256=m['data_sha256'],fitting_data_sha256=m['development_sha256'],
        observation_sha256=digest(ROOT/'observations.npz'),models=specs,
        protocol='Four predeclared mechanisms, unchanged risk parameters; no server/private scores. Queue depletion changes offline weights only and is NOT a runtime feature.'))
    return cases


def main():
    p=argparse.ArgumentParser();p.add_argument('--fit-only',action='store_true');p.add_argument('--workers',type=int,default=2)
    a=p.parse_args();cases=fit_models()
    if not a.fit_only:run_public_study(cases,ROOT/'model_replays',workers=a.workers)


if __name__=='__main__':main()
