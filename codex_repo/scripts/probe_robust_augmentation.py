"""Bounded feature/parameter search on the latest 554347 public-tape model.

The public tapes are previously consumed. The predeclared paired-block screen
limits further selection, but does not create new out-of-sample evidence.
"""
import argparse
import ast
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
from pathlib import Path
import shutil
import subprocess
import time

import numpy as np

from scripts.benchmark import digest
from scripts.check_submission import check
from scripts.probe_depth_advantage import clean_scan, replace_once, run_one


BASELINE = 'clean_554347'
FEATURES = {
    'depth_square': (['depth_imbalance*abs(depth_imbalance)'],
                     'Transfer the previously useful signed depth nonlinearity.'),
    'touch_concentration': (['br/max(1,bd_r)-ar/max(1,ad_r)',
                             'bn/max(1,bd_n)-an/max(1,ad_n)'],
                            'Asymmetry in the fraction of near-depth liquidity at the touch.'),
    'size_mix': (['(br*an-ar*bn)/max(1,br*an+ar*bn)',
                 '(bq*an-aq*bn)/max(1,bq*an+aq*bn)'],
                'Capped and raw mean order-size asymmetries, separate from order counts.'),
    'disagreement': (['robust_imbalance*abs(robust_imbalance-depth_imbalance)',
                      'count_imbalance*abs(count_imbalance-depth_count)'],
                     'Nonlinear touch pressure conditional on disagreement with nearby depth.'),
    'spread_pressure': (['min(4,spread)*robust_imbalance',
                         'min(4,spread)*count_imbalance'],
                        'Spread-conditioned robust volume/count pressure; four-tick saturation.'),
}
PARAMETERS = {
    'memory_240s': ('MODEL_MEMORY_US = 300000000', 'MODEL_MEMORY_US = 240000000'),
    'memory_360s': ('MODEL_MEMORY_US = 300000000', 'MODEL_MEMORY_US = 360000000'),
    'ridge_075': ('0.001 * self._mass', '0.00075 * self._mass'),
    'ridge_150': ('0.001 * self._mass', '0.0015 * self._mass'),
    'horizon_80ms': ('HORIZON_US = 100000', 'HORIZON_US = 80000'),
    'horizon_120ms': ('HORIZON_US = 100000', 'HORIZON_US = 120000'),
}


def generate(source):
    clean = clean_scan(source)
    candidates = {'original_554347': source, BASELINE: clean}
    anchor = 'robust_imbalance*abs(robust_imbalance))'
    for name, (expressions, _) in FEATURES.items():
        text = replace_once(clean, 'FEATURE_COUNT = 15', f'FEATURE_COUNT = {15+len(expressions)}')
        candidates[name] = replace_once(text, anchor,
                                        'robust_imbalance*abs(robust_imbalance),'+','.join(expressions)+')')
    for name, (before, after) in PARAMETERS.items():
        candidates[name] = replace_once(clean, before, after)
    return candidates


