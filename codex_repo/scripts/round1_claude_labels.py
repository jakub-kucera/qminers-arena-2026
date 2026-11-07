"""Test smoother causal labels and nonlinear forecast features on the 595K model."""
import json
from pathlib import Path

from scripts import round1_claude_improvements as research
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT = Path('logs/round1/claude_labels')


def nonlinear(base, mode):
    if mode == 'cubes':
        extra = ['flow**3', 'imbalance**3', 'count_imbalance**3', 'robust_imbalance**3',
                 'depth_count**3', 'depth_imbalance**3', 'depth_mid**3']
    else:
        extra = ['count_imbalance*flow*flow', 'count_imbalance*imbalance*imbalance',
                 'count_imbalance*robust_imbalance*robust_imbalance',
                 'flow*count_imbalance*count_imbalance',
                 'imbalance*count_imbalance*count_imbalance',
                 'depth_mid*count_imbalance*count_imbalance',
                 'depth_count*flow*count_imbalance',
                 'robust_imbalance*depth_count*count_imbalance']
    count = 15 + len(extra)
    base = base.replace('FEATURE_COUNT = 15', f'FEATURE_COUNT = {count}')
    return base.replace('robust_imbalance*abs(robust_imbalance))',
                        'robust_imbalance*abs(robust_imbalance),'+','.join(extra)+')')


def main():
    base = Path('strategies/round1_claude_595k.py').read_text()
    cases = {}
    for cap in (0.5, 1.0, 2.0, 5.0):
        cases[f'label_cap_{cap}'] = base.replace('max(-20.0, min(20.0, mid - old_mid))',
                                                f'max(-{cap}, min({cap}, mid - old_mid))')
    for signal in ('count_imbalance', 'robust_imbalance'):
        for gain in (0.25, 0.5):
            cases[f'future_micro_{signal}_{gain}'] = base.replace('self._learn(now,mid)',
                f'self._learn(now,mid+{gain}*spread*{signal})')
    for ridge in (0.0001, 0.0003, 0.003, 0.01):
        cases[f'ridge_{ridge}'] = base.replace('0.001 * self._mass', f'{ridge} * self._mass')
    for mode in ('cubes', 'interactions'):
        for ridge in (0.0001, 0.001):
            cases[f'{mode}_{ridge}'] = nonlinear(base, mode).replace(
                '0.001 * self._mass', f'{ridge} * self._mass')
    (ROOT/'sources').mkdir(parents=True, exist_ok=True)
    specs = {}
    for name, text in cases.items():
        path = ROOT/'sources'/(name+'.py')
        path.write_text(text)
        assert not check(path), check(path)
        specs[name] = {'source_sha256': digest(path)}
    (ROOT/'specs.json').write_text(json.dumps(specs, indent=2)+'\n')
    research.ROOT = ROOT
    screen = research.batch(cases, 'logs/round1/screening.csv', 'screening', workers=3)
    ranked = sorted(screen, key=lambda n: screen[n]['result']['pnl'], reverse=True)
    full = research.batch(ranked[:4], 'data/round1.csv', 'full', workers=3)
    winner = max(full, key=lambda n: full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner, result=full[winner],
        limitation='Sample tuning on previously evaluated data; labels mature causally, fees unchanged.'), indent=2)+'\n')
    print('WINNER LABELS', winner, full[winner]['result']['pnl'], flush=True)


if __name__ == '__main__':
    main()
