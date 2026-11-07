"""Freeze a validation-selected ML candidate before reading its final-quarter result."""
import ast
import json
import shutil
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from benchmark_export import peak_working_set
from export_candidates import source_check
from ml_round1_common import DEST, ROOT, file_hash
from run_round1_ml import run_case
from run_study import ExchangeSimulator, config, dump, load_strategy_from_file


def benchmark(path):
    wall, cpu = time.perf_counter(), time.process_time()
    result = ExchangeSimulator(load_strategy_from_file(Path(path)), config()).run(ROOT / 'data/round1.csv')
    record = dict(source=path, sha256=file_hash(path), result=result.model_dump(mode='json'),
        wall_seconds=time.perf_counter() - wall, cpu_seconds=time.process_time() - cpu,
        peak_working_set_bytes=peak_working_set(),
        note='One Windows Python process using the official loader/engine; other final comparisons run concurrently. No CatBoost or sklearn runtime dependency.')
    dump(DEST / 'candidate_benchmark.json', record)
    print(json.dumps(dict(benchmark_pnl=result.pnl, cpu_s=record['cpu_seconds'])), flush=True)
    return record


def main():
    plan = json.loads((DEST / 'validation_plan.json').read_text())
    entries = {e['name']: e for e in plan['entries']}
    results = json.loads((DEST / 'validation_summary.json').read_text())
    assert len(results) == len(entries) == 18
    by_name = {r['name']: r for r in results}
    reference, control = by_name['f4_reference'], by_name['f4_control']
    assert reference['result'] == control['result'], 'F4 control does not reproduce the actual F4 baseline.'
    eligible = [r for r in results if r['result']['breach_penalty'] == 0 and r['max_reserved_exposure'] <= 100]
    winner = max((r for r in eligible if entries[r['name']]['role'] == 'ml'), key=lambda r:r['policy_validation_pnl'])
    simple = max((r for r in eligible if entries[r['name']]['role'] in ('reference','simple')), key=lambda r:r['policy_validation_pnl'])
    source = Path(entries[winner['name']]['source'])
    assert file_hash(source) == entries[winner['name']]['source_sha256']
    exported = ROOT / 'strategies/round1_ml_candidate.py'
    shutil.copyfile(source, exported)
    failures, warnings = source_check(ast.parse(exported.read_text(encoding='utf-8')))
    assert not failures and exported.stat().st_size < 1024 ** 2
    decision = dict(frozen_utc=datetime.now(timezone.utc).isoformat(),
        selected_case=winner['name'], model=entries[winner['name']]['model'],
        validation_pnl=winner['policy_validation_pnl'], f4_validation_pnl=reference['policy_validation_pnl'],
        strongest_simple_case=simple['name'], strongest_simple_validation=simple['policy_validation_pnl'],
        export=str(exported), sha256=file_hash(exported), bytes=exported.stat().st_size,
        promotion_gate='ML must outperform F4 in both validation and reused final-quarter diagnostics, remain penalty-free with reserved exposure <=100, and fit source/runtime limits. Otherwise retain F4; no parameter change after this freeze.',
        evidence_limit='The diagnostic quarter was inspected previously. This is not an untouched independent holdout.')
    dump(DEST / 'selection.json', decision)
    tasks = [['final_ml', str(exported), str(ROOT / 'data/round1.csv'), {}, 5]]
    if simple['name'] != 'f4_reference':
        tasks.append(['final_simple',entries[simple['name']]['source'],str(ROOT/'data/round1.csv'),{},5])
    dump(DEST / 'final_plan.json', tasks)
    completed = []
    with ProcessPoolExecutor(max_workers=len(tasks)+1) as pool:
        futures = {pool.submit(run_case, case):case[0] for case in tasks}
        bench = pool.submit(benchmark, str(exported))
        for future in as_completed(futures):
            completed.append(future.result())
            dump(DEST / 'final_summary.json', completed)
        plain = bench.result()
    ml = next(r for r in completed if r['name'] == 'final_ml')
    assert ml['result'] == plain['result']
    f4 = json.loads((ROOT / 'research/round1_results/team_F4.json').read_text())
    curve = np.load(ROOT / 'research/round1_results/team_F4_trace.npz')['curve']
    at9000 = float(curve[np.searchsorted(curve[:,0],9000e6,side='right')-1,1])
    f4_tail = f4['result']['pnl'] - at9000
    promote = (winner['policy_validation_pnl'] > reference['policy_validation_pnl']
        and ml['diagnostic_tail_pnl'] > f4_tail and ml['result']['breach_penalty']==0
        and ml['max_reserved_exposure']<=100 and plain['cpu_seconds']<900)
    outcome = dict(promote_ml=promote, candidate=decision, candidate_full=ml['result']['pnl'],
        candidate_diagnostic_tail=ml['diagnostic_tail_pnl'], f4_full=f4['result']['pnl'],
        f4_diagnostic_tail=f4_tail, recommendation='ML candidate' if promote else 'Keep F4',
        note='Promotion is a local exploratory recommendation only; server execution and unseen-round performance are untested.')
    dump(DEST / 'outcome.json', outcome)
    print(json.dumps(outcome,indent=2), flush=True)


if __name__ == '__main__':
    main()
