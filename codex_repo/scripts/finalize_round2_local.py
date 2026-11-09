"""Verify native parity and preserve a local-only candidate and evidence."""
import argparse
import json
import shutil
from pathlib import Path
from scripts.benchmark import digest
from scripts.check_submission import check
from scripts.round2_workbench import write_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    root=Path('logs/round2_regime_hurdles')
    selection=json.loads((root/'full_selection.json').read_text())['candidate']
    audit=json.loads((root/'full_audit.json').read_text())
    native=json.loads((root/'official_cli/result.json').read_text())
    assert audit['result']==native,'Native CLI result differs from audit'
    assert native['pnl']>=150000 and native['breach_penalty']==0
    assert audit['max_abs_inventory']<=100 and audit['max_potential_inventory_at_submission']<=100
    source=Path(selection['file'])
    assert digest(source)==selection['source_sha256']==audit['source_sha256']
    assert not check(source)
    sensitivity=json.loads(Path('logs/round2_hurdle_sensitivity/results.json').read_text())
    assert len(sensitivity)==4,'Wait for all predeclared sensitivity runs'
    # Sensitivity is reported, never used to replace this frozen selection.
    for family in ('round2_regime_hurdles','round2_hurdle_sensitivity'):
        src=Path('logs')/family;dst=Path('research')/(family+'_20261107')
        dst.mkdir(exist_ok=True)
        for p in src.glob('*.json'):shutil.copyfile(p,dst/p.name)
        shutil.copytree(src/'sources',dst/'sources',dirs_exist_ok=True)
        (dst/'.gitattributes').write_text('* -text whitespace=cr-at-eol\n*.json linguist-generated=true\n')
    archived=Path('research/round2_regime_hurdles_20261107')
    shutil.copyfile(root/'official_cli/result.json',archived/'official_cli_result.json')
    shutil.copyfile(root/'official_cli/pnl.csv',archived/'official_cli_pnl.csv')
    target=Path('strategies/round2_composite_local.py')
    if target.exists():assert digest(target)==digest(source),'Do not overwrite another candidate'
    else:shutil.copyfile(source,target)
    args.output.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(source,args.output/'round2_composite_local.py')
    report=dict(status='Local 150k target achieved; no server submission',
        selection=selection,result=native,last20_increment=audit['last20'],
        max_abs_inventory=audit['max_abs_inventory'],
        max_potential_inventory=audit['max_potential_inventory_at_submission'],
        sampled_max_drawdown=audit['max_drawdown_1s'],data_sha256=audit['data_sha256'],
        engine_sha256=digest('simulator/simulator.py'),source_sha256=digest(source),
        official_curve_sha256=digest(root/'official_cli/pnl.csv'),
        verification='Unmodified native CLI and instrumented replay match every result field.',
        limitations='All public data consumed. Parameter sensitivity is not independent validation. No unseen-tape guarantee.',
        sensitivity={name:dict(first80=r['result']['pnl'],later30=r['later30'],last20=r['last20'])
                     for name,r in sensitivity.items()})
    write_json(archived/'verified_result.json',report)
    write_json(args.output/'verified_result.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
