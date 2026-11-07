"""Forecast the next observed midpoint change instead of a fixed-time return.

Labels are recorded only after the price changes. The event-sampled variants
fit only the latest saved frame before each move. Risk sizing is held fixed.
"""
from pathlib import Path

from scripts.build_round2_candidates import describe
from scripts.round2_jump_models import replace_once,run_study


def next_move(base,event_sampled,amplitude):
    text=replace_once(base,'while self._observations and self._observations[0][0] + self.HORIZON_US <= now:',
        'while self._observations and abs(self._observations[0][1]-mid)>=0.5:')
    text=replace_once(text,'if now - observed_us > self.HORIZON_US + 1_000_000:',
        'if now - observed_us > 5_000_000:')
    text=replace_once(text,'response = max(-1.0, min(1.0, mid - old_mid))',
        f'response = {amplitude} if mid>old_mid else -{amplitude}')
    if event_sampled:
        text=replace_once(text,'            elapsed = 0 if self._last_label_us is None else now - self._last_label_us',
            '''            if self._observations and self._observations[0][1]==old_mid:
                continue
            elapsed = 0 if self._last_label_us is None else now - self._last_label_us''')
    return text


def main():
    base=Path('strategies/round2_research/round2_absolute_variance_112379.py').read_text()
    cases={}
    for event,amplitude in ((False,.5),(True,.5),(True,1.0)):
        name=f'nextmove_event{int(event)}_amplitude{amplitude}'
        cases[name]=describe(next_move(base,event,amplitude),
            'Development-only next-price-move forecasting hypothesis: '+name+
            '. Risk sizing unchanged; labels require the subsequent observed move, with a5sec stale-label rejection.')
    run_study(cases,'logs/round2/next_move',workers=2)


if __name__=='__main__':main()
