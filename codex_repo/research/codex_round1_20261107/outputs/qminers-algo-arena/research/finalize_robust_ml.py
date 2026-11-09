"""Freeze candidates using validation only, then run all remaining diagnostics."""
import ast
import json
import shutil
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from benchmark_export import peak_working_set
from export_candidates import source_check
from ml_round1_common import file_hash
from robust_ml_common import DEST, ROOT, load_json
from run_robust_ml import execute
from run_study import ExchangeSimulator, config, dump, load_strategy_from_file


def benchmark(path):
    cpu, wall = time.process_time(), time.perf_counter()
    result = ExchangeSimulator(load_strategy_from_file(Path(path)), config()).run(ROOT/'data/round1.csv')
    record = dict(source=path,sha256=file_hash(path),result=result.model_dump(mode='json'),
        cpu_seconds=time.process_time()-cpu,wall_seconds=time.perf_counter()-wall,
        peak_working_set_bytes=peak_working_set(),
        note='One official-engine Python process; other diagnostic runs may execute concurrently. No sklearn/CatBoost imports in the candidate.')
    dump(DEST/'candidate_benchmark.json',record)
    print(json.dumps(dict(benchmark_pnl=result.pnl,cpu_s=record['cpu_seconds'])),flush=True)
    return record


def main():
    assert not (DEST/'selection.json').exists(), 'Selection is immutable once the tail is opened.'
    fit=load_json(DEST/'fit_results.json')
    specs={r['name']:r for r in fit['models']}
    results=load_json(DEST/'validation_summary.json')+load_json(DEST/'reused_controls.json')
    assert len(results)==20
    byname={r['name']:r for r in results}
    ranking=[]
    for name in list(specs)+['prior_cat']:
        excess, relative, block_excess=[],[],[]
        safe=True
        for delay in (5,20):
            r,base=byname[f'{name}_d{delay}'],byname[f'f4_d{delay}']
            excess.append(r['validation_pnl']-base['validation_pnl'])
            relative.append(excess[-1]/base['validation_pnl'])
            block_excess.extend(a-b for a,b in zip(r['validation_blocks'],base['validation_blocks']))
            safe &= r['result']['breach_penalty']==0 and r['max_reserved_exposure']<=100
        score=min(relative)
        positive=sum(v>0 for v in block_excess)
        ranking.append(dict(name=name,score=score,excess=excess,relative=relative,
            block_excess=block_excess,positive_blocks=positive,safe=safe,
            passes_validation_gate=bool(safe and score>0 and positive>=4)))
    ranking.sort(key=lambda x:x['score'],reverse=True)
    new=[r for r in ranking if r['name'] in specs]
    candidates=sorted(new,key=lambda r:(r['passes_validation_gate'],r['score']),reverse=True)[:2]
    for i,c in enumerate(candidates):
        spec=specs[c['name']]
        source=Path(spec['source'])
        assert file_hash(source)==spec['sha256']
        filename='round1_robust_candidate.py' if i==0 else 'round1_robust_alternative.py'
        path=ROOT/'strategies'/filename
        shutil.copyfile(source,path)
        failures,warnings=source_check(ast.parse(path.read_text(encoding='utf-8')))
        assert not failures and path.stat().st_size<1024**2
        c.update(export=str(path),sha256=file_hash(path),bytes=path.stat().st_size)
    selection=dict(frozen_utc=datetime.now(timezone.utc).isoformat(),ranking=ranking,candidates=candidates,
        decision='Freeze these two new candidates for diagnostics; selection gate alone is not a deployment recommendation.',
        required_followup='Inspect 9000-12000 tail, latency 50ms, alternate sample, and runtime before recommending. No parameter changes after selection.')
    dump(DEST/'selection.json',selection)
    print(json.dumps(selection,indent=2),flush=True)
    entries=[]
    for c in candidates:
        for delay in (5,20,50):
            name=f"final_{c['name']}_d{delay}"
            entries.append(dict(name=name,model=c['name'],case=[name,c['export'],str(ROOT/'data/round1.csv'),{},delay]))
    stress_sources=[(c['name'],c['export']) for c in candidates]+[
        ('f4',str(ROOT/'strategies/round1_best.py')),
        ('prior_cat',str(ROOT/'strategies/round1_ml_candidate.py'))]
    for model,source in stress_sources:
        name='v2_'+model
        entries.append(dict(name=name,model=model,case=[name,source,str(ROOT/'data/sample_v2.csv'),{'SESSION_S':5750.0},5]))
    dump(DEST/'final_plan.json',entries)
    with ProcessPoolExecutor(max_workers=1) as pool:
        future=pool.submit(benchmark,candidates[0]['export'])
        final=execute(entries,'final_summary.json')
        benchmark_result=future.result()
    winner=next(r for r in final if r['name']==f"final_{candidates[0]['name']}_d5")
    assert winner['result']==benchmark_result['result']
    print(json.dumps(dict(completed=len(final),exact_export_matches=True)),flush=True)


if __name__=='__main__':
    main()
