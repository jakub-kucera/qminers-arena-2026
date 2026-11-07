"""Weight forecast fitting toward the low-volatility states receiving exposure.

The recorded weight is known at observation time. It cannot depend on the
future response or on later selection/final-public outcomes.
"""
from pathlib import Path

from scripts.build_round2_candidates import describe
from scripts.round2_jump_models import replace_once,run_study


def weighted_learning(base):
    text=replace_once(base,'observed_us, old_mid, features = self._observations.popleft()',
        'observed_us, old_mid, features, observation_weight = self._observations.popleft()')
    text=replace_once(text,'self._mass = self._mass * decay + 1.0',
        'self._mass = self._mass * decay + observation_weight')
    text=replace_once(text,'features[i] * response','observation_weight * features[i] * response')
    text=replace_once(text,'features[i] * features[j]','observation_weight * features[i] * features[j]')
    return replace_once(text,'self._observations.append((now,mid,features))',
        '''observation_weight=max(0.01,min(1.0,1/max(0.25,self._vol_variance)))
            self._observations.append((now,mid,features,observation_weight))''')


def main():
    base=Path('strategies/round2_research/round2_absolute_variance_112379.py').read_text()
    weighted=weighted_learning(base)
    cases={'risk_weighted_long':weighted,
        'risk_weighted_memory300':replace_once(weighted,'MODEL_MEMORY_US = 100000000000','MODEL_MEMORY_US = 300000000'),
        'robust_memory300':replace_once(base,'MODEL_MEMORY_US = 100000000000','MODEL_MEMORY_US = 300000000')}
    cases={n:describe(t,'Development-only risk-weighted/adaptive forecast hypothesis: '+n+
                      '. Observation weights are fixed before labels mature; original native rules.') for n,t in cases.items()}
    run_study(cases,'logs/round2/risk_weighted_learning',workers=3)


if __name__=='__main__':main()
