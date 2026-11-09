"""Post-selection audit: remove an unverified assumption about private tape duration."""
import argparse
import ast
import json
import time
from datetime import datetime, timezone

from benchmark_export import peak_working_set
from export_candidates import render, source_check
from ml_round1_common import file_hash
from optimize_metric import DEST, ROOT, execute, load
from run_study import ExchangeSimulator, config, dump, load_strategy_from_file

PATH=ROOT/'strategies/round1_metric_portable.py'


def prepare():
    assert not (DEST/'portability_plan.json').exists()
    selection=load(DEST/'selection.json')
    assert selection['selected']=='deplete0'
    source=ROOT/'strategies/round1_metric_deplete0.py'
    text=source.read_text(encoding='utf-8')
    original='        winding = (now - self.start) / 1_000_000 > SESSION_S - WIND_DOWN_S'
    replacement='        winding = SESSION_S is not None and (now - self.start) / 1_000_000 > SESSION_S - WIND_DOWN_S'
    assert text.count(original)==1
    text=render(text.replace(original,replacement),dict(SESSION_S=None))
    compile(text,str(PATH),'exec')
    failures,warnings=source_check(ast.parse(text))
    assert not failures and len(text.encode())<1024**2
    PATH.write_text(text,encoding='utf-8')
    plan=dict(created_utc=datetime.now(timezone.utc).isoformat(),
        reason='The current public round lasts 12000s; the inspected technical rules do not guarantee that the private tape has that duration. A hard-coded wind-down could stop profitable trading for the remainder of a longer private tape.',
        deviation='This is an explicitly recorded post-selection portability audit, outside the predeclared policy search. Its endpoint effect is not covered by the original 12-comparison bootstrap bound.',
        change='SESSION_S=None disables scheduled wind-down; optional known horizons remain supported. The official scorer liquidates any remaining inventory at executable market prices. Forecast coefficients, quote edge, capacity accounting and all other policy settings are unchanged.',
        inference='The change is behaviorally identical before the old wind-down boundary. It does not access the eventual tape length or use future data.',
        rule='Use the portable file only if round1 PnL at5ms is at least the frozen timed candidate, 20/50ms later-half PnL and sample_v2 PnL deteriorate by no more than2% versus that candidate, all risk and source/runtime checks pass. Otherwise retain timed candidate and report duration assumption.',
        source=str(PATH),sha256=file_hash(PATH))
    entries=[]
    for delay in (5,20,50):
        name=f'portable_d{delay}'
        entries.append(dict(name=name,case=[name,str(PATH),str(ROOT/'data/round1.csv'),{},delay]))
    entries.append(dict(name='portable_v2',case=['portable_v2',str(PATH),str(ROOT/'data/sample_v2.csv'),{},5]))
    plan['entries']=entries
    dump(DEST/'portability_plan.json',plan)
    print(json.dumps(dict(source=str(PATH),sha256=plan['sha256'],replays=len(entries))),flush=True)


def benchmark():
    wall,cpu=time.perf_counter(),time.process_time()
    result=ExchangeSimulator(load_strategy_from_file(PATH),config()).run(ROOT/'data/round1.csv')
    record=dict(source=str(PATH),sha256=file_hash(PATH),result=result.model_dump(mode='json'),
        wall_seconds=time.perf_counter()-wall,cpu_seconds=time.process_time()-cpu,
        peak_working_set_bytes=peak_working_set(),note='Unmodified official loader/engine; no research callbacks.')
    dump(DEST/'portable_benchmark.json',record)
    print(json.dumps(dict(pnl=result.pnl,cpu=record['cpu_seconds'],memory_MiB=record['peak_working_set_bytes']/1024**2)),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('phase',choices=['prepare','run','benchmark'])
    args=parser.parse_args()
    if args.phase=='prepare':prepare()
    elif args.phase=='run':execute(load(DEST/'portability_plan.json')['entries'],'portability_results.json')
    else:benchmark()
