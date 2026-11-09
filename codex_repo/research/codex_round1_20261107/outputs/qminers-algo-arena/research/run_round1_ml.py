"""Predeclared policy validation for the trained round-one models."""
import json
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import run_study
from ml_round1_common import DEST, ROOT, WORK, export, file_hash
from run_study import dump


def prepare():
    assert (DEST / 'fit_results.json').exists()
    prefix = WORK / 'round1_first75.csv'
    if not prefix.exists():
        count = 0
        with (ROOT / 'data/round1.csv').open('rb') as source, prefix.open('wb') as target:
            target.write(source.readline())
            for line in source:
                if float(line.split(b',', 1)[0]) > 9000:
                    break
                target.write(line)
                count += 1
        dump(DEST / 'prefix.json', dict(rows=count, end_seconds=9000, sha256=file_hash(prefix)))
    models = json.loads((DEST / 'all_model_parameters.json').read_text())
    entries = []

    def add(name, path, model, kind, target):
        entries.append(dict(name=name, model=model, role=kind, target=target,
            source=str(path), source_sha256=file_hash(path),
            case=[name, str(path), str(prefix), {}, 5]))

    add('f4_reference', ROOT / 'strategies/round1_best.py', 'none', 'reference', 0)
    add('f4_control', export('f4_control', {'ML_KIND':'none'}), 'none', 'control', 0)
    for target in (0.0, 40.0):
        name = f'microprice_t{int(target)}'
        add(name, export(name, {'ML_KIND':'microprice','ML_HISTORY':False}, target), 'microprice', 'simple', target)
    for model, spec in models.items():
        for target in (0.0, 40.0):
            name = f'{model}_t{int(target)}'
            add(name, export(name, spec, target), model, 'ml', target)
    assert len(entries) == 18
    dump(DEST / 'validation_plan.json', dict(entries=entries, scoring='PnL at prefix end minus one-second curve PnL at 6000s. Full book replayed from the beginning. No wind-down at the 9000s prefix boundary.'))
    return entries


def run_case(case):
    run_study.OUT = DEST
    result = run_study.run_case(case)
    curve = np.load(DEST / f'{case[0]}_trace.npz')['curve']
    at = lambda seconds: float(curve[max(0, np.searchsorted(curve[:,0], seconds*1e6, side='right')-1),1])
    result['training_pnl'] = at(6000)
    result['policy_validation_pnl'] = (at(9000) if curve[-1,0] > 9000e6 else result['result']['pnl']) - at(6000)
    result['diagnostic_tail_pnl'] = result['result']['pnl'] - at(9000) if curve[-1,0] > 9000e6 else None
    dump(DEST / f'{case[0]}.json', result)
    return result


def main():
    entries = prepare()
    done, errors = [], []
    with ProcessPoolExecutor(max_workers=min(os.cpu_count() or 1, len(entries))) as pool:
        futures = {pool.submit(run_case, e['case']): e['name'] for e in entries}
        for future in as_completed(futures):
            try:
                result = future.result()
                done.append(result)
                dump(DEST / 'validation_summary.json', done)
                print(json.dumps(dict(completed=len(done),total=len(entries),name=result['name'],
                    validation_pnl=result['policy_validation_pnl'],penalty=result['result']['breach_penalty'],
                    reserved=result['max_reserved_exposure'],cpu_s=result['cpu_seconds'])), flush=True)
            except Exception as error:
                errors.append(dict(name=futures[future],error=repr(error)))
                dump(DEST / 'validation_errors.json', errors)
                print(json.dumps(errors[-1]), flush=True)
    if errors:
        raise RuntimeError(errors)


if __name__ == '__main__':
    main()
