"""Bounded ablation plan, using a continuous 75% prefix for policy selection."""
import argparse
import contextlib
import io
import json
import time
from concurrent.futures import ProcessPoolExecutor,as_completed
from pathlib import Path
import numpy as np
import run_study
from run_study import ROOT,OUT,dump

DEST=ROOT/'research/composite_results'
SCRATCH=ROOT.parents[1]/'work/composite'


def prepare():
    profile=json.loads((OUT/'dataset_profile.json').read_text())
    first=profile['first_s'];length=profile['duration_s']
    SCRATCH.mkdir(parents=True,exist_ok=True)
    prefix=SCRATCH/'sample_v2_first75.csv'
    cutoff=first+.75*length
    n=0
    with (ROOT/'data/sample_v2.csv').open() as source,prefix.open('w',newline='') as sink:
        sink.write(source.readline())
        for line in source:
            if float(line.split(',',1)[0])>cutoff:
                break
            sink.write(line);n+=1
    params=json.loads((DEST/'model_params.json').read_text())
    variants=[
       ('control',{}),
       ('queue_refill',{'TOPUP':1}),
       ('inventory_refill',{'TOPUP':1,'INVENTORY_SIZE':1}),
       ('larger_reducing_quote',{'QUOTE':200}),
       ('linear_sizes',{'MODEL':'linear','SIZE_ALPHA':1.5,'TARGET_ALPHA':80}),
       ('ensemble_sizes',{'MODEL':'ensemble','SIZE_ALPHA':1.5,'TARGET_ALPHA':80}),
       ('ensemble_refill',{'MODEL':'ensemble','SIZE_ALPHA':1.5,'TARGET_ALPHA':80,'TOPUP':1,'INVENTORY_SIZE':1}),
       ('ensemble_edge',{'MODEL':'ensemble','EDGE_FLOOR':.15}),
       ('ensemble_inside',{'MODEL':'ensemble','INSIDE_MODE':'alpha','INSIDE_THRESHOLD':.25}),
       ('inventory_inside',{'INSIDE_MODE':'inventory','INVENTORY_IMPROVE':50}),
       ('composite_inside',{'MODEL':'ensemble','TOPUP':1,'INVENTORY_SIZE':1,'SIZE_ALPHA':1.5,'TARGET_ALPHA':80,
                            'INSIDE_MODE':'both','INSIDE_THRESHOLD':.25,'EDGE_FLOOR':.05}),
       ('regime_guard',{'REGIME_GUARD':1}),
       ('full_composite',{'MODEL':'ensemble','TOPUP':1,'INVENTORY_SIZE':1,'SIZE_ALPHA':1.5,'TARGET_ALPHA':80,
                          'EDGE_FLOOR':.15,'REGIME_GUARD':1}),
    ]
    template=ROOT/'strategies/composite_template.py'
    tasks=[['s0_F2',str(ROOT/'strategies/team_f2_v2.py'),str(prefix),{},5]]
    for name,variant in variants:
        tasks.append(['s0_'+name,str(template),str(prefix),dict(params,**variant),5])
    dump(DEST/'screen_plan.json',tasks)
    dump(DEST/'split_plan.json',dict(first_s=first,training_end_s=first+.5*length,
        validation_end_s=cutoff,session_s=length,prefix_rows=n,
        selection='Max validation PnL on 50-75% among zero-penalty policies with max reserved exposure <=100. Exact ties choose fewer changes. Final 25% not read during new tuning; it was already viewed in the earlier study.'))
    print('Prepared',len(tasks),'predeclared policies;',n,'prefix rows.',flush=True)


def run_one(case):
    run_study.OUT=DEST
    # Avoid printing development-period results as if they were final-test results.
    with contextlib.redirect_stdout(io.StringIO()):
        result=run_study.run_case(case)
    split=json.loads((DEST/'split_plan.json').read_text())
    curve=np.load(DEST/(result['name']+'_trace.npz'))['curve']
    cut=split['training_end_s']*1e6
    index=np.searchsorted(curve[:,0],cut,side='right')-1
    train=float(curve[index,1])
    end_cut=split['validation_end_s']*1e6
    end_index=np.searchsorted(curve[:,0],end_cut,side='right')-1
    at75=float(curve[end_index,1])
    validation=at75-train
    vc=curve[index:end_index+1,1]
    dd=float(np.max(np.maximum.accumulate(vc)-vc))
    result.update(training_pnl=train,validation_pnl=validation,validation_drawdown=dd,
                  tail_pnl=result['result']['pnl']-at75)
    dump(DEST/(result['name']+'.json'),result)
    extra=f" full={result['result']['pnl']:,.0f} tail={result['tail_pnl']:,.0f}" if curve[-1,0]>end_cut else ''
    print(f"{result['name']}: validation={validation:,.0f}{extra} drawdown={dd:,.0f} max_reserved={result['max_reserved_exposure']} penalty={result['result']['breach_penalty']} CPU={result['cpu_seconds']:.1f}s",flush=True)
    return result


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--phase',choices=['screen','refine','room','confirm','final'],default='screen')
    p.add_argument('--prepare',action='store_true')
    p.add_argument('--jobs',type=int,default=2)
    args=p.parse_args()
    if args.prepare:
        prepare()
    tasks=json.loads((DEST/(args.phase+'_plan.json')).read_text())
    done=[]
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        futures={pool.submit(run_one,case):case[0] for case in tasks}
        for future in as_completed(futures):
            done.append(future.result())
            dump(DEST/(args.phase+'_summary.json'),done)
    print('Completed phase:',args.phase,flush=True)


if __name__=='__main__':
    main()
