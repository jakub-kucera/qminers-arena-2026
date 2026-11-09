"""V2 tuning of private-feed replenishment using bounded-age public quotes."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/sample_v2/private_search')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT
    base=Path('logs/sample_v2/target310/sources/variant_04.py').read_text()
    specs={}
    for age in (5000,20000,100000):
        for mode in ('fill','cancel','all'):
            n=f'private_{age}_{mode}'
            text=base.replace('        self._orders = {}','''        self._orders = {}
        self._desired_buy = None
        self._desired_sell = None
        self._desired_time = None''',1)
            text=text.replace('        if bid is None or ask is None or bid >= ask:', '''        if bid is None or ask is None or bid >= ask:
            self._desired_time = None''')
            text=text.replace('        self._quote(now,1,buy)','''        self._desired_buy, self._desired_sell, self._desired_time = buy, sell, now
        self._quote(now,1,buy)''')
            statuses={'fill':'(OrderStatus.PARTIALLY_FILLED,OrderStatus.FILLED)',
                      'cancel':'(OrderStatus.CANCELED,)',
                      'all':'(OrderStatus.PARTIALLY_FILLED,OrderStatus.FILLED,OrderStatus.CANCELED)'}[mode]
            text+=f'''
        if self._desired_time is not None and 0 <= event.timestamp_us-self._desired_time <= {age} and event.status in {statuses}:
            self._quote(event.timestamp_us,1,self._desired_buy)
            self._quote(event.timestamp_us,-1,self._desired_sell)
'''
            path=ROOT/'sources'/(n+'.py');path.write_text(text)
            assert not check(path),check(path)
            specs[n]={'max_cache_age_us':age,'events':mode,'sha256':digest(path)}
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/sample_v2/search/screening.csv','screening')
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    (ROOT/'finalists.json').write_text(json.dumps(finalists,indent=2)+'\n')
    full=search_queue.batch(finalists,'data/sample_v2.csv','full')
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps({'name':winner,'parameters':specs[winner],
        'result':full[winner],'limitation':'Tuned on previously evaluated v2.'},indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
