"""Development-only forecast ablations after freezing the first public finalist.

These candidates do not alter the frozen source undergoing its final public
check. Their later-public performance is not evaluated by this script.
"""
from pathlib import Path

from scripts.build_round2_candidates import describe
from scripts.round2_jump_models import replace_once,run_study


def main():
    base=Path('strategies/round2_research/round2_absolute_variance_112379.py').read_text()
    symmetric=replace_once(base,'        self._learn(now,mid)','        # No forecast fitting in this ablation.')
    symmetric=replace_once(symmetric,'        fair = mid + ', '        prediction=0.0\n        fair = mid + ')
    raw=replace_once(base,'max(-1.0, min(1.0, mid - old_mid))','max(-20.0, min(20.0, mid - old_mid))')
    clean=replace_once(base,'        self._learn(now,mid)',
        '''        if spread<=2:
            self._learn(now,mid)
        else:
            while self._observations and self._observations[0][0]+self.HORIZON_US<=now:
                self._observations.popleft()''')
    clean=replace_once(clean,'if now-self._last_observation_us >= self.OBSERVATION_INTERVAL_US:',
        'if spread<=2 and now-self._last_observation_us >= self.OBSERVATION_INTERVAL_US:')
    cases={'variance_no_alpha':symmetric,'variance_raw_labels':raw,'variance_clean_labels':clean}
    cases={n:describe(t,'Development-only absolute-volatility forecast ablation: '+n+
                      '. Does not change the frozen public-check candidate.') for n,t in cases.items()}
    run_study(cases,'logs/round2/volatility_ablations',workers=3)


if __name__=='__main__':main()
