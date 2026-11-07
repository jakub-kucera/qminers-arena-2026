"""Combine causal 20ms learning, reserved cancel overlap, and selective quoting."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT = Path('logs/round1/final_policy')


def hysteresis(base, enter, exit):
    source = base.replace('        self._previous_touch = None\n',
                          '        self._previous_touch = None\n        self._quote_bias = 0\n', 1)
    old = '        if abs(fair-mid) <= 0.1:\n            fair = mid'
    assert old in source
    return source.replace(old, f'''        delta = fair-mid
        if abs(delta) <= {exit}:
            self._quote_bias = 0
        elif delta >= {enter}:
            self._quote_bias = 1
        elif delta <= -{enter}:
            self._quote_bias = -1
        elif delta*self._quote_bias <= 0:
            self._quote_bias = 0
        if self._quote_bias == 0:
            fair = mid''')


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / 'sources').mkdir(exist_ok=True)
    if (ROOT / 'full.json').exists():
        raise SystemExit('Results already exist')
    search_queue.ROOT = ROOT
    base = Path('strategies/round1_queue_545k.py').read_text()
    candidates = {}
    for enter, exit in ((0.11, 0.07), (0.12, 0.08), (0.13, 0.09), (0.12, 0.06), (0.12, 0.1)):
        candidates[f'hysteresis_{enter}_{exit}'] = hysteresis(base, enter, exit)
    for threshold in (0.1, 0.25, 0.5):
        source = base.replace('        # Withdraw the side', f'''        if spread >= 2:
            if prediction-skew > {threshold}:
                buy = min(ask-1,bid+1)
            elif prediction-skew < -{threshold}:
                sell = max(bid+1,ask-1)
        # Withdraw the side''')
        candidates[f'inside_{threshold}'] = source
        if threshold == 0.25:
            candidates['inside_0.25_hysteresis'] = hysteresis(source, 0.12, 0.08)
    specs = {}
    for name, source in candidates.items():
        path = ROOT / 'sources' / (name + '.py')
        path.write_text(source)
        assert not check(path), check(path)
        specs[name] = dict(source_sha256=digest(path))
    (ROOT / 'specs.json').write_text(json.dumps(specs, indent=2) + '\n')
    full = search_queue.batch(specs, 'data/round1.csv', 'full', workers=6)
    winner = max(full, key=lambda n: full[n]['result']['pnl'])
    (ROOT / 'winner.json').write_text(json.dumps(dict(name=winner, result=full[winner],
        parameters=specs[winner], limitation='Tuned on already evaluated round-1 data.'), indent=2) + '\n')
    print('WINNER', winner, full[winner]['result']['pnl'], flush=True)


if __name__ == '__main__':
    main()
