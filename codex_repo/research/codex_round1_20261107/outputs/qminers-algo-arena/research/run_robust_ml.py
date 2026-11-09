"""Parallel validation replays; no late-tail selection or policy tuning."""
import json
import os
from concurrent.futures import ProcessPoolExecutor, as_completed

from ml_round1_common import file_hash
from robust_ml_common import DEST, PREFIX, PREVIOUS, ROOT, enrich, load_json, run_case
from run_study import dump


def execute(entries, filename):
    done, errors = [], []
    with ProcessPoolExecutor(max_workers=min(os.cpu_count() or 1,len(entries))) as pool:
        futures={pool.submit(run_case,e['case']):e['name'] for e in entries}
        for future in as_completed(futures):
            try:
                result=future.result()
                done.append(result)
                dump(DEST/filename,done)
                print(json.dumps(dict(completed=len(done),total=len(entries),name=result['name'],
                    pnl=result['result']['pnl'],validation=result['validation_pnl'],blocks=result['validation_blocks'],
                    penalty=result['result']['breach_penalty'],reserved=result['max_reserved_exposure'],
                    cpu_s=result['cpu_seconds'])),flush=True)
            except Exception as error:
                errors.append(dict(name=futures[future],error=repr(error)))
                dump(DEST/(filename+'.errors.json'),errors)
                print(json.dumps(errors[-1]),flush=True)
    if errors:
        raise RuntimeError(errors)
    return done


def main():
    fit=load_json(DEST/'fit_results.json')
    entries=[]
    for model in fit['models']:
        for delay in (5,20):
            name=f"{model['name']}_d{delay}"
            entries.append(dict(name=name,model=model['name'],sha256=model['sha256'],
                case=[name,model['source'],str(PREFIX),{},delay]))
    for name,path in [('f4',ROOT/'strategies/round1_best.py'),('prior_cat',ROOT/'strategies/round1_ml_candidate.py')]:
        case_name=name+'_d20'
        entries.append(dict(name=case_name,model=name,sha256=file_hash(path),
            case=[case_name,str(path),str(PREFIX),{},20]))
    previous=load_json(PREVIOUS/'validation_summary.json')
    controls=[]
    for oldname,newname in [('f4_reference','f4_d5'),('cat24_025s_t40','prior_cat_d5')]:
        r=next(x for x in previous if x['name']==oldname)
        enrich(r,PREVIOUS)
        r['prior_name']=oldname
        r['name']=newname
        r['reused_from']=str(PREVIOUS/'validation_summary.json')
        controls.append(r)
    dump(DEST/'reused_controls.json',controls)
    dump(DEST/'validation_plan.json',dict(entries=entries,reused_controls=controls))
    execute(entries,'validation_summary.json')


if __name__=='__main__':
    main()
