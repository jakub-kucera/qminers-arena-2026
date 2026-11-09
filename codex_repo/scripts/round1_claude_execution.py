"""Tune execution around the supplied causal 595K forecast; charge native fees."""
import json
from pathlib import Path

from scripts import round1_claude_improvements as research
from scripts.benchmark import digest
from scripts.check_submission import check
from scripts.round1_pending_cancel import fix_pending_rejections

ROOT = Path('logs/round1/claude_execution')


def generate():
    base = Path('strategies/round1_claude_595k.py').read_text()
    cases = {'baseline': base}
    for band in (0.06, 0.10, 0.14, 0.22, 0.26, 0.30, 0.40):
        cases[f'band_{band}'] = base.replace('abs(fair-mid) <= 0.18', f'abs(fair-mid) <= {band}')
    for skew in (0.0, 0.05, 0.10, 0.20):
        cases[f'skew_{skew}'] = base.replace('skew = 0.025 *', f'skew = {skew} *')
    for gain in (0.6, 0.8, 1.25, 1.6):
        cases[f'gain_{gain}'] = base.replace('fair = mid + 1.0*prediction', f'fair = mid + {gain}*prediction')
    for width in (0.35, 0.45, 0.60, 0.75):
        cases[f'width_{width}'] = base.replace('floor(fair-0.5)', f'floor(fair-{width})').replace(
            'ceil(fair+0.5)', f'ceil(fair+{width})')
    for release in (0.5, 0.75):
        cases[f'release_{release}'] = base.replace('ceil(r[2]*(1-1.0))', f'ceil(r[2]*(1-{release}))')
    pending = base.replace('if record[3] and not record[4]:', 'if not record[4]:')
    cases['cancel_before_ack'] = fix_pending_rejections(pending)
    for target in (0, 80):
        cases[f'hedge_target_{target}'] = base.replace('abs(self.inventory)-100,', f'abs(self.inventory)-{target},')
    (ROOT/'sources').mkdir(parents=True, exist_ok=True)
    specs = {}
    for name, text in cases.items():
        path = ROOT/'sources'/(name+'.py')
        path.write_text(text)
        assert not check(path), check(path)
        specs[name] = {'source_sha256': digest(path)}
    (ROOT/'specs.json').write_text(json.dumps(specs, indent=2)+'\n')
    return list(cases)


def main():
    research.ROOT = ROOT
    names = generate()
    screen = research.batch(names, 'logs/round1/screening.csv', 'screening', workers=4)
    ranked = sorted(screen, key=lambda n: screen[n]['result']['pnl'], reverse=True)
    full = research.batch(ranked[:5], 'data/round1.csv', 'full', workers=4)
    winner = max(full, key=lambda n: full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner, result=full[winner],
        limitation='Sample tuning on previously evaluated round1.csv, including native penalties.'), indent=2)+'\n')
    print('WINNER EXECUTION', winner, full[winner]['result']['pnl'], flush=True)


if __name__ == '__main__':
    main()