def prepare(root, source, data, prefix, transfer):
    root.mkdir(parents=True, exist_ok=True)
    if (root/'protocol.json').exists():
        raise FileExistsError('A protocol already exists; frozen experiments cannot be overwritten')
    sources = root/'sources'
    sources.mkdir(exist_ok=True)
    manifest = {}
    for name, text in generate(source.read_text()).items():
        path = sources/(name+'.py')
        if name == 'original_554347':
            shutil.copyfile(source, path)
        else:
            path.write_text(text, encoding='utf-8', newline='\n')
        ast.parse(text)
        assert not check(path), (name, check(path))
        manifest[name] = {'source': str(path), 'sha256': digest(path),
                          'feature_count': next(n.value.value for n in ast.walk(ast.parse(text))
                                                if isinstance(n, ast.Assign)
                                                and isinstance(n.targets[0], ast.Name)
                                                and n.targets[0].id == 'FEATURE_COUNT')}
    protocol = {
        'created_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'git_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        'upstream_main': subprocess.check_output(['git', 'rev-parse', 'origin/main'], text=True).strip(),
        'baseline_file': str(source), 'baseline_sha256': digest(source),
        'data_sha256': digest(data), 'prefix_sha256': digest(prefix),
        'transfer_sha256': digest(transfer), 'engine_sha256': digest('simulator/simulator.py'),
        'sources': manifest, 'features': FEATURES, 'parameters': PARAMETERS,
        'trial_count': len(FEATURES)+len(PARAMETERS),
        'screen': ('Warm every model from tape start through the existing 6000-second prefix. '
                   'Use exact in-engine marks every 300 seconds and end at 5990 seconds, '
                   'before prefix EOF order draining. Compare each candidate with clean_554347 '
                   'in twenty paired blocks, first ten ending at 3000 seconds. '
                   'Require positive PnL gain in both halves, >=0.5% total gain, >=12/20 '
                   'positive paired blocks, zero penalty and actual/potential exposure <=100. '
                   'Also require a positive one-sided 95% simultaneous max-T lower bound '
                   'across all eleven variants. Use 20000 circular paired-block bootstrap '
                   'draws, block length two (10 minutes), resampling within each half '
                   'after centering each candidate within that half, seed 2026110702. '
                   'This is a conditional selection diagnostic on consumed data, not a '
                   'validated probability of generalization.'),
        'freeze': ('Choose at most one eligible candidate by highest simultaneous lower bound; '
                   'tie-break with fewer features, then name. Freeze its source before full '
                   'round1/transfer/stress evaluation. Do not combine successful changes, '
                   'retune rejected candidates, or choose a runner-up after confirmation failure.'),
        'confirmation': ('Require gains in both 5990-9000 and 9000-end; full gain >=0.5%; '
                         'sample_v2 and 20/50ms stress PnL each >=99% of the corresponding '
                         'baseline; one-second drawdown at normal latency <=125% of baseline; '
                         'zero penalties, actual/potential exposure <=100 in every replay. '
                         'Otherwise retain the baseline and label candidates experimental.'),
        'fallback': ('If no candidate clears screening, retain the cleanup baseline; run a '
                     'single frozen best-lower-bound candidate through confirmation as an '
                     'explicit diagnostic only. It cannot be promoted after failing screening.'),
        'constraints': ('No additional order-book scan, no stateful feature fitting, no absolute '
                        'price/time features. Execution, position limits, inside-quote threshold '
                        'and private-event cache rules remain unchanged. New features are '
                        'bounded, price-translation invariant and reverse sign when sides swap.'),
        'limitation': 'No fresh tape was found. All round1/sample_v2 outcomes were previously consumed.',
    }
    (root/'protocol.json').write_text(json.dumps(protocol, indent=2)+'\n')
    print('FROZEN', protocol['trial_count'], 'trials plus original/clean controls', flush=True)


def bootstrap_gate(gains, seed=2026110702, draws=20000):
    """Rows are chronological blocks; columns are paired candidate gains."""
    gains = np.asarray(gains, dtype=float)
    if gains.ndim != 2 or gains.shape[0] != 20 or not np.isfinite(gains).all():
        raise ValueError('Expected twenty finite chronological blocks per candidate')
    centered = gains.copy()
    for start in (0, 10):
        centered[start:start+10] -= centered[start:start+10].mean(axis=0)
    rng = np.random.default_rng(seed)
    totals = np.zeros((draws, gains.shape[1]))
    for start in (0, 10):
        starts = rng.integers(0, 10, size=(draws, 5))
        indices = (starts[:, :, None]+np.array([0, 1])) % 10 + start
        totals += centered[indices].sum(axis=(1, 2))
    errors = np.maximum(1e-9, totals.std(axis=0, ddof=1))
    critical = float(np.quantile((totals/errors).max(axis=1), 0.95))
    lower = gains.sum(axis=0)-critical*errors
    return lower, errors, critical


