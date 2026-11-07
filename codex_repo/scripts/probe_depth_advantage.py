"""Bounded, predeclared research on the supplied causal depth market maker.

Run from the repository root. Sources, protocol, hashes, exact boundary marks,
and all outcomes are retained. No model or source is selected on the final tail.
The public tapes have already been consumed; these are robustness diagnostics.
"""
import argparse
import ast
from collections import deque
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import time

from scripts.benchmark import digest
from scripts.check_submission import check
from scripts.search_passive import CandidateEngine
from simulator.main import load_strategy_from_file
from simulator.simulator import SimulationConfig


FEATURES = ('flow,max(-5,min(5,self._fast_mid-self._slow_mid)),imbalance,\n'
            '                  ofi,spread*imbalance,flow*abs(flow),imbalance*abs(imbalance),'
            'ofi*abs(ofi),count_imbalance,robust_imbalance,depth_count,depth_imbalance,depth_mid')


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('Expected exactly one source anchor: ' + old[:100])
    return source.replace(old, new, 1)


def clean_scan(source):
    """Remove unused queue tracking without changing the market-only touch."""
    start = source.index('        # Feed order is price-time order:')
    end = source.index('        if bid is None or ask is None or bid >= ask:', start)
    scan = '''        for order in snapshot.bids:
            if order.owner != 'market':
                continue
            if bid is None:
                bid = order.price
            if order.price != bid:
                break
            bq += order.quantity
        for order in snapshot.asks:
            if order.owner != 'market':
                continue
            if ask is None:
                ask = order.price
            if order.price != ask:
                break
            aq += order.quantity
'''
    return source[:start] + scan + source[end:]


def feature_variant(source, expression, count):
    source = replace_once(source, 'FEATURE_COUNT = 13', f'FEATURE_COUNT = {count}')
    return replace_once(source, FEATURES, expression)


def blend_variant(source, memory_us=300000000, horizon_us=100000):
    """Add a second causal model; preserve primary-model math exactly."""
    state_names = ('observations', 'last_observation_us', 'last_fit_us', 'last_label_us',
                   'labels', 'mass', 'xx', 'xy', 'weights')
    def auxiliary(text):
        for name in state_names:
            text = text.replace('self._' + name, 'self._aux_' + name)
        return text
    start = source.index('        self._observations =')
    end = source.index('        self._fast_mid =', start)
    source = source[:end] + auxiliary(source[start:end]) + source[end:]
    start = source.index('    def _learn(')
    end = source.index('    def _cancel(', start)
    learner = auxiliary(source[start:end]).replace('def _learn(', 'def _learn_aux(')
    learner = learner.replace('self.HORIZON_US', str(horizon_us)).replace('self.MODEL_MEMORY_US', str(memory_us))
    source = source[:end] + learner + source[end:]
    source = replace_once(source, '        self._learn(now,mid)',
                          '        self._learn(now,mid)\n        self._learn_aux(now,mid)')
    source = replace_once(source, '            self._observations.clear()',
                          '            self._observations.clear()\n            self._aux_observations.clear()')
    source = replace_once(source, '            self._observations.append((now,mid,features))',
                          '            self._observations.append((now,mid,features))\n'
                          '            self._aux_observations.append((now,mid,features))')
    source = replace_once(source, '        fair = mid +',
                          '        if self._aux_labels >= self.MIN_LABELS:\n'
                          '            auxiliary_prediction = max(-2.0,min(2.0,sum(w*x for w,x in zip(self._aux_weights,features))))\n'
                          '            prediction = 0.75*prediction + 0.25*auxiliary_prediction\n'
                          '        fair = mid +')
    return source


