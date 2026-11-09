"""Stress the unchanged highest-public-PnL export; no fitting or selection."""
from concurrent.futures import ProcessPoolExecutor, as_completed

from run_study import ROOT, dump
from composite_study import DEST
from stress_composite import run


def main():
    source = str(ROOT / 'strategies/composite_max_pnl_v2.py')
    data = str(ROOT / 'data/sample_v2.csv')
    old = str(ROOT / 'data/sample.csv')
    cases = [
        ['max_pnl_20ms', source, data, {}, 20],
        ['max_pnl_50ms', source, data, {}, 50],
        ['cross_original_max_pnl', source, old, {'SESSION_S': 3599.000003}, 5],
    ]
    dump(DEST / 'max_pnl_stress_plan.json', cases)
    done = []
    with ProcessPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, case) for case in cases]
        for future in as_completed(futures):
            result = future.result()
            done.append(result)
            dump(DEST / 'max_pnl_stress_summary.json', done)
            print(result['name'], result['result']['pnl'],
                  result['result']['breach_penalty'], flush=True)


if __name__ == '__main__':
    main()
