"""Optimize simple microstructure signals against execution PnL, without regression."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/direct_signals')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT
    base=Path('strategies/round1_submission.py').read_text().replace('        self._learn(now,mid)\n','')
    expressions={}
    for feature in ('count_imbalance','robust_imbalance','depth_count','depth_imbalance','imbalance','depth_mid'):
        for alpha in (-0.5,0.25,0.5,1.0,2.0):
            expressions[f'{feature}_{alpha}']=f'{alpha}*{feature}'
    for alpha in (0.5,1.0,2.0):
        for beta in (-0.25,0.25,0.5):
            expressions[f'count_{alpha}_flow_{beta}']=f'{alpha}*count_imbalance+{beta}*flow'
    for alpha in (0.5,1.0):
        for beta in (-0.5,0.5):
            expressions[f'count_{alpha}_quantity_{beta}']=f'{alpha}*count_imbalance+{beta}*imbalance'
            expressions[f'count_{alpha}_depth_{beta}']=f'{alpha}*count_imbalance+{beta}*depth_count'
    specs={}
    for name,expression in expressions.items():
        path=ROOT/'sources'/(name+'.py')
        text=base.replace('        fair = mid + ',f'        prediction = max(-2.0,min(2.0,{expression}))\n        fair = mid + ')
        path.write_text(text);assert not check(path),check(path)
        specs[name]=dict(expression=expression,source_sha256=digest(path))
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/round1/screening.csv','screening',workers=6)
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:5]
    full=search_queue.batch(finalists,'data/round1.csv','full',workers=5)
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],parameters=specs[winner],
        limitation='Direct heuristic coefficients selected on consumed round1 sample; no independent holdout remains.'),indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