def prepare(attachment, root, data, prefix):
    root.mkdir(parents=True, exist_ok=True)
    if (root/'protocol.json').exists():
        raise FileExistsError('Refusing to overwrite a frozen protocol')
    sources = root/'sources'
    sources.mkdir(exist_ok=True)
    original = attachment.read_text(encoding='utf-8-sig')
    base = clean_scan(original)
    five = FEATURES.split(',flow*abs(flow)')[0]
    eight = FEATURES.split(',count_imbalance')[0]
    variants = {
        'supplied_13': original,
        'clean_13': base,
        'core_5': feature_variant(base, five, 5),
        'nonlinear_8': feature_variant(base, eight, 8),
        'depth_linear_10': feature_variant(base, five + ',count_imbalance,robust_imbalance,depth_count,depth_imbalance,depth_mid', 10),
        'depth_nonlinear_16': feature_variant(base, FEATURES + ',count_imbalance*abs(count_imbalance),robust_imbalance*abs(robust_imbalance),depth_imbalance*abs(depth_imbalance)', 16),
        'memory_blend': blend_variant(base, memory_us=60000000),
        'horizon_blend': blend_variant(base, horizon_us=500000),
    }
    lag = replace_once(base, '        self._last_action =',
                       '        self._depth_history = deque(maxlen=64)\n        self._last_action =')
    lag = replace_once(lag, '        features=(', '''        while len(self._depth_history) > 1 and self._depth_history[1][0] <= now-100000:
            self._depth_history.popleft()
        lag_touch = lag_depth = 0.0
        if self._depth_history and 100000 <= now-self._depth_history[0][0] <= 1100000:
            lag_touch = robust_imbalance-self._depth_history[0][1]
            lag_depth = depth_imbalance-self._depth_history[0][2]
        features=(''')
    lag = replace_once(lag, '            self._observations.append((now,mid,features))',
                       '            self._depth_history.append((now,robust_imbalance,depth_imbalance))\n'
                       '            self._observations.append((now,mid,features))')
    lag = replace_once(lag, '            self._observations.clear()',
                       '            self._observations.clear()\n            self._depth_history.clear()')
    variants['depth_changes_15'] = feature_variant(lag, FEATURES + ',lag_touch,lag_depth', 15)
    manifest = {}
    for name, source in variants.items():
        path = sources/(name+'.py')
        if name == 'supplied_13':
            path.write_bytes(attachment.read_bytes())
        else:
            path.write_text(source, encoding='utf-8', newline='\n')
        ast.parse(source)
        assert not check(path), (name, check(path))
        manifest[name] = {'source': str(path), 'sha256': digest(path)}
    protocol = {
        'attachment_sha256': digest(attachment),
        'round1_sha256': digest(data), 'prefix_sha256': digest(prefix),
        'engine_sha256': digest('simulator/simulator.py'),
        'models_sha256': digest('simulator/models.py'),
        'sources': manifest,
        'ablation_only': ['core_5', 'nonlinear_8', 'depth_linear_10'],
        'extensions': ['depth_nonlinear_16', 'memory_blend', 'horizon_blend', 'depth_changes_15'],
        'selection': ('Run every variant through the existing 6000-second prefix from an empty book. '
                      'Use exact pre-terminal marks at 3000 and 5990 seconds. Clean baseline must exactly '
                      'match supplied baseline. Extensions must improve both halves, gain at least 1% '
                      'through 5990 seconds, win at least 6/10 chronological blocks, incur zero penalty '
                      'and keep actual/submitted potential exposure <=100. Rank eligible by total gain. '
                      'Freeze best and second eligible (if any) before running full round1 and sample_v2. '
                      'Require gains in both 5990-9000 and 9000-end, and no more than 2% sample_v2 loss. '
                      'Run baseline and selected extension at 20 and 50 ms latency. If none pass, retain '
                      'the supplied model with runtime-only cleanup. No automatic stacking of changes.'),
        'limit': 'Previously consumed public tapes; no fresh holdout or private leaderboard claim.',
        'created_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }
    (root/'protocol.json').write_text(json.dumps(protocol, indent=2)+'\n')
    print('FROZEN', len(variants), 'sources', flush=True)


class ProbeEngine(CandidateEngine):
    """Read-only boundary marks; no change to matching or the strategy feed."""
    def __init__(self, strategy, config, boundaries):
        super().__init__(strategy, config)
        self._probe_boundaries = deque(sorted(boundaries))
        self.boundary_pnl = {}

    def _advance_time(self, timestamp_us):
        while self._probe_boundaries and self._probe_boundaries[0] <= timestamp_us:
            boundary = self._probe_boundaries.popleft()
            if self.current_ts_us < boundary:
                super()._advance_time(boundary)
                self.boundary_pnl[str(boundary)] = self._mark_to_market_pnl()
        super()._advance_time(timestamp_us)


def run_one(source, data, destination, delay=5, boundaries=()):
    destination = Path(destination)
    if (destination/'evaluation.json').exists():
        raise FileExistsError(destination)
    strategy = load_strategy_from_file(Path(source))
    config = SimulationConfig(max_position=100, max_potential_position=1000,
                              position_breach_penalty_per_second=10000,
                              order_accept_delay_ms=delay, public_depth=20)
    engine = ProbeEngine(strategy, config, boundaries)
    started = time.perf_counter()
    cpu_started = time.process_time()
    result = engine.run(Path(data))
    wall = time.perf_counter()-started
    cpu = time.process_time()-cpu_started
    curve = engine.pnl_curve(result.pnl)
    peak = dd = 0
    for _, value in curve:
        peak = max(peak, value)
        dd = max(dd, peak-value)
    blocks, last = [], 0
    for key, value in engine.boundary_pnl.items():
        blocks.append({'end_us': int(key), 'pnl': value-last})
        last = value
    record = {
        'source_sha256': digest(source), 'data_sha256': digest(data),
        'result': result.model_dump(mode='json'), 'boundary_pnl': engine.boundary_pnl,
        'blocks': blocks, 'max_drawdown_1s': dd, 'runtime_seconds': wall,
        'cpu_seconds': cpu, 'max_abs_inventory': engine.max_abs_inventory,
        'max_potential_inventory': engine.max_potential_inventory,
        'submissions': engine._user_order_seq, 'status_counts': dict(engine.status_counts),
        'labels': strategy._labels, 'weights': strategy._weights,
        'config': config.model_dump(mode='json'),
        'curve_sha256': hashlib.sha256(json.dumps(curve).encode()).hexdigest(),
    }
    assert result.breach_penalty == 0
    assert engine.max_abs_inventory <= 100 and engine.max_potential_inventory <= 100
    assert len(engine.boundary_pnl) == len(boundaries), 'A requested boundary was not reached'
    destination.mkdir(parents=True, exist_ok=True)
    (destination/'evaluation.json').write_text(json.dumps(record, indent=2)+'\n')
    (destination/'pnl.json').write_text(json.dumps(curve)+'\n')
    return record


def batch(root, data, names, stage, workers, delay=5):
    protocol = json.loads((root/'protocol.json').read_text())
    boundaries = list(range(600000000, 5400000001, 600000000)) + [5990000000]
    if stage.startswith('full'):
        boundaries += [6000000000, 7200000000, 8400000000, 9000000000, 9600000000, 10800000000]
    elif stage.startswith('sample'):
        boundaries = list(range(600000000, 5400000001, 600000000))
    results = {}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        jobs = {}
        for name in names:
            source = Path(protocol['sources'][name]['source'])
            assert digest(source) == protocol['sources'][name]['sha256']
            jobs[pool.submit(run_one, source, data, root/stage/name, delay, boundaries)] = name
        for future in as_completed(jobs):
            name = jobs[future]
            result = future.result()
            results[name] = result
            print(stage, name, 'PnL', result['result']['pnl'], 'CPU', round(result['cpu_seconds'], 1),
                  'DD', result['max_drawdown_1s'], flush=True)
    (root/(stage+'.json')).write_text(json.dumps(results, indent=2)+'\n')


def select(root):
    """Apply the declared gates, then freeze names before any extension tail run."""
    path = root/'selection.json'
    if path.exists():
        raise FileExistsError(path)
    protocol = json.loads((root/'protocol.json').read_text())
    screen = json.loads((root/'screen.json').read_text())
    supplied, baseline = screen['supplied_13'], screen['clean_13']
    for field in ('result', 'boundary_pnl', 'curve_sha256', 'weights', 'status_counts'):
        assert supplied[field] == baseline[field], 'Cleanup changed '+field
    total = baseline['boundary_pnl']['5990000000']
    first = baseline['boundary_pnl']['3000000000']
    baseline_blocks = [b['pnl'] for b in baseline['blocks']]
    scores = {}
    for name in protocol['extensions']:
        row = screen[name]
        value = row['boundary_pnl']['5990000000']
        early = row['boundary_pnl']['3000000000']
        deltas = [b['pnl']-a for b, a in zip(row['blocks'], baseline_blocks)]
        gains = [early-first, (value-early)-(total-first)]
        eligible = (all(g > 0 for g in gains) and value >= total*1.01
                    and sum(d > 0 for d in deltas) >= 6
                    and row['result']['breach_penalty'] == 0
                    and row['max_abs_inventory'] <= 100
                    and row['max_potential_inventory'] <= 100)
        scores[name] = {'eligible': eligible, 'gain': value-total,
                        'gain_percent': 100*(value/total-1), 'half_gains': gains,
                        'block_gains': deltas, 'positive_blocks': sum(d > 0 for d in deltas)}
    eligible = sorted((n for n, r in scores.items() if r['eligible']),
                      key=lambda n: scores[n]['gain'], reverse=True)
    frozen = {'finalists': eligible[:2], 'scores': scores,
              'baseline_pnl_at_5990s': total, 'cleanup_exact_match': True,
              'sources': {n: protocol['sources'][n] for n in eligible[:2]},
              'created_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    path.write_text(json.dumps(frozen, indent=2)+'\n')
    print(json.dumps(frozen, indent=2), flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--prepare', action='store_true')
    p.add_argument('--select', action='store_true')
    p.add_argument('--attachment', type=Path)
    p.add_argument('--data', type=Path)
    p.add_argument('--prefix', type=Path)
    p.add_argument('--stage', default='screen')
    p.add_argument('--names', nargs='+')
    p.add_argument('--workers', type=int, default=6)
    p.add_argument('--delay', type=int, default=5)
    a = p.parse_args()
    if a.prepare:
        prepare(a.attachment, a.root, a.data, a.prefix)
    elif a.select:
        select(a.root)
    else:
        names = a.names or list(json.loads((a.root/'protocol.json').read_text())['sources'])
        batch(a.root, a.data, names, a.stage, a.workers, a.delay)


if __name__ == '__main__':
    main()
