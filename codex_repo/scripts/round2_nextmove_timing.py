"""Event-time forecasting with fresh frames and a five-ms eligibility check."""
from pathlib import Path

from scripts.build_round2_candidates import describe
from scripts.round2_jump_models import replace_once,run_study
from scripts.round2_next_move import next_move


def main():
    base=Path('strategies/round2_research/round2_absolute_variance_112379.py').read_text()
    cases={}
    for amplitude in (.5,1.0):
        text=next_move(base,True,amplitude)
        text=replace_once(text,'OBSERVATION_INTERVAL_US = 20000','OBSERVATION_INTERVAL_US = 0')
        cases[f'nextmove_everyevent_amplitude{amplitude}']=text
    delayed=cases['nextmove_everyevent_amplitude1.0']
    delayed=replace_once(delayed,
        '''            if self._observations and self._observations[0][1]==old_mid:
                continue''',
        '''            if now-observed_us<5000:
                continue
            if (self._observations and self._observations[0][1]==old_mid and
                    self._observations[0][0]<=now-5000):
                continue''')
    cases['nextmove_latency_eligible']=delayed
    cases={n:describe(t,'Development-only event-clock forecasting hypothesis: '+n+
        '. Volatility parameters unchanged; all labels mature after the subsequent price move.') for n,t in cases.items()}
    run_study(cases,'logs/round2/nextmove_timing',workers=2)


if __name__=='__main__':main()
