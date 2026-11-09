"""Bounded update-speed and decay alternatives for conditional calibration."""
from pathlib import Path
from scripts.round2_conditional_calibration import build as original_build
from scripts.round2_ra_composite import main as run_study


def build():
    base=original_build()['side_spread1_blend1.0'];cases={}
    for rate in (.01,.1):
        anchor='alpha=0.03*min(1.0,quantity/100)'
        assert base.count(anchor)==1
        cases[f'rate{rate}']=base.replace(anchor,f'alpha={rate}*min(1.0,quantity/100)',1)
    for seconds in (60,900):
        anchor='exp(-max(0,now-self._cal_time)/300000000)'
        assert base.count(anchor)==2
        cases[f'decay{seconds}s']=base.replace(anchor,f'exp(-max(0,now-self._cal_time)/{seconds*1000000})')
    return cases


if __name__=='__main__':
    run_study(Path('logs/round2_calibration_dynamics'),build(),
        'One-factor update-speed0.01/0.1 or decay60/900seconds around the frozen conditional-calibration prefix winner; same labels and0.5correction cap.')
