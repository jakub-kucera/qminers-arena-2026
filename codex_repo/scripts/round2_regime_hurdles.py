"""Predeclared higher-profit hurdles on the already-consumed public prefix."""
from pathlib import Path
from scripts import round2_regime_composite as study

original_build = study.build


def build():
    original = original_build()
    cases = {}
    for seconds, threshold in ((60,20),(60,40),(300,50),(300,100)):
        text = original[f'mix_{seconds}s_gate0']
        anchor = 'score-self._m2_history[0][1]>0:'
        assert text.count(anchor) == 1
        cases[f'mix_{seconds}s_gate{threshold}'] = text.replace(
            anchor, f'score-self._m2_history[0][1]>{threshold}:')
    return cases


if __name__ == '__main__':
    study.ROOT = Path('logs/round2_regime_hurdles')
    study.build = build
    study.main()
