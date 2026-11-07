"""Mechanism checks following the first positive jump-aware development model."""
from pathlib import Path

from scripts.round2_jump_models import build_candidates,replace_once,run_study
from scripts.build_round2_candidates import describe


def main():
    base=Path('strategies/round2/round2_transfer.py').read_text()
    pause=build_candidates(base)['jump_pause100ms']
    clean=replace_once(pause,'        self._learn(now,mid)',
        '''        if spread<=2:
            self._learn(now,mid)
        else:
            while self._observations and self._observations[0][0]+self.HORIZON_US<=now:
                self._observations.popleft()''')
    clean=replace_once(clean,'if now-self._last_observation_us >= self.OBSERVATION_INTERVAL_US:',
        'if spread<=2 and now-self._last_observation_us >= self.OBSERVATION_INTERVAL_US:')
    cases={
        'pause_clean':clean,
        'pause_cancel_invalid':replace_once(pause,'now-self._invalid_since >= 50_000','now-self._invalid_since >= 0'),
        'pause500ms':replace_once(pause,'self._pause_until=now+100000','self._pause_until=now+500000'),
        'pause_no_spread_gate':replace_once(pause,'if spread>2 or now<self._pause_until:',
                                           'if now<self._pause_until:'),
        'spread_gate_only':replace_once(pause,'if spread>2 or now<self._pause_until:', 'if spread>2:'),
        'pause_labelhalf':replace_once(pause,'max(-1.0, min(1.0, mid - old_mid))',
                                      'max(-0.5, min(0.5, mid - old_mid))')}
    cases={n:describe(t,'Round-2 development jump-mechanism hypothesis: '+n+
                      '. Original native rules and causal labels.') for n,t in cases.items()}
    run_study(cases,'logs/round2/jump_followups',workers=2)


if __name__=='__main__':main()
