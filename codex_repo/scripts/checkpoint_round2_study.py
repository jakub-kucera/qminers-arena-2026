"""Preserve exact local candidate only after native CLI parity is established."""
import argparse
import json
import shutil
from pathlib import Path
from scripts.benchmark import digest
from scripts.check_submission import check
from scripts.round2_workbench import write_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();root=args.study
    selection=json.loads((root/'full_selection.json').read_text())
    candidate=selection['candidate'];source=Path(candidate['file'])
    audit=json.loads((root/'full_audit.json').read_text())
    native=json.loads((root/'official_cli/result.json').read_text())
    assert audit['result']==native
    assert digest(source)==candidate['source_sha256']==audit['source_sha256']
    assert not check(source),check(source)
    assert audit['max_abs_inventory']<=100 and audit['max_potential_inventory_at_submission']<=100
    assert native['breach_penalty']==0
    archive=Path('research')/(root.name+'_20261107')
    archive.mkdir(exist_ok=True)
    for p in root.glob('*.json'):shutil.copyfile(p,archive/p.name)
    shutil.copytree(root/'sources',archive/'sources',dirs_exist_ok=True)
    (archive/'.gitattributes').write_text('* -text whitespace=cr-at-eol\n*.json linguist-generated=true\n')
    shutil.copyfile(root/'official_cli/result.json',archive/'official_cli_result.json')
    shutil.copyfile(root/'official_cli/pnl.csv',archive/'official_cli_pnl.csv')
    name=f'round2_local_{int(native["pnl"])}.py'
    target=Path('strategies/round2')/name
    if target.exists():assert digest(target)==digest(source)
    else:shutil.copyfile(source,target)
    args.output.mkdir(exist_ok=True,parents=True)
    shutil.copyfile(source,args.output/name)
    goal=selection['goal']
    if isinstance(goal,dict):
        reference_path=Path(goal['reference_audit'])
        reference=json.loads(reference_path.read_text())
        reference_native=json.loads((reference_path.parent/'official_cli/result.json').read_text())
        assert reference['result']==reference_native
        assert reference['source_sha256']==goal['reference_source_sha256']
        assert reference['data_sha256']==audit['data_sha256']
        goal=reference_native['pnl']+goal['increment']
    report=dict(goal=goal,goal_reached=native['pnl']>=goal,result=native,
        source_sha256=digest(source),data_sha256=audit['data_sha256'],
        engine_sha256=digest('simulator/simulator.py'),last20=audit['last20'],
        max_abs_inventory=audit['max_abs_inventory'],max_potential_inventory=audit['max_potential_inventory_at_submission'],
        sampled_drawdown=audit['max_drawdown_1s'],native_cli_parity=True,
        limitations='Repeatedly consumed public tape. No untouched holdout or competition server test.',
        selection=selection)
    write_json(archive/'verified_result.json',report)
    write_json(args.output/'verified_result.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