def select(root):
    destination = root/'selection.json'
    if destination.exists():
        raise FileExistsError(destination)
    protocol = json.loads((root/'protocol.json').read_text())
    screen = json.loads((root/'screen.json').read_text())
    base, original = screen[BASELINE], screen['original_554347']
    for field in ('result', 'boundary_pnl', 'curve_sha256', 'weights', 'status_counts'):
        assert base[field] == original[field], 'Runtime cleanup changed '+field
    names = list(FEATURES)+list(PARAMETERS)
    deltas = np.array([[block['pnl']-b['pnl'] for block, b in zip(screen[n]['blocks'], base['blocks'])]
                       for n in names]).T
    lower, errors, critical = bootstrap_gate(deltas)
    baseline_total = base['boundary_pnl']['5990000000']
    scores = {}
    for i, name in enumerate(names):
        d = deltas[:, i]
        halves = [float(d[:10].sum()), float(d[10:].sum())]
        gain = float(d.sum())
        row = screen[name]
        eligible = (min(halves) > 0 and gain >= baseline_total*.005
                    and int((d > 0).sum()) >= 12 and lower[i] > 0
                    and row['result']['breach_penalty'] == 0
                    and row['max_abs_inventory'] <= 100 and row['max_potential_inventory'] <= 100)
        scores[name] = {'eligible': bool(eligible), 'gain': gain,
                        'gain_percent': 100*gain/baseline_total, 'half_gains': halves,
                        'positive_blocks': int((d > 0).sum()), 'block_gains': d.tolist(),
                        'simultaneous_lower_bound': float(lower[i]),
                        'bootstrap_standard_error': float(errors[i]),
                        'feature_count': protocol['sources'][name]['feature_count']}
    ranking = sorted(names, key=lambda n: (-scores[n]['simultaneous_lower_bound'],
                                         scores[n]['feature_count'], n))
    eligible = [n for n in ranking if scores[n]['eligible']]
    selected = eligible[0] if eligible else None
    diagnostic = selected or ranking[0]
    frozen = {'selected': selected, 'confirmation_candidate': diagnostic,
              'diagnostic_only': selected is None, 'scores': scores,
              'bootstrap_critical_value': critical, 'bootstrap_draws': 20000,
              'baseline_pnl_at_5990s': baseline_total,
              'source': protocol['sources'][diagnostic],
              'created_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    destination.write_text(json.dumps(frozen, indent=2)+'\n')
    print(json.dumps(frozen, indent=2), flush=True)


def batch(root, data, names, stage, workers, delay):
    protocol = json.loads((root/'protocol.json').read_text())
    boundaries = list(range(300000000, 5700000001, 300000000))+[5990000000]
    if stage.startswith('full'):
        boundaries += list(range(6000000000, 11700000001, 300000000))
        expected = protocol['data_sha256']
    elif stage.startswith('sample'):
        boundaries = list(range(300000000, 5400000001, 300000000))
        expected = protocol['transfer_sha256']
    else:
        expected = protocol['prefix_sha256']
    assert digest(data) == expected
    assert digest('simulator/simulator.py') == protocol['engine_sha256']
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
            print(stage, name, 'pnl', result['result']['pnl'],
                  'CPU', round(result['cpu_seconds'], 1), 'DD', result['max_drawdown_1s'], flush=True)
    (root/(stage+'.json')).write_text(json.dumps(results, indent=2)+'\n')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path('logs/robust_augmentation'))
    p.add_argument('--prepare', action='store_true')
    p.add_argument('--select', action='store_true')
    p.add_argument('--source', type=Path, default=Path('strategies/round1_submission.py'))
    p.add_argument('--data', type=Path)
    p.add_argument('--prefix', type=Path)
    p.add_argument('--transfer', type=Path)
    p.add_argument('--stage', default='screen')
    p.add_argument('--names', nargs='+')
    p.add_argument('--workers', type=int, default=8)
    p.add_argument('--delay', type=int, default=5)
    a = p.parse_args()
    if a.prepare:
        prepare(a.root, a.source, a.data, a.prefix, a.transfer)
    elif a.select:
        select(a.root)
    else:
        names = a.names or list(json.loads((a.root/'protocol.json').read_text())['sources'])
        batch(a.root, a.data, names, a.stage, a.workers, a.delay)


if __name__ == '__main__':
    main()
