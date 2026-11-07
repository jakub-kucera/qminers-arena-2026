"""Full replays of capped counts, nearby horizons, and neutral quote thresholds."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT = Path('logs/round1/count_calibration')


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / 'sources').mkdir(exist_ok=True)
    if (ROOT / 'full.json').exists():
        raise SystemExit('Results already exist')
    search_queue.ROOT = ROOT
    base = Path('strategies/round1_queue_545k.py').read_text()
    candidates = {}
    for cap in (1, 5, 10):
        candidates[f'count_cap_{cap}'] = base.replace('weight = min(20,order.quantity)', f'weight = min({cap},order.quantity)')
    for horizon in (75000, 125000, 150000):
        candidates[f'horizon_{horizon}'] = base.replace('HORIZON_US = 100000', f'HORIZON_US = {horizon}')
    for band in (0.09, 0.11, 0.12):
        candidates[f'band_{band}'] = base.replace('abs(fair-mid) <= 0.1', f'abs(fair-mid) <= {band}')
    specs = {}
    for name, source in candidates.items():
        path = ROOT / 'sources' / (name + '.py')
        path.write_text(source)
        assert source != base
        assert not check(path), check(path)
        specs[name] = dict(source_sha256=digest(path))
    (ROOT / 'specs.json').write_text(json.dumps(specs, indent=2) + '\n')
    full = search_queue.batch(specs, 'data/round1.csv', 'full', workers=4)
    winner = max(full, key=lambda n: full[n]['result']['pnl'])
    (ROOT / 'winner.json').write_text(json.dumps(dict(name=winner, result=full[winner],
        parameters=specs[winner], limitation='Tuned on already evaluated round-1 data.'), indent=2) + '\n')
    print('WINNER', winner, full[winner]['result']['pnl'], flush=True)


if __name__ == '__main__':
    main()
