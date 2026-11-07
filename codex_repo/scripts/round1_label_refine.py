"""Causal future quote-derived value targets and denser observation schedules."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT = Path('logs/round1/label_refine')


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / 'sources').mkdir(exist_ok=True)
    if (ROOT / 'screening.json').exists():
        raise SystemExit('Results already exist')
    search_queue.ROOT = ROOT
    base = Path('strategies/round1_depth_nonlinear_534k.py').read_text()
    candidates = {}
    for feature in ('count_imbalance', 'robust_imbalance'):
        for alpha in (0.25, 0.5):
            name = f'future_{feature}_{alpha}'
            candidates[name] = base.replace('        self._learn(now,mid)\n',
                f'        self._learn(now,mid+{alpha}*spread*{feature})\n')
    for interval in (20000, 50000):
        for scale_ridge in (False, True):
            name = f'observation_{interval}_scale_{scale_ridge}'
            source = base.replace('OBSERVATION_INTERVAL_US = 100000', f'OBSERVATION_INTERVAL_US = {interval}')
            if scale_ridge:
                scale = 100000 / interval
                source = source.replace('max(10.0, 0.001 * self._mass)', f'max({10*scale}, 0.001 * self._mass)')
            candidates[name] = source
    specs = {}
    for name, source in candidates.items():
        path = ROOT / 'sources' / (name + '.py')
        path.write_text(source)
        assert not check(path), check(path)
        specs[name] = dict(source_sha256=digest(path))
    (ROOT / 'specs.json').write_text(json.dumps(specs, indent=2) + '\n')
    screened = search_queue.batch(specs, 'logs/round1/screening.csv', 'screening')
    finalists = sorted(screened, key=lambda n: screened[n]['result']['pnl'], reverse=True)[:3]
    finalists = [n for n in finalists if screened[n]['result']['pnl'] > 155000]
    full = search_queue.batch(finalists, 'data/round1.csv', 'full') if finalists else {}
    winner = max(full, key=lambda n: full[n]['result']['pnl']) if full else None
    (ROOT / 'winner.json').write_text(json.dumps(dict(name=winner, result=full.get(winner),
        parameters=specs.get(winner), limitation='Tuned on already evaluated round-1 data.'), indent=2) + '\n')
    print('WINNER', winner, full[winner]['result']['pnl'] if winner else 'no prefix improvement', flush=True)


if __name__ == '__main__':
    main()
