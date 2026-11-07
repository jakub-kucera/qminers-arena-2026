"""Latency checks of the unchanged selected ML export, with no further tuning."""
from concurrent.futures import ProcessPoolExecutor, as_completed
from ml_round1_common import DEST, ROOT
from run_round1_ml import run_case
from run_study import dump


def main():
    cases = [[f'ml_delay{delay}', str(ROOT/'strategies/round1_ml_candidate.py'),
              str(ROOT/'data/round1.csv'), {}, delay] for delay in (20,50)]
    dump(DEST/'stress_plan.json',cases)
    done=[]
    with ProcessPoolExecutor(max_workers=2) as pool:
        for future in as_completed([pool.submit(run_case,case) for case in cases]):
            done.append(future.result())
            dump(DEST/'stress_summary.json',done)


if __name__=='__main__':
    main()
