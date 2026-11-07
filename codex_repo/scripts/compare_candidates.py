"""Compare candidate families on reproducible artificial regimes.

python -m scripts.compare_candidates --output logs/candidates/stress
Additional seeds are evaluation cases, not a parameter search.
"""
import argparse
import json
from pathlib import Path

from scripts.benchmark import digest, evaluate
from scripts.stress import generate
from simulator.main import load_strategy_from_file


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('logs/candidates/stress'))
    parser.add_argument('--seeds',type=int,nargs='+',default=[11,29,47,101,211,307])
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    sources=[Path('strategies')/(name+'_strategy.py') for name in ('arena','guarded','passive')]
    results={}
    for mode in ('flat','noise','continuation','reversal','regime_switch','recovery'):
        for seed in args.seeds:
            name=f'{mode}_{seed}'
            tape=args.output/(name+'.csv')
            generate(tape,mode,seed)
            case={'data_sha256':digest(tape),'strategies':{}}
            for source in sources:
                strategy=load_strategy_from_file(source)
                run=evaluate(strategy,tape,args.output/name/source.stem,200 if mode=='recovery' else 300)
                if run['result']['breach_penalty'] or run['max_potential_inventory_at_submission']>strategy.POSITION_LIMIT:
                    raise AssertionError(f'{name}/{source.stem}: risk failure')
                if source.stem=='guarded_strategy':
                    run['guard_score_at_end']=strategy._guard_score
                    run['guard_scale_at_end']=strategy._guard_scale
                case['strategies'][source.stem]=run
            results[name]=case
        totals={s.stem:round(sum(v['strategies'][s.stem]['result']['pnl'] for k,v in results.items() if k.startswith(mode+'_')),2) for s in sources}
        print(mode,totals,flush=True)
    report={'source_hashes':{str(p):digest(p) for p in sources},'seeds':args.seeds,
            'limitation':'Artificial regimes; no evidence of recorded-market performance. Seeds 11/29/47 overlap earlier stress work.',
            'cases':results}
    (args.output/'comparison.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':
    main()
