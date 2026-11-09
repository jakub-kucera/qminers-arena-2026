"""Round-1 sample tuning of forecast-triggered IOC hedges with reserved capacity."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.check_submission import check
from scripts.benchmark import digest

ROOT=Path('logs/round1/hybrid')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT
    base=Path('logs/round1/target550/sources/execution_13.py').read_text()
    specs={}
    configs=[(100,t,100,True) for t in (.05,.1,.2,.3,.5)]
    configs += [(80,t,20,mode) for t in (.1,.2) for mode in (True,False)]
    for index,(maker_cap,threshold,lot,closing) in enumerate(configs):
        n=f'hybrid_{index:02d}'
        text=base.replace('        self._orders = {}','        self._orders = {}\n        self._last_taker_us = -50000',1)
        text=text.replace('self.POSITION_LIMIT-sign*self.inventory-reserved',f'{maker_cap}-sign*self.inventory-reserved')
        block=f'''        if self._labels >= self.MIN_LABELS and abs(prediction) > {threshold} and now-self._last_taker_us >= 50000:
            direction = 1 if prediction > 0 else -1
            if {not closing} or direction*self.inventory < 0:
                reserved = sum(r[2] for r in self._orders.values() if r[0] == direction)
                free = max(0,self.POSITION_LIMIT-direction*self.inventory-reserved)
                available = aq if direction > 0 else bq
                quantity = min({lot},free,available)
'''
        if closing:
            block+='''                quantity = min(quantity,abs(self.inventory))
'''
        block+='''                if quantity > 0:
                    price = ask if direction > 0 else bid
                    oid = self.send_order(OrderRequest(side=Side.BUY if direction > 0 else Side.SELL,
                        price=price,quantity=quantity,order_type=OrderType.IOC))
                    self._orders[oid] = [direction,price,quantity,False,False,now]
                    self._last_taker_us = now
'''
        text=text.replace('        self._quote(now,1,buy)',block+'        self._quote(now,1,buy)')
        path=ROOT/'sources'/(n+'.py');path.write_text(text)
        assert not check(path),check(path)
        specs[n]={'maker_cap':maker_cap,'trigger':threshold,'ioc_lot':lot,'closing_only':closing,'sha256':digest(path)}
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/round1/screening.csv','screening')
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    finalists=[n for n in finalists if screen[n]['result']['pnl']>141000]
    full=search_queue.batch(finalists,'data/round1.csv','full') if finalists else {}
    winner=max(full,key=lambda n:full[n]['result']['pnl']) if full else None
    (ROOT/'winner.json').write_text(json.dumps({'name':winner,'parameters':specs.get(winner),
        'result':full.get(winner),'limitation':'Further tuning on already evaluated round-1 data.'},indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'] if winner else 'no prefix improvement',flush=True)


if __name__=='__main__':main()
