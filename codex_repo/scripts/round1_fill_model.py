"""Learn conditional passive markouts from already observed market trades."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/fill_model')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT
    base=Path('strategies/round1_best.py').read_text()
    specs={}
    for horizon in (100000,500000):
        for threshold in (0,.2,.4):
            n=f'fill_{horizon}_{threshold}'
            text=base.replace('FEATURE_COUNT = 5','FEATURE_COUNT = 6').replace('HORIZON_US = 100000',f'HORIZON_US = {horizon}')
            text=text.replace('deque(maxlen=64)','deque(maxlen=4096)')
            text=text.replace('        self._orders = {}','        self._orders = {}\n        self._virtual_frame = None',1)
            text=text.replace('observed_us, old_mid, features = self._observations.popleft()',
                              'observed_us, old_mid, features, direction = self._observations.popleft()')
            text=text.replace('mid - old_mid','direction * (mid - old_mid)')
            text=text.replace('        now = snapshot.timestamp_us','''        now = snapshot.timestamp_us
        seen = set()
        if self._virtual_frame is not None:
            old_bid,old_ask,old_flow,old_momentum,old_imbalance,old_ofi,old_spread = self._virtual_frame
            for trade in trades:
                if trade.taker_owner != 'market' or trade.book_side in seen:
                    continue
                direction = 1 if trade.book_side == 'bid' else -1
                price = old_bid if direction > 0 else old_ask
                if trade.price != price:
                    continue
                seen.add(trade.book_side)
                features = (1,direction*old_flow,direction*old_imbalance,
                            direction*old_ofi,old_spread,direction*old_momentum)
                self._observations.append((trade.timestamp_us,price,features,direction))''',1)
            text=text.replace('            self._previous_touch = None','            self._previous_touch = None\n            self._virtual_frame = None',1)
            start=text.index('        features=(flow,')
            end=text.index('        # Withdraw the side',start)
            replacement=f'''        momentum = max(-5,min(5,self._fast_mid-self._slow_mid))
        ofi = max(-3,min(3,self._ofi))
        self._learn(now,mid)
        self._virtual_frame = (bid,ask,flow,momentum,imbalance,ofi,spread)
        buy,sell = bid,ask
        if self._labels >= self.MIN_LABELS:
            buy_features = (1,flow,imbalance,ofi,spread,momentum)
            sell_features = (1,-flow,-imbalance,-ofi,spread,-momentum)
            buy_edge = sum(w*x for w,x in zip(self._weights,buy_features))
            sell_edge = sum(w*x for w,x in zip(self._weights,sell_features))
            if buy_edge < {threshold} and self.inventory >= 0:
                buy = bid-1
            if sell_edge < {threshold} and self.inventory <= 0:
                sell = ask+1
'''
            text=text[:start]+replacement+text[end:]
            path=ROOT/'sources'/(n+'.py');path.write_text(text)
            assert not check(path),check(path)
            specs[n]={'horizon_us':horizon,'minimum_edge':threshold,'sha256':digest(path)}
    (ROOT/'specifications.json').write_text(json.dumps(specs,indent=2)+'\n')
    screened=search_queue.batch(specs,'logs/round1/screening.csv','screening')
    finalists=sorted(screened,key=lambda n:screened[n]['result']['pnl'],reverse=True)[:2]
    full=search_queue.batch(finalists,'data/round1.csv','full')
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps({'name':winner,'parameters':specs[winner],
        'result':full[winner],'limitation':'Further tuning on already evaluated round-1 data.'},indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
