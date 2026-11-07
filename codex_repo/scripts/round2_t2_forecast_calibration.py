"""Causal shrinkage calibration of stored out-of-sample price forecasts."""
from pathlib import Path
from scripts.round2_t2_structural import SOURCE
from scripts.round2_ra_composite import main
from scripts.benchmark import digest


def build():
    p=Path('strategies/round2/round2_local_294098.py')
    assert digest(p)=='06acfa3b209a6a3ccbf7beb08ec0715774c87bf98becdeae07f52465c3380f09'
    base=p.read_text()
    base=base.replace('        self.inventory = 0','''        self._fc_xx=self._fc_xy=0.0
        self._fc_time=None
        self._fc_count=0
        self.inventory = 0''',1)
    base=base.replace('observed_us, old_mid, features = self._observations.popleft()',
                      'observed_us, old_mid, features, forecast, old_spread = self._observations.popleft()',1)
    anchor='            elapsed = 0 if self._last_label_us is None else now - self._last_label_us'
    assert base.count(anchor)==1
    base=base.replace(anchor,'''            if forecast is not None and old_spread<=1 and abs(forecast)>=0.1:
                fc_decay=1.0 if self._fc_time is None else exp(-max(0,now-self._fc_time)/self.FC_MEMORY_US)
                self._fc_xx=self._fc_xx*fc_decay+forecast*forecast
                self._fc_xy=self._fc_xy*fc_decay+forecast*max(-3.0,min(3.0,mid-old_mid))
                self._fc_time=now
                self._fc_count+=1
'''+anchor,1)
    anchor='            self._observations.append((now,mid,features))'
    assert base.count(anchor)==1
    base=base.replace(anchor,'''            stored_forecast=None if self._labels<self.MIN_LABELS else max(-2.0,min(2.0,sum(w*x for w,x in zip(self._weights,features))))
            self._observations.append((now,mid,features,stored_forecast,spread))''',1)
    anchor='        fair = mid + 1.0*prediction'
    assert base.count(anchor)==1
    base=base.replace(anchor,'        prediction=self._calibrate_forecast(now,prediction)\n'+anchor,1)
    anchor='    def _learn(self, now, mid):'
    base=base.replace(anchor,'''    def _calibrate_forecast(self,now,prediction):
        if self._fc_time is None:
            return prediction
        decay=exp(-max(0,now-self._fc_time)/self.FC_MEMORY_US)
        gain=max(0.5,min(1.5,(20.0+decay*self._fc_xy)/(20.0+decay*self._fc_xx)))
        return max(-2.0,min(2.0,prediction*((1-self.FC_BLEND)+self.FC_BLEND*gain)))

'''+anchor,1)
    cases={}
    for memory,blend in ((300,.5),(300,1.0),(1800,.5),(1800,1.0)):
        cases[f'memory{memory}_blend{blend}']=base.replace('    FEATURE_COUNT = 33',
            f'    FC_MEMORY_US={memory*1000000}\n    FC_BLEND={blend}\n    FEATURE_COUNT = 33',1)
    return cases


if __name__=='__main__':
    main(Path('logs/round2_t2_forecast_calibration'),build(),
         'No-passive reference294098, causal stored raw forecasts and400ms outcomes. Narrow-spread absforecast>=0.1 calibration only, responseclip3, identity prior20, slopeclip0.5..1.5. Memory300/1800s and blend50/100percent; four frozen cases. No in-sample reconstructed forecasts. Reference later30-80=185349.',
         goal=dict(reference_audit='logs/round2_t2_liquidity_supplied/full_audit.json',reference_source_sha256=digest(SOURCE),increment=50000))
