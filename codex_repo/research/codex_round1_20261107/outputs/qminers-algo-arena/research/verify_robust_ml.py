"""Check model export and preserve the previously tested causal/risk implementation."""
import ast
import json
import sys

import numpy as np

from ml_round1_common import file_hash, load_features, runtime_source
from robust_ml_common import DEST, ROOT, load_json
from run_study import dump, load_strategy_from_file


def methods(source):
    cls=next(n for n in ast.parse(source).body if isinstance(n,ast.ClassDef))
    return {n.name:ast.dump(n,include_attributes=False) for n in cls.body if isinstance(n,ast.FunctionDef)}


def main():
    original=methods(runtime_source())
    records=[]
    for spec in load_json(DEST/'fit_results.json')['models']:
        from pathlib import Path
        path=Path(spec['source'])
        assert file_hash(path)==spec['sha256']
        current=methods(path.read_text(encoding='utf-8'))
        for name,body in original.items():
            if name!='predict':
                assert body==current[name],(spec['name'],name)
        records.append(dict(name=spec['name'],unchanged_methods=len(original)-1,
            export_max_error=spec['export_max_error']))
    # Loss outcomes and class distribution explain the Huber near-zero solution.
    from ml_round1_common import future_change
    f,_,x=load_features()
    train=f[:,0]+250000<6000e6
    labels=future_change(f,.25)[train]
    actual_horizon=f[:,0][np.minimum(len(f)-1,np.searchsorted(f[:,0],f[:,0]+250000,side='right')-1)]-f[:,0]
    valid=(f[:,0]>=6000e6)&(f[:,0]+250000<9000e6)
    bot=load_strategy_from_file(DEST/'sources/guarded_ensemble.py')
    module=sys.modules['user_strategy_module']
    # Strong disagreement must fall back to zero; shrinkage cannot flip direction.
    module.ROBUST_MODELS=[dict(kind='linear',base=1.0,coef=[0]*24),dict(kind='linear',base=-1.0,coef=[0]*24)]
    module.ROBUST_WEIGHTS=[.5,.5]
    assert bot.predict([0]*24)==0
    module.ROBUST_MODELS=[dict(kind='linear',base=.4,coef=[0]*24),dict(kind='linear',base=.2,coef=[0]*24)]
    assert abs(bot.predict([0]*24)-.2)<1e-12
    module.ROBUST_MODELS=[dict(kind='linear',base=-.4,coef=[0]*24),dict(kind='linear',base=-.2,coef=[0]*24)]
    assert abs(bot.predict([0]*24)+.2)<1e-12
    # Labels are the last sampled midpoint at/before t+250ms, not interpolated future ticks.
    report=dict(records=records,risk_and_feature_methods_unchanged=True,guard_invariants_passed=True,
        training_label_zero_fraction=float(np.mean(labels==0)),training_rows=int(train.sum()),
        label_horizon_ms_quantiles=np.quantile(actual_horizon[valid]/1000,[0,.5,1]).tolist(),
        old_baseline_sha256=file_hash(ROOT/'strategies/round1_best.py'),
        old_ml_sha256=file_hash(ROOT/'strategies/round1_ml_candidate.py'))
    dump(DEST/'verification.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
