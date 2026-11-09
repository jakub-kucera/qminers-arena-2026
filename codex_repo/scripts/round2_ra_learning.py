"""Causal flow-state features and bounded ridge-memory alternatives."""
from pathlib import Path
from scripts.round2_ra_composite import build as original_build,main as run_study


def build():
    base=original_build()['flow250_stop3_gate20_maker']
    cases={}
    for features,memory in ((True,100000),(True,300),(False,300),(False,900)):
        text=base.replace('MODEL_MEMORY_US = 100000000000',f'MODEL_MEMORY_US = {memory*1000000}')
        if features:
            text=text.replace('FEATURE_COUNT = 29','FEATURE_COUNT = 32',1)
            old='        m2_target=self._m2_target(now,bid,ask,trades)'
            assert text.count(old)==1
            text=text.replace(old,'',1)
            anchor='        mid = (bid+ask)*0.5'
            assert text.count(anchor)==1
            text=text.replace(anchor,anchor+'\n'+old,1)
            anchor='        if self._cal_time is not None:'
            assert text.count(anchor)==1
            text=text.replace(anchor,'''        features+=(max(-3,min(3,self._ra_sum/500)),float(self._m2_big),
                   0.0 if self._ra_stopped else float(self._m2_big))
'''+anchor,1)
        cases[f'signal_features{int(features)}_memory{memory}']=text
    return cases


if __name__=='__main__':
    run_study(Path('logs/round2_ra_learning'),build(),
        'Add causal accumulated flow, last signal and stopped-state features to the online ridge; compare 300/900-second memory with near-cumulative learning. Fixed fill trees unchanged.')
