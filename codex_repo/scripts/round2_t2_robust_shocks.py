"""Robust causal regression using residuals of stored historical forecasts."""
from pathlib import Path
from scripts.round2_ra_composite import main
from scripts.benchmark import digest


def build():
    p=Path('strategies/round2/round2_local_304476.py')
    assert digest(p)=='bbf2558137756bc7ce1f0daf332c4438fa1ef3afb74f1cd1bcd8f5dfac5f1780'
    base=p.read_text()
    replacements=[('observed_us, old_mid, features = self._observations.popleft()',
                   'observed_us, old_mid, features, stored_forecast = self._observations.popleft()'),
                  ('            self._mass = self._mass * decay + 1.0',
                   '            residual=abs(response-stored_forecast)\n            weight=min(1.0,self.HUBER_DELTA/max(1e-12,residual))\n            self._mass = self._mass * decay + weight'),
                  ('features[i] * response','weight * features[i] * response'),
                  ('features[i] * features[j]','weight * features[i] * features[j]'),
                  ('            self._observations.append((now,mid,features))',
                   '            stored_forecast=max(-2.0,min(2.0,sum(w*x for w,x in zip(self._weights,features))))\n            self._observations.append((now,mid,features,stored_forecast))')]
    for old,new in replacements:
        assert base.count(old)==1,old
        base=base.replace(old,new,1)
    return {f'huber{delta}':base.replace('    FEATURE_COUNT = 35',
            f'    HUBER_DELTA={delta}\n    FEATURE_COUNT = 35',1) for delta in (3.0,6.0)}


if __name__=='__main__':
    main(Path('logs/round2_t2_robust_shocks'),build(),
         'Current user goal>=10k from upstream main, conservative local-cycle target306715. From304476 whose drawdown rose10880: robust weighted ridge with Huber residual threshold3/6 on matured400ms labels using forecasts stored at observation. Same weight in mass/covariance/xy; no crash-time or direction switches. Two frozen cases.',
         goal=306715)
