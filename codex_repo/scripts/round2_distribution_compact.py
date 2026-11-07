"""Ablate55-feature head to the strongest stable descriptive signals.

Selection of these features has seen all public diagnostics. This is reused
sample tuning, despite all fitted labels remaining strictly first60%.
"""
import argparse
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


def main():
    p=argparse.ArgumentParser();p.add_argument('--workers',type=int,default=2);a=p.parse_args()
    data=dict(np.load('logs/round2/distribution_research/observations.npz'))
    m=load_manifest(Path('logs/round2'));cut=m['development_cutoff_us']
    valid,y=labels(data,data['fill_t'],data['fill_price'],data['fill_sign'],400000,cut)
    root=Path('logs/round2/distribution_research/compact');root.mkdir(exist_ok=True)
    cases={};specs={}
    for name,indices,expression in (
        ('distribution_young_touch',[*range(18),38],'(sign*self._distribution_frame[0][20],)'),
        ('distribution_young_state',[*range(18),38,54,43],
            '(sign*self._distribution_frame[0][20],self._distribution_frame[1][-1],self._distribution_frame[1][1])')):
        x=data['fill_x'][valid][:,indices];w=np.minimum(20,data['fill_quantity'][valid])
        model=HistGradientBoostingRegressor(max_iter=64,max_leaf_nodes=15,min_samples_leaf=300,
            l2_regularization=100,learning_rate=.05,max_bins=64,early_stopping=False,random_state=44890)
        with _get_threadpool_controller().limit(limits=1):model.fit(x,np.clip(y[valid],-3,3),sample_weight=w)
        source=augment(fill_value_source(BASE.read_text(),model,0.0))
        source=replace_once(source,'return (1.0,min(3,sign*(mid-price)))+tuple(sign*features[i] for i in indices)',
            'return (1.0,min(3,sign*(mid-price)))+tuple(sign*features[i] for i in indices)+'+expression)
        source=describe(source,'Compact distribution fill-value hypothesis '+name+
            '. First60% fitted; feature choices reused full-public diagnostics. Risk parameters unchanged.')
        path=root/(name+'.py')
        if path.exists():assert path.read_text()==source
        else:path.write_text(source)
        assert not check(path),check(path)
        s=load_strategy_from_file(path);sample=x[::max(1,len(x)//500)]
        with _get_threadpool_controller().limit(limits=1):expected=model.predict(sample)
        error=float(np.max(abs(np.array([s._predict_fixed_trees(row) for row in sample])-expected)))
        assert error<1e-10
        cases[name]=source;specs[name]=dict(source_sha256=digest(path),columns=indices,
            training_rows=len(x),horizon_us=400000,clip=3,weight_cap=20,export_max_error=error)
    write_json(root/'fit_specs.json',specs)
    run_public_study(cases,root/'replays',workers=a.workers)


if __name__=='__main__':main()
