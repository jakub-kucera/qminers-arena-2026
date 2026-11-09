"""Causal separation of near-touch arrivals, cancellations, and traded removals."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/liquidity_model')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT
    base=Path('logs/round1/nonlinear/sources/nonlinear_8_0.001_100000.py').read_text()
    specs={}
    for mode in ('count','volume'):
        for tau in (100000,500000):
            n=f'liquidity_{mode}_{tau}'
            text=base.replace('FEATURE_COUNT = 8','FEATURE_COUNT = 10')
            text=text.replace('        self._orders = {}','''        self._orders = {}
        self._previous_market = None
        self._liquidity_best = None
        self._liquidity_time = None
        self._arrivals = self._cancellations = 0.0''',1)
            text=text.replace('            self._previous_touch = None','            self._previous_touch = None\n            self._previous_market = None',1)
            calculation=f'''        elapsed_liquidity = 0 if self._liquidity_time is None else max(0,now-self._liquidity_time)
        self._liquidity_time = now
        self._arrivals *= exp(-elapsed_liquidity/{tau})
        self._cancellations *= exp(-elapsed_liquidity/{tau})
        if elapsed_liquidity > 10000000:
            self._previous_market = None
        current_market = {{o.order_id:o for orders in (snapshot.bids,snapshot.asks) for o in orders if o.owner == 'market'}}
        if self._previous_market is not None:
            traded = {{}}
            for trade in trades:
                if trade.maker_owner == 'market':
                    traded[trade.maker_order_id] = traded.get(trade.maker_order_id,0)+trade.quantity
            for oid,order in current_market.items():
                if oid in self._previous_market:
                    continue
                direction = 1 if order.side == Side.BUY else -1
                distance = bid-order.price if direction > 0 else order.price-ask
                if distance <= 1:
                    self._arrivals += direction*VALUE_ARRIVAL
            old_bid,old_ask = self._liquidity_best
            for oid,order in self._previous_market.items():
                if oid in current_market:
                    continue
                remaining = order.quantity-traded.get(oid,0)
                direction = 1 if order.side == Side.BUY else -1
                distance = old_bid-order.price if direction > 0 else order.price-old_ask
                if remaining > 0 and distance <= 1:
                    self._cancellations -= direction*VALUE_CANCEL
        self._previous_market = current_market
        self._liquidity_best = (bid,ask)
'''
            calculation=calculation.replace('VALUE_ARRIVAL','(1.0/5)' if mode=='count' else '(order.quantity/max(1,bq+aq))')
            calculation=calculation.replace('VALUE_CANCEL','(1.0/5)' if mode=='count' else '(remaining/max(1,bq+aq))')
            text=text.replace('        ofi = max(-3,min(3,self._ofi))',calculation+'        ofi = max(-3,min(3,self._ofi))')
            text=text.replace('ofi*abs(ofi))','ofi*abs(ofi),max(-3,min(3,self._arrivals)),max(-3,min(3,self._cancellations)))')
            path=ROOT/'sources'/(n+'.py');path.write_text(text)
            assert not check(path),check(path)
            specs[n]={'mode':mode,'kernel_us':tau,'sha256':digest(path)}
    (ROOT/'specifications.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/round1/screening.csv','screening')
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:2]
    finalists=[n for n in finalists if screen[n]['result']['pnl']>147000]
    full=search_queue.batch(finalists,'data/round1.csv','full') if finalists else {}
    winner=max(full,key=lambda n:full[n]['result']['pnl']) if full else None
    (ROOT/'winner.json').write_text(json.dumps({'name':winner,'parameters':specs.get(winner),
        'result':full.get(winner),'limitation':'Further tuning on already evaluated round-1 data.'},indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'] if winner else 'no prefix improvement',flush=True)


if __name__=='__main__':main()
