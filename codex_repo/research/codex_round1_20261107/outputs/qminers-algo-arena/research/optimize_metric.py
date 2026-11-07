"""Small, frozen policy search for official PnL with chronological, multiplicity-aware selection."""
import argparse
import ast
import copy
import json
import os
import shutil
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.linear_model import ElasticNet
from threadpoolctl import threadpool_limits

import robust_ml_common
import run_study
from export_candidates import render, source_check
from fit_robust_ml import linear_fit
from ml_round1_common import file_hash, future_change, load_features
from run_study import ROOT, dump

DEST=ROOT/'research/metric_optimization_results'
SOURCES=DEST/'sources'
WORK=ROOT.parents[1]/'work/metric-optimization'
ROBUST=ROOT/'research/robust_ml_results'
LAGS=(5,20,50)
PARENT='g1_e015'


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def at(curve,seconds):
    return float(curve[max(0,np.searchsorted(curve[:,0],seconds*1e6,side='right')-1),1])


def configurations():
    rows=[]
    for gain in (.5,1.,1.5):
        for edge in (0.,.15,.3):
            name='g'+str(gain).rstrip('0').rstrip('.').replace('.','')+'_e'+str(edge).rstrip('0').rstrip('.').replace('.','')
            rows.append(dict(name=name,gain=gain,edge=edge,params={},family='grid'))
    for name,params in [('refill1',dict(MIN_REFILL=1)),('refill25',dict(MIN_REFILL=25)),
                        ('deplete0',dict(DEPLETE_LOTS=0)),('deplete40',dict(DEPLETE_LOTS=40))]:
        rows.append(dict(name=name,gain=1.,edge=.15,params=params,family='execution'))
    assert len(rows)==13 and any(r['name']==PARENT for r in rows)
    return rows


def export(model,variant,fold):
    name=variant['name']
    spec=copy.deepcopy(model)
    spec['base']*=variant['gain']
    spec['coef']=[v*variant['gain'] for v in spec['coef']]
    old=robust_ml_common.SOURCES
    robust_ml_common.SOURCES=SOURCES
    try:
        path=robust_ml_common.export(f'{name}_f{fold}',[spec])
    finally:
        robust_ml_common.SOURCES=old
    text=render(path.read_text(encoding='utf-8'),dict(EDGE_FLOOR=variant['edge'],**variant['params']))
    compile(text,str(path),'exec')
    fails,warnings=source_check(ast.parse(text))
    assert not fails
    path.write_text(text,encoding='utf-8')
    assert path.stat().st_size<1024**2
    return path


def prefix(seconds):
    if seconds==9000:
        return ROOT.parents[1]/'work/ml-round1/round1_first75.csv'
    target=WORK/f'round1_prefix{seconds}.csv'
    if not target.exists():
        count=0
        with (ROOT/'data/round1.csv').open('rb') as source,target.open('wb') as out:
            out.write(source.readline())
            for line in source:
                if float(line.split(b',',1)[0])>seconds:
                    break
                out.write(line)
                count+=1
        dump(DEST/f'prefix{seconds}.json',dict(rows=count,seconds=seconds,sha256=file_hash(target)))
    return target


