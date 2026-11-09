"""Freeze selection before the final full-tape replay and export runnable files."""
import ast
import hashlib
import json
from datetime import datetime,timezone
from pathlib import Path
from run_study import ROOT,dump,load_bot
from composite_study import DEST
from export_candidates import render,source_check


def export(row,name):
    path=Path(row['source'])
    assert hashlib.sha256(path.read_bytes()).hexdigest()==row['source_sha256']
    source=path.read_text(encoding='utf-8')
    source=render(source,row['params'])
    header='# Frozen from validation case '+row['name']+'.\n'
    header+='# Training: first 50% of public sample_v2; policy selection: 50-75%.\n'
    header+='# Combines team F4 execution ideas (5003a35) with independently fitted causal forecasts.\n'
    target=ROOT/'strategies'/name
    target.write_text(header+source,encoding='utf-8')
    tree=ast.parse(target.read_text())
    fails,warnings=source_check(tree)
    assert not fails,fails
    assert target.stat().st_size<=1048576
    load_bot(target,{})
    classes=[n for n in tree.body if isinstance(n,ast.ClassDef) and any(isinstance(b,ast.Name) and b.id=='BaseStrategy' for b in n.bases)]
    assert len(classes)==1
    return dict(path=str(target),sha256=hashlib.sha256(target.read_bytes()).hexdigest(),bytes=target.stat().st_size,
                validation_case=row['name'],validation_pnl=row['validation_pnl'],warnings=warnings)


def main():
    rows=[]
    for phase in ('screen','refine','room','confirm'):
        rows.extend(json.loads((DEST/(phase+'_summary.json')).read_text()))
    assert len(rows)==37,len(rows)
    byname={r['name']:r for r in rows}
    assert byname['s0_control']['result']==byname['s0_F2']['result'],'F2 control parity failed'
    assert byname['r0_control']['result']==byname['r0_F4']['result'],'F4 control parity failed'
    eligible=[r for r in rows if r['result']['breach_penalty']==0 and r['max_reserved_exposure']<=100]
    winner=max(eligible,key=lambda r:r['validation_pnl'])
    ensemble=max((r for r in eligible if r['params'].get('MODEL')=='ensemble'),key=lambda r:r['validation_pnl'])
    linear=max((r for r in eligible if r['params'].get('MODEL')=='linear'),key=lambda r:r['validation_pnl'])
    selected=export(winner,'composite_best_v2.py')
    alternative=byname['a0_matched_linear'] if winner['name']=='r0_ensemble_target40' else (linear if winner['params'].get('MODEL')=='ensemble' else ensemble)
    alt_export=export(alternative,'composite_alternative_v2.py')
    data=str(ROOT/'data/sample_v2.csv')
    tasks=[['final_selected',selected['path'],data,{},5],
           ['final_F4',byname['r0_F4']['source'],data,{},5],
           ['final_alternative',alt_export['path'],data,{},5]]
    dump(DEST/'selection.json',dict(frozen_utc=datetime.now(timezone.utc).isoformat(),
        selected=selected,alternative=alt_export,selected_params=winner['params'],selected_model=winner['params'].get('MODEL'),
        policy_trials=37,validation_baseline_F2=byname['s0_F2']['validation_pnl'],
        validation_baseline_F4=byname['r0_F4']['validation_pnl'],
        gate='Selected policy must beat F4 on the diagnostic tail and remain within the risk limits. Otherwise retain F4. Alternative is a frozen model ablation and will not be used to retune the selected policy.',
        note='The public tail was previously inspected; this is a reused confirmation segment, not new independent evidence. No parameter changes after this freeze.'))
    dump(DEST/'final_plan.json',tasks)
    print(json.dumps({'selected':selected,'alternative':alt_export,'model':winner['params'].get('MODEL')},indent=2))


if __name__=='__main__':
    main()
