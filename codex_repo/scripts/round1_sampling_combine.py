"""Combine denser causal labels with quote reservation and policy refinements."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT = Path('logs/round1/sampling_combine')


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / 'sources').mkdir(exist_ok=True)
    if (ROOT / 'full.json').exists():
        raise SystemExit('Results already exist')
    search_queue.ROOT = ROOT
    base = Path('strategies/round1_depth_nonlinear_534k.py').read_text().replace(
        'skew = 0.05 *', 'skew = 0.025 *').replace(
        'weight = min(100,order.quantity)', 'weight = min(20,order.quantity)')
    specs = {}
    for interval, overlap, cap in [(20000, False, 20), (20000, True, 20),
                                  (50000, False, 20), (50000, True, 20),
                                  (20000, True, 1)]:
        name = f'interval_{interval}_overlap_{overlap}_target_{cap}'
        source = base.replace('OBSERVATION_INTERVAL_US = 100000', f'OBSERVATION_INTERVAL_US = {interval}')
        if overlap:
            source = source.replace('        if changing or any(record[4] for oid,record in current):\n            return\n', '')
        if cap != 20:
            source = source.replace('max(-20.0, min(20.0, mid - old_mid))', f'max(-{cap}.0, min({cap}.0, mid - old_mid))')
        path = ROOT / 'sources' / (name + '.py')
        path.write_text(source)
        assert not check(path), check(path)
        specs[name] = dict(interval_us=interval, overlap=overlap, response_cap=cap, source_sha256=digest(path))
    (ROOT / 'specs.json').write_text(json.dumps(specs, indent=2) + '\n')
    full = search_queue.batch(specs, 'data/round1.csv', 'full')
    winner = max(full, key=lambda n: full[n]['result']['pnl'])
    (ROOT / 'winner.json').write_text(json.dumps(dict(name=winner, result=full[winner],
        parameters=specs[winner], limitation='Tuned on already evaluated round-1 data.'), indent=2) + '\n')
    print('WINNER', winner, full[winner]['result']['pnl'], flush=True)


if __name__ == '__main__':
    main()
