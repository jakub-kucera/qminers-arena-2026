"""Preserve valuable quotes ahead of market-only touch; compare public-touch anchoring."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/own_quote_reference')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT;base=Path('strategies/round1_private_554347.py').read_text();candidates={}
    for edge in (0.0,0.1,0.2,0.3):
        for ahead in (0,100):
            text=base.replace('        self._orders = {}', '''        self._orders = {}
        self._market_fair = 0.0
        self._market_touch = {1:0,-1:0}''',1)
            text=text.replace('        self._desired_buy,self._desired_sell,self._desired_time =',
                '        self._market_fair = mid+prediction-skew\n        self._market_touch = {1:bid,-1:ask}\n        self._desired_buy,self._desired_sell,self._desired_time =')
            text=text.replace('''            if price is None or record[1] != price:
                self._cancel(oid)
                changing = True''',f'''            if price is None or record[1] != price:
                keep=(price is not None and record[3] and not record[4]
                      and sign*(record[1]-self._market_touch[sign])>=0
                      and sign*(self._market_fair-record[1])>={edge}
                      and self.queue_ahead.get(oid,1000000)<={ahead})
                if not keep:
                    self._cancel(oid)
                    changing = True''')
            candidates[f'keep_edge_{edge}_ahead_{ahead}']=text
    for weight in (0.5,1.0):
        text=base.replace('        fair = mid + ',f'''        public_bid,public_ask = snapshot.bids[0].price,snapshot.asks[0].price
        if public_bid>=public_ask:
            public_bid,public_ask = bid,ask
        quote_mid=mid+{weight}*((public_bid+public_ask)*0.5-mid)
        fair = quote_mid + ''')
        text=text.replace('abs(fair-mid) <= 0.1','abs(fair-quote_mid) <= 0.1').replace(
            '            fair = mid\n','            fair = quote_mid\n')
        text=text.replace('buy = min(bid,floor','buy = min(public_bid,floor').replace(
            'sell = max(ask,ceil','sell = max(public_ask,ceil')
        candidates[f'public_fair_{weight}']=text
    specs={}
    for name,text in candidates.items():
        path=ROOT/'sources'/(name+'.py');path.write_text(text)
        assert not check(path),check(path)
        specs[name]=dict(source_sha256=digest(path))
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/round1/screening.csv','screening',workers=4)
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    full=search_queue.batch(finalists,'data/round1.csv','full',workers=3)
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],parameters=specs[winner],
        limitation='Sample tuning; all queue ranks and touch references are from current public snapshots.'),indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
