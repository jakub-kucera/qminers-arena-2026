"""Freeze a predeclared later-period winner and run one full local audit."""
import argparse
import json
from pathlib import Path
from scripts.round2_workbench import load_manifest,run_candidate,write_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study',type=Path,required=True)
    args=parser.parse_args();root=args.study
    protocol=json.loads((root/'protocol.json').read_text())
    results=json.loads((root/'results.json').read_text())
    assert len(results)==len(protocol['candidates'])
    eligible=[c for c in protocol['candidates'] if results[c['name']]['later30']>0 and results[c['name']]['last20']>0]
    winner=max(eligible,key=lambda c:results[c['name']]['later30']+results[c['name']]['last20'])
    selection=dict(candidate=winner,selection_rule=protocol['selection'],goal=protocol['goal'],scope=protocol['scope'])
    p=root/'full_selection.json'
    if p.exists():assert json.loads(p.read_text())==selection
    else:write_json(p,selection)
    print('Frozen',winner['name'],flush=True)
    p=root/'full_audit.json'
    if p.exists():
        print('Existing full audit preserved');return
    m=load_manifest(Path('logs/round2_local_intake'))
    r=run_candidate(winner,m['data'],root/'full_audit',
        (m['first_us']+1800000000,m['development_cutoff_us'],m['validation_cutoff_us']))
    r['last20']=r['result']['pnl']-r['boundary_pnl'][str(m['validation_cutoff_us'])]
    write_json(p,r)
    print(r['result'],r['last20'],flush=True)


if __name__=='__main__':main()
