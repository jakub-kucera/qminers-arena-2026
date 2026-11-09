"""Predeclared stress checks of the frozen file; no policy refitting."""
import json
from concurrent.futures import ProcessPoolExecutor,as_completed
from run_study import ROOT,dump
import run_study
from composite_study import DEST


def run(case):
    run_study.OUT=DEST
    return run_study.run_case(case)


def main():
    selected=json.loads((DEST/'selection.json').read_text())['selected']['path']
    f4=str(ROOT/'research/reference_strategies/r0_F4_depletion_guard.py')
    data=str(ROOT/'data/sample_v2.csv')
    old=str(ROOT/'data/sample.csv')
    tasks=[['stress_20ms',selected,data,{},20],['stress_50ms',selected,data,{},50],
       ['cross_original_selected',selected,old,{'SESSION_S':3599.000003},5],
       ['cross_original_F4',f4,old,{'SESSION_S':3599.000003},5]]
    dump(DEST/'stress_plan.json',tasks)
    done=[]
    with ProcessPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(run,c) for c in tasks]
        for future in as_completed(futures):
            done.append(future.result())
            dump(DEST/'stress_summary.json',done)


if __name__=='__main__':
    main()
