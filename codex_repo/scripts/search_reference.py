"""Compare visible-touch quote anchoring with market-only reference prices."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/sample_v2/reference_search')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT
    base=Path('logs/sample_v2/target310/sources/variant_04.py').read_text()
    specs={}
    for mode in ('prices','full_touch'):
        for band in (.1,.25):
            n=f'reference_{mode}_{band}'
            addition='''        if snapshot.bids and snapshot.asks:
            bid = snapshot.bids[0].price
            ask = snapshot.asks[0].price
'''
            if mode=='full_touch':
                addition+='''            bq = sum(o.quantity for o in snapshot.bids if o.price == bid)
            aq = sum(o.quantity for o in snapshot.asks if o.price == ask)
'''
            text=base.replace('        if bid is None or ask is None or bid >= ask:',addition+'        if bid is None or ask is None or bid >= ask:')
            text=text.replace('abs(fair-mid) <= 0.1',f'abs(fair-mid) <= {band}')
            path=ROOT/'sources'/(n+'.py');path.write_text(text)
            assert not check(path),check(path)
            specs[n]={'mode':mode,'neutral_band':band,'sha256':digest(path)}
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/sample_v2/search/screening.csv','screening')
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:2]
    full=search_queue.batch(finalists,'data/sample_v2.csv','full')
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps({'name':winner,'parameters':specs[winner],
        'result':full[winner],'limitation':'Tuned on previously evaluated v2.'},indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
