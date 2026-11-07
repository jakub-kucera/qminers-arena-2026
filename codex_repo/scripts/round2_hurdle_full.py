"""Freeze the predeclared prefix winner, then audit its full local replay."""
from pathlib import Path
import json
from scripts.round2_workbench import load_manifest, run_candidate, write_json

ROOT=Path('logs/round2_regime_hurdles')


def main():
    protocol=json.loads((ROOT/'protocol.json').read_text())
    results=json.loads((ROOT/'results.json').read_text())
    eligible=[c for c in protocol['candidates'] if results[c['name']]['later30']>0
              and results[c['name']]['last20']>0]
    winner=max(eligible,key=lambda c:results[c['name']]['later30']+results[c['name']]['last20'])
    selection=dict(candidate=winner,rule=protocol['selection'],scope=protocol['scope'])
    path=ROOT/'full_selection.json'
    if path.exists():assert json.loads(path.read_text())==selection
    else:write_json(path,selection)
    print('Frozen',winner['name'],'before full replay',flush=True)
    m=load_manifest(Path('logs/round2_local_intake'))
    destination=ROOT/'full_audit.json'
    if destination.exists():
        print('Already completed; preserving existing audit',flush=True)
        return
    r=run_candidate(winner,m['data'],ROOT/'full_audit',
        (m['first_us']+1800000000,m['development_cutoff_us'],m['validation_cutoff_us']))
    r['last20']=r['result']['pnl']-r['boundary_pnl'][str(m['validation_cutoff_us'])]
    write_json(destination,r)
    print(r['result'], 'last20',r['last20'],flush=True)


if __name__=='__main__':main()
