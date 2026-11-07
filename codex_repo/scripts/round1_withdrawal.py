"""True one-sided quoting or wider retreats during forecast conviction."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/withdrawal')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT;base=Path('strategies/round1_submission.py').read_text();specs={}
    for threshold in (0.05,0.1,0.15,0.2,0.3):
        for retreat in (None,2,3):
            name=f'withdraw_{threshold}_{retreat}'
            sell='None' if retreat is None else f'max(sell,ask+{retreat})'
            buy='None' if retreat is None else f'min(buy,bid-{retreat})'
            extra=f'''        if prediction-skew > {threshold}:
            sell = {sell}
        elif prediction-skew < -{threshold}:
            buy = {buy}
'''
            text=base.replace('        # Withdraw the side',extra+'        # Withdraw the side')
            path=ROOT/'sources'/(name+'.py');path.write_text(text)
            assert not check(path),check(path)
            specs[name]=dict(threshold=threshold,retreat=retreat,source_sha256=digest(path))
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/round1/screening.csv','screening',workers=6)
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    full=search_queue.batch(finalists,'data/round1.csv','full',workers=3)
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],parameters=specs[winner],
        limitation='Further tuning on consumed round1; strict 100-lot potential exposure maintained.'),indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
