"""Delay new liquidity briefly after market-price changes; cancel stale quotes immediately."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/price_stability')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT;base=Path('strategies/round1_private_554347.py').read_text();specs={}
    for scope in ('side','both'):
        for lag in (1000,2000,5000,10000,20000,50000):
            name=f'{scope}_{lag}'
            text=base.replace('        self._orders = {}', '''        self._orders = {}
        self._market_touch = None
        self._price_changed = {1:0,-1:0}''',1)
            text=text.replace('            self._previous_touch = None\n',
                              '            self._previous_touch = None\n            self._market_touch = None\n')
            text=text.replace('        mid = (bid+ask)*0.5', '''        if self._market_touch is None or bid != self._market_touch[0]:
            self._price_changed[1] = now
        if self._market_touch is None or ask != self._market_touch[1]:
            self._price_changed[-1] = now
        self._market_touch = (bid,ask)
        mid = (bid+ask)*0.5''')
            stamp='self._price_changed[sign]' if scope=='side' else 'max(self._price_changed.values())'
            text=text.replace('        if len(current) >= 8:', f'''        if now-{stamp} < {lag}:
            return
        if len(current) >= 8:''')
            path=ROOT/'sources'/(name+'.py');path.write_text(text)
            assert not check(path),check(path)
            specs[name]=dict(scope=scope,lag_us=lag,source_sha256=digest(path))
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/round1/screening.csv','screening',workers=4)
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    full=search_queue.batch(finalists,'data/round1.csv','full',workers=3)
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],parameters=specs[winner],
        limitation='Sample-tuned, all price-change timestamps derive only from already received public snapshots.'),indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
