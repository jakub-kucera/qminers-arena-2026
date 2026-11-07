"""Frozen strategy comparison on the newly supplied round-one tape."""
import argparse
import ast
import hashlib
import json
import math
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import run_study
from run_study import ROOT, dump

DEST = ROOT / 'research/round1_results'
FROZEN = DEST / 'frozen_sources'


def source_copy(name, source, session=None):
    raw = source.read_bytes()
    if session is not None:
        text = raw.decode('utf-8')
        lines = text.splitlines(keepends=True)
        matches = [n for n in ast.parse(text).body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == 'SESSION_S' for t in n.targets)]
        assert len(matches) == 1, (source, matches)
        node = matches[0]
        assert node.lineno == node.end_lineno
        lines[node.lineno - 1] = f'SESSION_S = {session!r}\n'
        raw = ''.join(lines).encode('utf-8')
    target = FROZEN / f'{name}.py'
    if target.exists():
        assert target.read_bytes() == raw, f'Frozen source changed: {target}'
    else:
        target.write_bytes(raw)
    return target


def prepare():
    DEST.mkdir(parents=True, exist_ok=True)
    FROZEN.mkdir(exist_ok=True)
    profile = json.loads((DEST / 'dataset.json').read_text())
    data = ROOT / 'data/round1.csv'
    assert hashlib.file_digest(data.open('rb'), 'sha256').hexdigest() == profile['sha256']
    assert profile['backward_timestamps'] == 0
    session = float(math.ceil(profile['last_s']))
    strat = ROOT / 'strategies'
    refs = ROOT / 'research/reference_strategies'
    flow = ROOT.parents[1] / 'work/pasted-review/illustrative_flow06.py'
    specs = [
        ('pasted_passive', strat / 'pasted_passive_v2.py', None, {}, 'primary'),
        ('pasted_flow06', flow, None, {}, 'primary'),
        ('composite_linear', strat / 'composite_max_pnl_v2.py', session, {}, 'primary'),
        ('composite_ensemble', strat / 'composite_best_v2.py', session, {}, 'primary'),
        ('team_F4', refs / 'r0_F4_depletion_guard.py', session, {}, 'primary'),
        ('team_F2', strat / 'team_f2_v2.py', session, {}, 'primary'),
        ('team_F2_cap80', strat / 'team_f2_cap80_v2.py', session, {}, 'primary'),
        ('ridge_maker', strat / 'ridge_maker_v2.py', session, {}, 'primary'),
        ('microprice_maker', strat / 'research_candidate.py', session, {'MODE': 'maker'}, 'primary'),
        ('team_M2', refs / 'r0_M2_runner_safe.py', session, {}, 'primary'),
        ('fixed_trend', strat / 'trend_follower_fixed.py', None, {}, 'primary'),
        ('mean_reversion', strat / 'research_candidate.py', session, {'MODE': 'revert'}, 'primary'),
        ('record', strat / 'research_candidate.py', session, {'MODE': 'record'}, 'no_trade_control'),
        ('old_clock_composite', strat / 'composite_max_pnl_v2.py', None, {}, 'clock_diagnostic'),
        ('old_clock_F4', refs / 'r0_F4_depletion_guard.py', None, {}, 'clock_diagnostic'),
        ('old_clock_F2', strat / 'team_f2_v2.py', None, {}, 'clock_diagnostic'),
    ]
    entries = []
    for name, source, horizon, params, role in specs:
        path = source_copy(name, source, horizon)
        entries.append(dict(name=name, source=str(source), frozen_source=str(path),
            original_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            frozen_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), role=role,
            session_adjustment=horizon, params=params,
            case=[name, str(path), str(data), params, 5]))
    plan = dict(frozen_utc=datetime.now(timezone.utc).isoformat(), entries=entries,
        dataset=profile, session_seconds=session,
        note='No model fitting or strategy parameter search on round1. Session-aware primary candidates change only SESSION_S to the nominal 12,000-second round. Unchanged old-clock controls are separate. Pasted strategies and corrected trend are unchanged.',
        selection='Rank primary cases by full official PnL after penalties; report chronological segments, risk and execution diagnostics. Results are descriptive comparisons on this supplied tape, not a new unseen evaluation after selecting the winner.')
    if (DEST / 'comparison_plan.json').exists():
        old = json.loads((DEST / 'comparison_plan.json').read_text())
        assert old['entries'] == entries
    else:
        dump(DEST / 'comparison_plan.json', plan)
    return entries


def run_one(case):
    run_study.OUT = DEST
    result = run_study.run_case(case)
    trace = np.load(DEST / f'{case[0]}_trace.npz')
    curve = trace['curve']
    trades = trace['trades']
    start, end = curve[0, 0], curve[-1, 0]
    bounds = np.linspace(start, end, 13)
    points = np.searchsorted(curve[:, 0], bounds, side='right') - 1
    vals = curve[np.maximum(points, 0), 1].copy()
    vals[0] = 0
    vals[-1] = result['result']['pnl']
    result['twelve_segment_pnl'] = np.diff(vals).tolist()
    result['positive_segments'] = int(np.sum(np.diff(vals) > 0))
    result['maker_volume'] = float(trades[trades[:, 4] == 1, 3].sum())
    result['taker_volume'] = float(trades[trades[:, 4] == 0, 3].sum())
    result['pnl_per_traded_lot'] = result['result']['pnl'] / max(1, result['result']['traded_volume'])
    result['last_fill_s'] = float(trades[-1, 0] / 1e6) if len(trades) else None
    dump(DEST / f'{case[0]}.json', result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--jobs', type=int, default=os.cpu_count() or 1)
    args = parser.parse_args()
    entries = prepare()
    workers = min(args.jobs, len(entries))
    print(json.dumps(dict(cases=len(entries), workers=workers, logical_cpus=os.cpu_count())), flush=True)
    done, errors = [], []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        tasks = {pool.submit(run_one, entry['case']): entry['name'] for entry in entries}
        for future in as_completed(tasks):
            try:
                result = future.result()
                done.append(result)
                dump(DEST / 'comparison_summary.json', done)
                print(json.dumps(dict(completed=len(done), total=len(entries), name=result['name'],
                    pnl=result['result']['pnl'], penalty=result['result']['breach_penalty'],
                    max_reserved=result['max_reserved_exposure'], cpu_s=result['cpu_seconds'])), flush=True)
            except Exception as error:
                errors.append(dict(name=tasks[future], error=repr(error)))
                dump(DEST / 'comparison_errors.json', errors)
                print(json.dumps(errors[-1]), flush=True)
    if errors:
        raise RuntimeError(errors)


if __name__ == '__main__':
    main()
