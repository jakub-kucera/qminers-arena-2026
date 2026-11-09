"""Align the gate's shadow policy and avoid threshold-induced mode churn."""
from pathlib import Path
from scripts.benchmark import digest
from scripts.round2_ra_composite import main as run_study


def build():
    p=Path('strategies/round2/round2_local_195721.py')
    assert digest(p)=='e2d55a7d606b1a679070bc386182c38d7bf8b35da8b5a77d6a55ae408b0118e2'
    base=p.read_text();cases={}
    for stopped,hysteresis in ((False,5),(False,0),(True,None),(True,5)):
        text=base
        if stopped:
            text=text.replace('        self._ra_flow=deque()','''        self._shadow_ra_stopped=False
        self._shadow_ra_anchor=0.0
        self._ra_flow=deque()''',1)
            text=text.replace('        if fired:\n', '''        if fired:
            if fired!=self._m2_big or self._shadow_ra_stopped:
                self._shadow_ra_anchor=mid
                self._shadow_ra_stopped=False
''',1)
            anchor='        step=self._m2_big-self._m2_shadow_pos'
            assert text.count(anchor)==1
            text=text.replace(anchor,'''        if not self._shadow_ra_stopped and self._m2_shadow_pos:
            if self._m2_big*(self._shadow_ra_anchor-mid)>=3:
                self._shadow_ra_stopped=True
        shadow_desired=0 if self._shadow_ra_stopped else self._m2_big
        step=shadow_desired-self._m2_shadow_pos''',1)
            text=text.replace('            self._m2_shadow_pos=self._m2_big','            self._m2_shadow_pos=shadow_desired',1)
        if hysteresis is not None:
            text=text.replace('        self._m2_big=0','        self._regime_active=False\n        self._m2_big=0',1)
            anchor='        if now-self._m2_start>=60000000 and score>10 and score-self._m2_history[0][1]>20:'
            assert text.count(anchor)==1
            text=text.replace(anchor,f'''        if now-self._m2_start>=60000000 and score>10:
            recent=score-self._m2_history[0][1]
            self._regime_active=recent>{hysteresis} if self._regime_active else recent>20
        else:
            self._regime_active=False
        if self._regime_active:''',1)
        cases[f'stopped_shadow{int(stopped)}_exit{hysteresis}']=text
    return cases


if __name__=='__main__':
    run_study(Path('logs/round2_ra_regime'),build(),
        'Reduce mode churn with entry20/exit5 or0 hysteresis, and compare an independently simulated stopped shadow with the original unstopped shadow. Current/past information only.')
