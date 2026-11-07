"""Test inventory-quality label horizons without changing the price learner."""
from pathlib import Path
from scripts.benchmark import digest
from scripts.round2_ra_composite import main as run_study


def build():
    p=Path('strategies/round2/round2_local_209795.py')
    assert digest(p)=='df93cf43167894a1fe00a67b459f32d655ecbc8a5d5a2e4f036f54645e05af90'
    base=p.read_text();cases={}
    for milliseconds in (100,200,800,2000):
        maturity='self._cal_labels[0][0]+400000<=now'
        stale='now-observed<=1400000'
        assert base.count(maturity)==1 and base.count(stale)==1
        text=base.replace(maturity,f'self._cal_labels[0][0]+{milliseconds*1000}<=now',1)
        text=text.replace(stale,f'now-observed<={milliseconds*1000+1000000}',1)
        cases[f'fill_horizon{milliseconds}ms']=text
    return cases


if __name__=='__main__':
    run_study(Path('logs/round2_calibration_horizon'),build(),
        'Change only the causal fill-gate target horizon to100/200/800/2000ms, with stale tolerance1s beyond maturity. Static tree and online price learner remain400ms; correction may adapt their score to inventory quality over another horizon. Reference209795 first80=184980, later50=148868.')