def prepare():
    DEST.mkdir(parents=True,exist_ok=True)
    WORK.mkdir(parents=True,exist_ok=True)
    assert not (DEST/'experiment_plan.json').exists(),'Do not change the plan after seeing results.'
    variants=configurations()
    plan=dict(created_utc=datetime.now(timezone.utc).isoformat(),
        objective='Official executable net PnL. The private round standardizes positive teams; no other teams private results are available. Forecast MSE, Sharpe and pnl_se are diagnostics, not the objective.',
        scoring_evidence='Team snapshot of official technical page saved 2026-11-07, lines 511-520; official ExchangeSimulator.run and executable liquidation calculation. Live general rules checked; authenticated technical page unavailable in the selected browser.',
        variants=variants,model='Elastic Net only; 24 existing causal features; target last sampled midpoint at/before 250ms; l1_ratio .5.',
        folds=[dict(fold=1,fit_end=3000,eval_start=3000,eval_end=6000),
               dict(fold=2,fit_end=6000,eval_start=6000,eval_end=9000)],
        inner_cv='Fold1 chooses alpha from .0001/.001/.01 using only 0-1500 -> 1500-3000. Fold2 reuses the already frozen first-6000 fit and its prior expanding CV. Labels crossing a time boundary are purged.',
        execution='All replays start at the beginning to preserve the book and causal state; SESSION_S stays 12000. Validation uses identical one-second sampled boundary valuations, excluding prefix-terminal liquidation differences.',
        selection='Compare each of 12 changes with its fold-matched parent in paired five-minute PnL blocks. Require positive total excess in both folds and a positive simultaneous one-sided 95% lower bound from a centered, studentized, family-wise max-T moving-block bootstrap. Choose highest total validation PnL among passing variants. If none passes, retain the parent as recommendation.',
        bootstrap=dict(seed=20261107,resamples=10000,block_seconds=300,moving_block_length=2,folds_resampled_separately=True,
            caution='Two-fold, single-tape diagnostic with dependence assumptions. Adjusts only this batch, not all earlier research or regime uncertainty.'),
        plateau='Report immediate grid neighbors and their fold improvements; an isolated grid maximum with no improving neighbor is not promoted.',
        followup='Freeze the selected candidate and the raw-profit leader if different (maximum two). Full round1 at 5/20/50ms and frozen-model sample_v2 at5ms with SESSION_S5750. No further tuning after opening these results.',
        final_gate='Require validation gate, zero penalties and reserved exposure <=100, positive 9000-12000 PnL excess over the parent at5ms, no >2% later-half loss versus parent at20/50ms, no >2% sample_v2 loss versus parent, and submission size/runtime checks. Otherwise keep the previous Elastic Net bot.',
        limitations='All provided tapes have already been inspected. No new untouched holdout exists. No procedure can guarantee absence of overfitting or a maximum private score; this finite batch ends after frozen follow-up.')
    dump(DEST/'experiment_plan.json',plan)
    f,_,x=load_features()
    t=f[:,0]/1e6
    y=future_change(f,.25)
    a=t+.25<1500
    b=(t>=1500)&(t+.25<3000)
    cv=[]
    for alpha in (.0001,.001,.01):
        spec,_=linear_fit(ElasticNet(alpha=alpha,l1_ratio=.5,max_iter=10000,tol=1e-7),x[a],y[a])
        pred=spec['base']+x[b]@np.array(spec['coef'])
        cv.append(dict(alpha=alpha,mse=float(np.mean((pred-y[b])**2))))
    alpha=min(cv,key=lambda r:r['mse'])['alpha']
    train=t+.25<3000
    early,_=linear_fit(ElasticNet(alpha=alpha,l1_ratio=.5,max_iter=10000,tol=1e-7),x[train],y[train])
    late=load(ROBUST/'all_parameters.json')['elastic250'][0]
    dump(DEST/'models.json',dict(early=early,late=late,early_alpha=alpha,inner_cv=cv,early_training_rows=int(train.sum())))
    entries=[]
    for fold,model,end in [(1,early,6000),(2,late,9000)]:
        data=prefix(end)
        for variant in variants:
            source=export(model,variant,fold)
            name=f"{variant['name']}_f{fold}"
            entries.append(dict(name=name,variant=variant['name'],fold=fold,sha256=file_hash(source),
                case=[name,str(source),str(data),{},5]))
        name=f'f4_f{fold}'
        entries.append(dict(name=name,variant='f4',fold=fold,sha256=file_hash(ROOT/'strategies/round1_best.py'),
            case=[name,str(ROOT/'strategies/round1_best.py'),str(data),{},5]))
    assert file_hash(SOURCES/f'{PARENT}_f2.py')==file_hash(ROOT/'strategies/round1_robust_candidate.py')
    dump(DEST/'validation_plan.json',entries)
    print(json.dumps(dict(cases=len(entries),early_alpha=alpha,parent_exact_source_match=True)),flush=True)


def run_case(case):
    run_study.OUT=DEST
    r=run_study.run_case(case)
    curve=np.load(DEST/f'{case[0]}_trace.npz')['curve']
    if case[0].endswith(('_f1','_f2')):
        # run_study appends a terminal mark after draining pending orders. Use only
        # the regular one-second samples for validation block comparisons.
        curve=curve[:-1]
        start=3000 if case[0].endswith('_f1') else 6000
        boundaries=list(range(start,start+3001,300))
        values=[at(curve,s) for s in boundaries]
        r['evaluation_pnl']=values[-1]-values[0]
        r['blocks']=np.diff(values).tolist()
        r['boundary_marks']=values
    elif r['data']=='round1.csv':
        r['training_pnl']=at(curve,6000)
        r['validation_pnl']=at(curve,9000)-at(curve,6000)
        r['tail_pnl']=r['result']['pnl']-at(curve,9000)
        r['outside_fit_pnl']=r['result']['pnl']-at(curve,6000)
    dump(DEST/f'{case[0]}.json',r)
    return r


