"""Fixed convex blend of broad and narrow-spread causal ridge learners."""
from pathlib import Path
from scripts.round2_t2_structural import SOURCE
from scripts.round2_ra_composite import main
from scripts.benchmark import digest


def build():
    p=Path('strategies/round2/round2_local_296715.py')
    assert digest(p)=='33ec43e71347d9bf3ea81e7ee48c2bfd48d2310abc784a33c1ed614f5218fd55'
    base=p.read_text()
    anchor='        self._weights = [0.0] * self.FEATURE_COUNT'
    assert base.count(anchor)==1
    base=base.replace(anchor,anchor+'''
        self._narrow_observations=deque(maxlen=64)
        self._narrow_state=dict(_last_fit_us=None,_last_label_us=None,_labels=0,_mass=0.0,
            _xx=[[0.0]*self.FEATURE_COUNT for _ in range(self.FEATURE_COUNT)],
            _xy=[0.0]*self.FEATURE_COUNT,_weights=[0.0]*self.FEATURE_COUNT)
''',1)
    base=base.replace('    def _learn(self, now, mid):','''    def _learn(self,now,mid):
        self._learn_head(now,mid)
        broad=(self._last_fit_us,self._last_label_us,self._labels,self._mass,self._xx,self._xy,self._weights)
        self._observations,self._narrow_observations=self._narrow_observations,self._observations
        self._last_fit_us,self._last_label_us,self._labels,self._mass,self._xx,self._xy,self._weights=(self._narrow_state['_last_fit_us'],self._narrow_state['_last_label_us'],self._narrow_state['_labels'],self._narrow_state['_mass'],self._narrow_state['_xx'],self._narrow_state['_xy'],self._narrow_state['_weights'])
        try:
            self._learn_head(now,mid)
        finally:
            self._narrow_state=dict(_last_fit_us=self._last_fit_us,_last_label_us=self._last_label_us,_labels=self._labels,_mass=self._mass,_xx=self._xx,_xy=self._xy,_weights=self._weights)
            self._last_fit_us,self._last_label_us,self._labels,self._mass,self._xx,self._xy,self._weights=broad
            self._observations,self._narrow_observations=self._narrow_observations,self._observations

    def _blend_forecast(self,prediction,features):
        if self._narrow_state['_labels']<self.MIN_LABELS:
            return prediction
        narrow=max(-2.0,min(2.0,sum(w*x for w,x in zip(self._narrow_state['_weights'],features))))
        return (1-self.NARROW_BLEND)*prediction+self.NARROW_BLEND*narrow

    def _learn_head(self, now, mid):''',1)
    base=base.replace('            self._observations.clear()',
                      '            self._observations.clear()\n            self._narrow_observations.clear()',1)
    anchor='            self._observations.append((now,mid,features))'
    assert base.count(anchor)==1
    base=base.replace(anchor,anchor+'''
            if spread<=1:
                self._narrow_observations.append((now,mid,features))''',1)
    anchor='        fair = mid + 1.0*prediction'
    assert base.count(anchor)==1
    base=base.replace(anchor,'        prediction=self._blend_forecast(prediction,features)\n'+anchor,1)
    return {f'narrow_blend{blend}':base.replace('    FEATURE_COUNT = 33',
            f'    NARROW_BLEND={blend}\n    FEATURE_COUNT = 33',1) for blend in (.25,.5,.75)}


if __name__=='__main__':
    main(Path('logs/round2_t2_dual_head_v2'),build(),
         'Two independent causal ridge3x learners on same33features: all-spread and observed-spread1 samples. Fixed narrow forecast blend25/50/75percent; broad fallback before narrow warmup. Both400ms target and native execution unchanged. Three frozen cases, no full-score weighting. Reference296715 later30-80=188941.',
         goal=dict(reference_audit='logs/round2_t2_liquidity_supplied/full_audit.json',reference_source_sha256=digest(SOURCE),increment=50000))
