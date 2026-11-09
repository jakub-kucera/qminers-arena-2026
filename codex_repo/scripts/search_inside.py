"""Actual inside-spread quotes, still priced strictly away from market crossing."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/sample_v2/inside_search')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT
    base=Path('logs/sample_v2/target310/sources/variant_04.py').read_text()
    specs={}
    configs=[(width,alpha) for width in (0,.1,.25,.5) for alpha in (.25,.5)]
    for index,(width,alpha) in enumerate(configs):
        n=f'inside_{index:02d}'
        text=base.replace('0.25*spread*imbalance',f'{alpha}*spread*imbalance')
        text=text.replace('buy = min(bid,floor(fair-0.5))',f'buy = min(ask-1,floor(fair-{width}))')
        text=text.replace('sell = max(ask,ceil(fair+0.5))',f'sell = max(bid+1,ceil(fair+{width}))')
        text=text.replace('        # Withdraw the side','''        if buy >= sell:
            if imbalance > 0:
                sell = ask
            elif imbalance < 0:
                buy = bid
            else:
                buy, sell = bid, ask
        # Withdraw the side''')
        path=ROOT/'sources'/(n+'.py');path.write_text(text)
        assert not check(path),check(path)
        specs[n]={'halfwidth':width,'alpha':alpha,'sha256':digest(path)}
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/sample_v2/search/screening.csv','screening')
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    finalists=[n for n in finalists if screen[n]['result']['pnl']>88000]
    full=search_queue.batch(finalists,'data/sample_v2.csv','full') if finalists else {}
    winner=max(full,key=lambda n:full[n]['result']['pnl']) if full else None
    (ROOT/'winner.json').write_text(json.dumps({'name':winner,'parameters':specs.get(winner),
        'result':full.get(winner),'limitation':'Tuned on previously evaluated v2.'},indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'] if winner else 'no prefix improvement',flush=True)


if __name__=='__main__':main()
