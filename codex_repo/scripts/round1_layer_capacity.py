"""Test whether arbitrary order-count caps strand otherwise available exposure."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/layer_capacity')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT;specs={}
    for family,basefile in (('f15','strategies/round1_private_554347.py'),('f23','strategies/round1_size_555389.py')):
        base=Path(basefile).read_text()
        for slots in (16,32,64,256):
            name=f'{family}_slots_{slots}'
            assert 'if len(current) >= 8:' in base
            text=base.replace('if len(current) >= 8:',f'if len(current) >= {slots}:')
            path=ROOT/'sources'/(name+'.py');path.write_text(text)
            assert not check(path),check(path)
            specs[name]=dict(family=family,max_orders_per_side=slots,source_sha256=digest(path))
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/round1/screening.csv','screening',workers=4)
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    full=search_queue.batch(finalists,'data/round1.csv','full',workers=3)
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],parameters=specs[winner],
        limitation='Sample tuning; only order-count capacity changes. All accepted, pending and canceling quantities remain reserved under hard 100-lot potential bound.'),indent=2)+'\n')
    print('WINNER LAYER CAPACITY',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
