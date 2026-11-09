"""Queue-preserving quote thresholds, cancel overlap, and bounded return targets."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT = Path('logs/round1/execution_refine')


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / 'sources').mkdir(exist_ok=True)
    if (ROOT / 'screening.json').exists():
        raise SystemExit('Results already exist')
    search_queue.ROOT = ROOT
    base = Path('strategies/round1_depth_nonlinear_534k.py').read_text().replace(
        'skew = 0.05 *', 'skew = 0.025 *').replace(
        'weight = min(100,order.quantity)', 'weight = min(20,order.quantity)')
    candidates = {}
    candidates['overlap'] = base.replace('        if changing or any(record[4] for oid,record in current):\n            return\n', '')
    for cap in (0.5, 1.0, 2.0):
        candidates[f'target_cap_{cap}'] = base.replace(
            'max(-20.0, min(20.0, mid - old_mid))', f'max(-{cap}, min({cap}, mid - old_mid))')
    for enter, exit in ((0.1, 0.05), (0.12, 0.08), (0.15, 0.1)):
        source = base.replace('        self._previous_touch = None\n',
                              '        self._previous_touch = None\n        self._quote_bias = 0\n', 1)
        source = source.replace('        if abs(fair-mid) <= 0.1:\n            fair = mid', f'''        delta = fair-mid
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
        candidates[f'hysteresis_{enter}_{exit}'] = source
    for delay in (2000, 5000):
        source = base.replace('        self._previous_touch = None\n',
            '        self._previous_touch = None\n        self._wanted = {}\n', 1)
        source = source.replace('    def _quote(self, now, sign, price):\n', f'''    def _quote(self, now, sign, price):
        previous,since = self._wanted.get(sign,(None,now))
        if price != previous:
            since = now
        self._wanted[sign] = (price,since)
        if price is not None and now-since < {delay}:
            return
''')
        candidates[f'confirm_{delay}'] = source
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
