"""Transfer a generator preset to a new round with controlled parameter cases.

    uv run python -m experiments.generator.gen_round_fit TAPE --params PARAMS.json \
        --dir OUT --case 'base={"informed":0.0}' --case 'flow={"informed":0.5}' \
        --seeds 501 --family FAMILY.txt --binary rust/target/release/arena-sim --score

Single worker; cached draws require gen_calibrate's source/parameter provenance.
Reports use identical measurements on real and generated tapes: return/spread/
impact statistics, F sign dependence, and causal alignment with prior G prices.
Optional bot scores are calibration diagnostics on the public tape, NOT a new
validation-PnL claim. Use fresh seeds after selecting cases; report each seed.
All candidate bots and generator defaults remain unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import time

os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['OMP_NUM_THREADS'] = '1'
import numpy as np

from arena import qsim_rust
from experiments.generator import gen_calibrate as gc
from experiments.rounds.family_rust import FAMILY
from experiments.filter import filter_placement
from experiments.tape import tape_book
from experiments.filter.filter_placement import read_events

STAT_KEYS = tuple(dict.fromkeys(gc.STAT_KEYS + ('imp<=60', 'imp<=250', 'one_tick_gap')))
BOT_NAMES = ('L8', 'L3', 'L9', 'B1', 'B1F', 'F5')


def digest(path):
    with Path(path).open('rb') as fh:
        return hashlib.file_digest(fh, 'sha256').hexdigest()


def family_scores(path):
    out = {}
    for line in Path(path).read_text().splitlines():
        cols = line.split()
        if len(cols) >= 4 and cols[0] in FAMILY:
            try:
                values = [float(x.replace(',', '')) for x in cols[1:4]]
            except ValueError:
                continue
            name = 'B1F' if cols[0] == 'F3' else cols[0]
            out[name] = dict(zip(('pnl', 'first75', 'last25'), values))
    if not all(k in out for k in BOT_NAMES):
        raise ValueError('family report needs L8,L3,L9,B1,F3,F5 scores')
    return out


def load_cases(specs, path=None, select=None):
    cases = json.loads(Path(path).read_text())['cases'] if path else {}
    for item in specs or []:
        name, value = item.split('=', 1)
        if name in cases:
            raise ValueError(f'duplicate case: {name}')
        cases[name] = json.loads(value)
    if any(not name.replace('_', '').isalnum() or not isinstance(value, dict) for name, value in cases.items()):
        raise ValueError('cases need simple names and JSON option objects')
    if select:
        cases = {name: cases[name] for name in select.split(',')}
    return cases


def flow_stats(data):
    f = np.flatnonzero(data['kind'] == 1)
    if len(f) < 20:
        return {'n': len(f), 'status': 'too few F observations'}
    t = data['time_us'][f]
    s = np.where(data['side'][f] == 0, 1., -1.)
    buy = float(np.mean(s > 0))
    same = float(np.mean(s[1:] == s[:-1]))
    out = dict(n=len(f), rate=len(f) / (float(data['end_us']) / 1e6), buy_share=buy,
               same_side=same, iid_same_side=buy * buy + (1 - buy) ** 2,
               excess_same_side=same - (buy * buy + (1 - buy) ** 2),
               sign_corr1=float(np.corrcoef(s[1:], s[:-1])[0, 1]) if s[1:].std() and s[:-1].std() else None)
    gap = np.diff(t) / 1e6
    out['by_gap_s'] = {}
    for lo, hi in ((0, .02), (.02, .1), (.1, .5), (.5, 2)):
        use = (gap >= lo) & (gap < hi)
        out['by_gap_s'][f'{lo:g}:{hi:g}'] = dict(n=int(use.sum()), same_side=float(np.mean(s[1:][use] == s[:-1][use])) if use.any() else None)
    # Strictly preceding G prices, never F's own price or future observations.
    centre, counts = np.zeros(len(f)), []
    for side in (0, 1):
        g = np.flatnonzero((data['kind'] == 0) & (data['side'] == side))
        gt, gp = data['time_us'][g], data['price'][g]
        ps = np.r_[0., np.cumsum(gp, dtype=float)]
        hi = np.searchsorted(gt, t, side='left')
        lo = np.searchsorted(gt, t - 100_000, side='left')
        n = hi - lo
        centre += .5 * (ps[hi] - ps[lo]) / np.maximum(n, 1)
        counts.append(n)
    mid = (data['bid'][f] + data['ask'][f]) / 2
    delta = centre - mid
    valid = (counts[0] >= 3) & (counts[1] >= 3) & (data['bid'][f] > 0) & (data['ask'][f] > data['bid'][f])
    out['prior_G_alignment'] = {}
    for threshold in (0., .5, 1.):
        use = valid & (np.abs(delta) > threshold)
        out['prior_G_alignment'][str(threshold)] = dict(n=int(use.sum()),
            follow_share=float(np.mean(s[use] * delta[use] > 0)) if use.any() else None)
    out['qualification'] = 'Prior G centre is an observable proxy, not true latent. Same-side excess accounts for unconditional buy imbalance.'
    out['by_1000s'] = []
    for start in range(0, int(data['end_us']), 1_000_000_000):
        pairs = (t[:-1] >= start) & (t[1:] < start + 1_000_000_000)
        aligned = valid & (np.abs(delta) > .5) & (t >= start) & (t < start + 1_000_000_000)
        out['by_1000s'].append(dict(start_s=start / 1e6, n_pairs=int(pairs.sum()),
            same_side=float(np.mean(s[1:][pairs] == s[:-1][pairs])) if pairs.any() else None,
            n_aligned=int(aligned.sum()), follow_share=float(np.mean(s[aligned] * delta[aligned] > 0)) if aligned.any() else None))
    return out


def measure(tape, cache):
    stats = {**gc.tape_stats(tape), **gc.impact_curve(tape)}
    stats['one_tick_gap'] = 1 - stats['one_tick']
    events = read_events(tape, cache)
    return dict(stats=stats, flow=flow_stats(events), sha256=str(events['sha256']))


def distance(measured, reference):
    # Log-ratio statistics; sign dependence is a separate, bounded discrepancy.
    logs = []
    for k in STAT_KEYS:
        a, b = measured['stats'].get(k), reference['stats'].get(k)
        if a is None or b is None or not np.isfinite(a + b) or b <= 0:
            raise ValueError(f'{k}: missing/nonfinite statistic or nonpositive reference')
        # An opposite-sign impact is a bad fit, not an excuse to drop that moment.
        logs.append(np.log(max(a / b, .001)) ** 2)
    out = {'stat_log_rmse': float(np.sqrt(np.mean(logs)))}
    a, b = measured['flow'], reference['flow']
    out['same_side_error'] = a['excess_same_side'] - b['excess_same_side']
    aa, bb = a['prior_G_alignment']['0.5']['follow_share'], b['prior_G_alignment']['0.5']['follow_share']
    out['alignment_error'] = aa - bb if aa is not None and bb is not None else None
    return out


def bot_params():
    out = {name: gc.BOTS[name][1] for name in BOT_NAMES if name != 'F5'}
    out['F5'] = {item.split('=', 1)[0]: float(item.split('=', 1)[1]) for item in shlex.split(FAMILY['F5']) if item != '--set'}
    return out


def score(tape, binary, expected_sha=None):
    expected_sha = expected_sha or digest(binary)
    if digest(binary) != expected_sha:
        raise ValueError('simulator binary changed between runs')
    params = bot_params()
    previous_binary = qsim_rust.BINARY
    try:
        qsim_rust.BINARY = Path(binary).resolve()
        results = qsim_rust.run_batch('ridge_maker', list(params.values()), [Path(tape)], threads=1)
    finally:
        qsim_rust.BINARY = previous_binary
    if digest(binary) != expected_sha:
        raise ValueError('simulator binary changed during the run; do not publish these scores')
    scores = {}
    for name, row in zip(params, results):
        r = row[0]
        if r.get('error') or not np.isfinite(r.get('pnl', np.nan)):
            raise ValueError(f'{name}: invalid simulator result {r}')
        scores[name] = float(r['pnl'])
    return scores


def summarize(rows, reference, target=None):
    """Per-case seed variation; never treat six bots as six independent draws."""
    out = {}
    for name in sorted({r['case'] for r in rows}):
        subset = [r for r in rows if r['case'] == name]
        seeds = [r['seed'] for r in subset]
        if len(set(seeds)) != len(seeds):
            raise ValueError(f'{name}: duplicate seed in aggregation')
        stats = {k: float(np.mean([r['measurement']['stats'][k] for r in subset])) for k in STAT_KEYS}
        result = dict(seeds=seeds, mean_stats=stats,
                      moment_log_rmse=float(np.sqrt(np.mean([np.log(max(stats[k] / reference['stats'][k], .001)) ** 2 for k in STAT_KEYS]))))
        if all('synthetic_truth' in r for r in subset):
            result['volatile_share_per_seed'] = [r['synthetic_truth']['on_share'] for r in subset]
        if all('scores' in r for r in subset):
            sim = {k: [r['scores'][k] for r in subset] for k in BOT_NAMES}
            result['mean_scores'] = {k: float(np.mean(v)) for k, v in sim.items()}
            if target:
                result['score_comparison'] = gc.compare(sim, {k: v['pnl'] for k, v in target.items()})
            result['contrasts'] = {}
            for a, b in (('L8', 'L3'), ('B1', 'L9'), ('B1F', 'B1'), ('F5', 'B1F')):
                differences = np.array(sim[a]) - np.array(sim[b])
                result['contrasts'][a + '-' + b] = dict(per_seed=differences.tolist(),
                    mean=float(differences.mean()),
                    seed_se=float(differences.std(ddof=1) / np.sqrt(len(seeds))) if len(seeds) > 1 else None,
                    target=target[a]['pnl'] - target[b]['pnl'] if target else None)
        out[name] = result
    return out


def run(args):
    start = time.monotonic()
    args.dir.mkdir(parents=True, exist_ok=True)
    if args.flow_only:
        data = read_events(args.tape, args.cache or args.dir / 'real_events.npz')
        report = dict(source=str(args.tape), sha256=str(data['sha256']), flow=flow_stats(data))
        (args.out or args.dir / 'flow_report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
        print(json.dumps(report), flush=True)
        return 0
    params = json.loads(args.params.read_text())
    base = gc.parse_opts(args.opts)
    cases = load_cases(args.case, args.cases, args.select)
    target = family_scores(args.family) if args.family else None
    binary_sha = digest(args.binary) if args.score or args.check_real else None
    reference_file = args.dir / 'reference.json'
    source_id = dict(tape_sha256=digest(args.tape), measurement_sources={Path(p).name: digest(p)
        for p in (__file__, gc.__file__, filter_placement.__file__, tape_book.__file__)})
    if reference_file.exists() and json.loads(reference_file.read_text()).get('identity') == source_id:
        reference = json.loads(reference_file.read_text())['measurement']
    else:
        reference = measure(args.tape, args.dir / 'real_events.npz')
        reference_file.write_text(json.dumps(dict(identity=source_id, measurement=reference), indent=2) + '\n')
    print('real', json.dumps(reference), flush=True)
    if args.score and target and abs(args.seconds - reference['stats']['seconds']) > 2:
        raise ValueError('Scoreboard comparison requires a full-duration draw matching the real tape')
    if args.check_real:
        if not target:
            raise ValueError('--check-real requires --family')
        actual = score(args.tape, args.binary, binary_sha)
        if any(abs(actual[k] - target[k]['pnl']) > 1 for k in BOT_NAMES):
            raise ValueError(f'Simulator/parameter parity failed: {actual}')
        (args.dir / 'real_score_check.json').write_text(json.dumps(dict(scores=actual,
            binary_sha256=binary_sha, params=bot_params()), indent=2) + '\n')
    invocation = json.dumps(dict(cases=cases, seeds=args.seeds, seconds=args.seconds, score=args.score), sort_keys=True)
    report_file = args.out or args.dir / ('report_' + hashlib.sha256(invocation.encode()).hexdigest()[:12] + '.json')
    all_rows = []
    for name, overrides in cases.items():
        fitted = gc.with_opts(params, {**base, **overrides})
        case_dir = args.dir / name
        case_dir.mkdir(exist_ok=True)
        param_path = case_dir / 'params.json'
        if param_path.exists() and json.loads(param_path.read_text()) != fitted:
            raise ValueError(f'{param_path}: parameters differ; choose a new case name')
        param_path.write_text(json.dumps(fitted) + '\n')
        for seed in gc.parse_seeds(args.seeds):
            tape = case_dir / f'seed{seed}.csv'
            job = (fitted, seed, args.seconds, str(tape))
            latent_path = gc._gen_latent(job) if args.latent else None
            if not args.latent:
                gc._gen(job)
            measured = measure(tape, case_dir / f'seed{seed}_events.npz')
            row = dict(case=name, seed=seed, options={**base, **overrides}, measurement=measured,
                       distance=distance(measured, reference))
            if latent_path:
                states = np.loadtxt(latent_path, delimiter=',', skiprows=1, usecols=(2,))
                row['synthetic_truth'] = dict(on_share=float(np.mean(states == 1)), latent_sha256=digest(latent_path))
            if args.score:
                row['scores'] = score(tape, args.binary, binary_sha)
                row['binary_sha256'] = binary_sha
                if target:
                    row['score_comparison'] = gc.compare({k: [v] for k, v in row['scores'].items()},
                                                        {k: v['pnl'] for k, v in target.items()})
            (case_dir / f'seed{seed}.summary.json').write_text(json.dumps(row, indent=2, allow_nan=False) + '\n')
            all_rows.append(row)
            print(name, seed, json.dumps(row['distance']), row.get('scores', {}), flush=True)
            result = dict(source=str(args.tape), source_identity=source_id, seconds=args.seconds,
                          target_scores=target, rows=all_rows, elapsed_s=time.monotonic() - start,
                          summary=summarize(all_rows, reference, target),
                          qualification='Full public-tape calibration. Fresh-seed stability and real holdout checks required before strategy selection.')
            report_file.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print('report', report_file, flush=True)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('tape', type=Path)
    p.add_argument('--params', type=Path)
    p.add_argument('--opts', default='r3_public_after')
    p.add_argument('--dir', type=Path, required=True)
    p.add_argument('--case', action='append', help='NAME=JSON overrides of the latent preset')
    p.add_argument('--cases', type=Path, help='JSON document with a cases object of named option dictionaries')
    p.add_argument('--select', help='Comma-separated subset of names in --cases')
    p.add_argument('--seeds', default='501')
    p.add_argument('--seconds', type=float, default=6000.)
    p.add_argument('--family', type=Path)
    p.add_argument('--binary', type=Path, default=qsim_rust.BINARY)
    p.add_argument('--score', action='store_true')
    p.add_argument('--latent', action='store_true', help='Also save the true latent path and record realized volatile-state occupancy')
    p.add_argument('--check-real', action='store_true', help='Require the executable/parameters to reproduce the family scoreboard')
    p.add_argument('--out', type=Path, help='Report path (default: distinct name per case/seed invocation)')
    p.add_argument('--flow-only', action='store_true', help='Measure observable F persistence and preceding-G alignment only')
    p.add_argument('--cache', type=Path, help='Existing filter_placement event cache for --flow-only')
    args = p.parse_args(argv)
    if args.seconds <= 0:
        p.error('seconds must be positive')
    if not args.flow_only and (not args.params or not (args.case or args.cases)):
        p.error('--params and --case/--cases are required unless --flow-only')
    return run(args)


if __name__ == '__main__':
    raise SystemExit(main())