def execute(entries,filename):
    assert not (DEST/filename).exists(),'Do not replace completed replay results.'
    done=[]
    with ProcessPoolExecutor(max_workers=min(18,os.cpu_count() or 1,len(entries))) as pool:
        futures={pool.submit(run_case,e['case']):e['name'] for e in entries}
        for future in as_completed(futures):
            try:
                r=future.result()
            except Exception as error:
                dump(DEST/'run_error.json',dict(name=futures[future],error=repr(error)))
                raise
            done.append(r)
            dump(DEST/filename,done)
            print(json.dumps(dict(done=len(done),total=len(entries),name=r['name'],pnl=r['result']['pnl'],
                evaluation=r.get('evaluation_pnl'),penalty=r['result']['breach_penalty'],cpu=r['cpu_seconds'])),flush=True)
    return done


def select():
    assert not (DEST/'selection.json').exists(),'Selection is frozen before follow-up.'
    plan=load(DEST/'experiment_plan.json')
    results=load(DEST/'validation_summary.json')
    assert len(results)==28
    # Preserve raw results and correct the initially included terminal trace row.
    # This implements the boundary convention already fixed in the plan.
    dump(DEST/'validation_summary_before_boundary_correction.json',results)
    corrections=[]
    for r in results:
        curve=np.load(DEST/f"{r['name']}_trace.npz")['curve'][:-1]
        start=3000 if r['name'].endswith('_f1') else 6000
        values=[at(curve,s) for s in range(start,start+3001,300)]
        corrections.append(dict(name=r['name'],before=r['evaluation_pnl'],after=values[-1]-values[0]))
        r['evaluation_pnl']=values[-1]-values[0]
        r['blocks']=np.diff(values).tolist()
        r['boundary_marks']=values
        dump(DEST/f"{r['name']}.json",r)
    dump(DEST/'validation_summary.json',results)
    dump(DEST/'boundary_correction.json',dict(at_utc=datetime.now(timezone.utc).isoformat(),
        reason='The trace has an extra terminal-liquidation row. Remove that row from validation block scoring to implement the predeclared regular-grid convention; official full PnL remains unchanged. Correction applied uniformly before statistical selection.',
        changes=corrections))
    results={r['name']:r for r in results}
    names=[v['name'] for v in plan['variants'] if v['name']!=PARENT]
    blocks=[]
    for fold in (1,2):
        base=np.array(results[f'{PARENT}_f{fold}']['blocks'])
        blocks.append(np.column_stack([np.array(results[f'{name}_f{fold}']['blocks'])-base for name in names]))
    sample=np.vstack(blocks)
    means=sample.mean(axis=0)
    se=sample.std(axis=0,ddof=1)/np.sqrt(len(sample))
    centered=[b-b.mean(axis=0) for b in blocks]
    rng=np.random.default_rng(20261107)
    draws=10000
    boot=np.zeros((draws,len(names)))
    for values in centered:
        starts=rng.integers(0,10,size=(draws,5))
        indices=np.stack([starts,(starts+1)%10],axis=-1).reshape(draws,10)
        boot+=values[indices].sum(axis=1)/20
    eligible_se=se>1e-9
    tstar=np.zeros_like(boot)
    tstar[:,eligible_se]=boot[:,eligible_se]/se[eligible_se]
    critical=float(np.quantile(tstar.max(axis=1),.95))
    lower=means-critical*se
    records=[]
    variants={v['name']:v for v in plan['variants']}
    for j,name in enumerate(names):
        excess=[float(b[:,j].sum()) for b in blocks]
        safe=all(results[f'{name}_f{fold}']['result']['breach_penalty']==0 and results[f'{name}_f{fold}']['max_reserved_exposure']<=100 for fold in (1,2))
        neighbors=[]
        if variants[name]['family']=='grid':
            v=variants[name]
            for other in plan['variants']:
                if other['family']!='grid' or other['name']==name:
                    continue
                adjacent=(abs(other['gain']-v['gain'])==.5 and other['edge']==v['edge']) or (other['gain']==v['gain'] and abs(abs(other['edge']-v['edge'])-.15)<1e-9)
                if adjacent:
                    ex=[results[f"{other['name']}_f{f}"]['evaluation_pnl']-results[f'{PARENT}_f{f}']['evaluation_pnl'] for f in (1,2)]
                    neighbors.append(dict(name=other['name'],fold_excess=ex))
        plateau=not neighbors or any(all(e>0 for e in v['fold_excess']) for v in neighbors)
        records.append(dict(name=name,fold_excess=excess,total_excess=sum(excess),
            positive_blocks=int(np.sum(sample[:,j]>0)),simultaneous_lower_total=float(lower[j]*20),
            adjusted_p=float((1+np.sum(tstar.max(axis=1)>=means[j]/se[j]))/(draws+1)) if se[j]>1e-9 else None,
            neighbors=neighbors,plateau=plateau,safe=safe,
            gate=bool(safe and all(e>0 for e in excess) and lower[j]>0 and plateau)))
    records.sort(key=lambda r:r['total_excess'],reverse=True)
    passing=[r for r in records if r['gate']]
    selected=passing[0]['name'] if passing else PARENT
    raw_leader=records[0]['name']
    followup=list(dict.fromkeys([selected,raw_leader]))
    # The parent has already completed identical full/stress runs; reuse those if retained.
    followup=[name for name in followup if name!=PARENT]
    for name in followup:
        source=SOURCES/f'{name}_f2.py'
        target=ROOT/'strategies'/f'round1_metric_{name}.py'
        shutil.copyfile(source,target)
    selection=dict(frozen_utc=datetime.now(timezone.utc).isoformat(),selected=selected,raw_leader=raw_leader,
        passing=len(passing),critical_max_t=critical,ranking=records,followup=followup,
        note='Simultaneous bounds adjust this fixed 12-change batch only. Historical reuse and new-regime uncertainty remain. No parameter updates after this record.')
    dump(DEST/'selection.json',selection)
    print(json.dumps(selection,indent=2),flush=True)
    entries=[]
    for name in followup:
        path=ROOT/'strategies'/f'round1_metric_{name}.py'
        for delay in LAGS:
            case=f'final_{name}_d{delay}'
            entries.append(dict(name=case,case=[case,str(path),str(ROOT/'data/round1.csv'),{},delay]))
        case='v2_'+name
        entries.append(dict(name=case,case=[case,str(path),str(ROOT/'data/sample_v2.csv'),{'SESSION_S':5750.},5]))
    dump(DEST/'final_plan.json',entries)


