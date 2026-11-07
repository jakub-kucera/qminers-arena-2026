"""Freeze the observed leader, check the exact export, and stress the top two."""
import hashlib
import json
import shutil
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from benchmark_export import peak_working_set
from export_candidates import render, source_check
from round1_study import DEST, run_one
from run_study import ROOT, ExchangeSimulator, load_strategy_from_file, config, dump
import ast


def benchmark(source, expected):
    started, cpu = time.perf_counter(), time.process_time()
    result = ExchangeSimulator(load_strategy_from_file(Path(source)), config()).run(ROOT / 'data/round1.csv')
    assert result.pnl == expected, (result.pnl, expected)
    record = dict(source=source, source_sha256=hashlib.sha256(Path(source).read_bytes()).hexdigest(),
        result=result.model_dump(mode='json'), wall_seconds=time.perf_counter() - started,
        cpu_seconds=time.process_time() - cpu, peak_working_set_bytes=peak_working_set(),
        note='Exact export, official engine, one Python process on Windows. Other stress replays run concurrently; not a remote Linux sandbox measurement.')
    dump(DEST / 'winner_benchmark.json', record)
    print(json.dumps(dict(benchmark_pnl=result.pnl, cpu_s=record['cpu_seconds'], wall_s=record['wall_seconds'])), flush=True)
    return record


def main():
    plan = json.loads((DEST / 'comparison_plan.json').read_text())
    entries = {e['name']: e for e in plan['entries']}
    summary = json.loads((DEST / 'comparison_summary.json').read_text())
    assert len(summary) == len(entries) == 16
    ranked = sorted((r for r in summary if entries[r['name']]['role'] == 'primary'),
                    key=lambda r: r['result']['pnl'], reverse=True)
    winner = ranked[0]
    entry = entries[winner['name']]
    source = Path(entry['frozen_source'])
    text = source.read_text(encoding='utf-8')
    if entry['params']:
        text = render(text, entry['params'])
    tree = ast.parse(text)
    checks = source_check(tree)
    destination = ROOT / 'strategies/round1_best.py'
    if not entry['params']:
        shutil.copyfile(source, destination)
    else:
        destination.write_text(text, encoding='utf-8')
    assert destination.stat().st_size <= 1024 ** 2
    compile(destination.read_text(encoding='utf-8'), str(destination), 'exec')
    decision = dict(selected_case=winner['name'], expected_pnl=winner['result']['pnl'],
        export=str(destination), sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),
        bytes=destination.stat().st_size, source_checks=checks,
        change='SESSION_S = 12000.0; all other F4 strategy logic and parameters unchanged.',
        ranking_basis='Highest full supplied-round PnL among 12 frozen trading candidates; no retraining.',
        stress_candidates=[r['name'] for r in ranked[:2]])
    dump(DEST / 'selection.json', decision)
    tasks = []
    for result in ranked[:2]:
        e = entries[result['name']]
        for delay in (20, 50):
            tasks.append([f'{result["name"]}_delay{delay}', e['frozen_source'],
                          str(ROOT / 'data/round1.csv'), e['params'], delay])
    dump(DEST / 'stress_plan.json', tasks)
    completed = []
    with ProcessPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(run_one, case): case[0] for case in tasks}
        bench = pool.submit(benchmark, str(destination), winner['result']['pnl'])
        for future in as_completed(futures):
            completed.append(future.result())
            dump(DEST / 'stress_summary.json', completed)
        bench.result()


if __name__ == '__main__':
    main()
