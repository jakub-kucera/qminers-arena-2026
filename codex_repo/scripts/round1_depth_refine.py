"""Refine robust queue predictors; all scores are tuning on consumed round-1 data."""
import json
from pathlib import Path

from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT = Path('logs/round1/depth_refine')


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / 'sources').mkdir(exist_ok=True)
    if (ROOT / 'screening.json').exists():
        raise SystemExit('Results already exist')
    search_queue.ROOT = ROOT
    base = Path('strategies/round1_depth_524k.py').read_text()
    candidates = {}
    for cap in (20, 50, 200, 1000):
        candidates[f'cap_{cap}'] = base.replace('weight = min(100,order.quantity)', f'weight = min({cap},order.quantity)')
    for ticks in (0, 1, 4, 9):
        candidates[f'distance_{ticks}'] = base.replace('distance > 2:', f'distance > {ticks}:')
    for horizon in (20000, 50000, 200000, 500000):
        candidates[f'horizon_{horizon}'] = base.replace('HORIZON_US = 100000', f'HORIZON_US = {horizon}')
    for memory in (60000000, 900000000):
        candidates[f'memory_{memory}'] = base.replace('MODEL_MEMORY_US = 300000000', f'MODEL_MEMORY_US = {memory}')
    for ridge in (0.005, 0.02):
        candidates[f'ridge_{ridge}'] = base.replace('0.001 * self._mass', f'{ridge} * self._mass')
    for name, extra in {
        'touch_nonlinear': ',count_imbalance*abs(count_imbalance),robust_imbalance*abs(robust_imbalance)',
        'cross_features': ',robust_imbalance*abs(flow),flow*abs(robust_imbalance),count_imbalance*abs(ofi)',
        'depth_nonlinear': ',depth_count*abs(depth_count),depth_imbalance*abs(depth_imbalance)',
    }.items():
        count = 13 + extra.count(',')
        candidates[name] = base.replace('FEATURE_COUNT = 13', f'FEATURE_COUNT = {count}').replace('depth_imbalance,depth_mid)', 'depth_imbalance,depth_mid' + extra + ')')
    # Join the simpler touch-only model with signed nonlinear queue features.
    touch = base.replace('FEATURE_COUNT = 13', 'FEATURE_COUNT = 12').replace(
        ',depth_count,depth_imbalance,depth_mid)',
        ',count_imbalance*abs(count_imbalance),robust_imbalance*abs(robust_imbalance))')
    candidates['touch_nonlinear_only'] = touch
    specs = {}
    for name, source in candidates.items():
        path = ROOT / 'sources' / (name + '.py')
        path.write_text(source)
        assert not check(path), check(path)
        specs[name] = {'source_sha256': digest(path)}
    (ROOT / 'specs.json').write_text(json.dumps(specs, indent=2) + '\n')
    screened = search_queue.batch(specs, 'logs/round1/screening.csv', 'screening')
    finalists = sorted(screened, key=lambda n: screened[n]['result']['pnl'], reverse=True)[:4]
    full = search_queue.batch(finalists, 'data/round1.csv', 'full')
    winner = max(full, key=lambda n: full[n]['result']['pnl'])
    (ROOT / 'winner.json').write_text(json.dumps({
        'name': winner, 'result': full[winner], 'parameters': specs[winner],
        'limitation': 'Further tuning on already evaluated round-1 data.',
    }, indent=2) + '\n')
    print('WINNER', winner, full[winner]['result']['pnl'], flush=True)


if __name__ == '__main__':
    main()