def benchmark():
    from benchmark_export import peak_working_set
    selection=load(DEST/'selection.json')
    name=selection['selected']
    if name==PARENT:
        record=load(ROBUST/'candidate_benchmark.json')
        record['reused_from']=str(ROBUST/'candidate_benchmark.json')
    else:
        source=ROOT/'strategies'/f'round1_metric_{name}.py'
        wall,cpu=time.perf_counter(),time.process_time()
        result=run_study.ExchangeSimulator(run_study.load_strategy_from_file(source),run_study.config()).run(ROOT/'data/round1.csv')
        record=dict(source=str(source),sha256=file_hash(source),result=result.model_dump(mode='json'),
            wall_seconds=time.perf_counter()-wall,cpu_seconds=time.process_time()-cpu,
            peak_working_set_bytes=peak_working_set(),
            note='Exact frozen file and unmodified official engine. Single process, other local replays may run concurrently.')
    dump(DEST/'candidate_benchmark.json',record)
    print(json.dumps(dict(benchmark_pnl=record['result']['pnl'],cpu_seconds=record['cpu_seconds'],memory_MiB=record['peak_working_set_bytes']/1024**2)),flush=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('phase',choices=['prepare','validate','select','final','benchmark'])
    args=parser.parse_args()
    if args.phase=='prepare':
        with threadpool_limits(limits=8):
            prepare()
    elif args.phase=='validate':
        execute(load(DEST/'validation_plan.json'),'validation_summary.json')
    elif args.phase=='select':
        select()
    elif args.phase=='benchmark':
        benchmark()
    else:
        entries=load(DEST/'final_plan.json')
        if entries:
            execute(entries,'final_summary.json')


if __name__=='__main__':
    main()
