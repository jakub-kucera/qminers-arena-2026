"""Full primary liquidity plus deeper standing quotes under native charged risk.

Unlike a 100-lot split ladder, this uses the documented 1000-lot acceptance
wall. Actual excursions beyond 100 are charged at 10000/s and hedged with the
same 5ms delay. Only NET native PnL is used for ranking.
"""
import json
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
from scripts.round1_standing_liquidity import source_for as standing_source,run
from scripts.check_submission import check
from scripts.benchmark import digest
from scripts.round1_pending_cancel import fix_pending_rejections

ROOT=Path('logs/round1/overbooked_depth')


def source_for(levels,size):
    text=standing_source(200,100)
    text=text.replace('prediction-skew > 2.1','prediction-skew > 0.3').replace('prediction-skew < -2.1','prediction-skew < -0.3')
    text=text.replace('self.inventory > 100','self.inventory >= 100').replace('self.inventory < -100','self.inventory <= -100')
    text=text.replace('if record[3] and not record[4]:','if not record[4]:')
    text=text.replace('        self._orders = {}','        self._orders = {}\n        self._raw_quotes = {1:None,-1:None}',1)
    text=text.replace('        # Withdraw the side','        self._raw_quotes = {1:buy,-1:sell}\n        # Withdraw the side')
    start=text.index('    def _quote(');end=text.index('    def on_order_book_change',start)
    method=f'''    def _quote(self, now, sign, price):
        hedge_reserved=sum(r[2] for oid,r in self._orders.items() if r[0]==sign and oid==self._hedge_id)
        targets={{}}
        if price is not None:
            targets[price]=max(0,100-sign*self.inventory-hedge_reserved)
        raw=self._raw_quotes[sign]
        if raw is not None and sign*self.inventory<=100:
            for i in range(1,{levels+1}):
                level=raw-sign*i
                if level>0:
                    targets[level]=max(targets.get(level,0),{size})
        if sign*self.inventory>100:
            targets={{}}
        current=[(oid,r) for oid,r in self._orders.items() if r[0]==sign and oid!=self._hedge_id]
        for oid,r in current:
            if r[1] not in targets or targets[r[1]]<=0:
                self._cancel(oid)
        for level,target in targets.items():
            at_level=[(oid,r) for oid,r in current if r[1]==level]
            excess=sum(r[2] for oid,r in at_level)-target
            for oid,r in reversed(at_level):
                if excess<=0:break
                reduction=min(r[2],excess)
                if reduction==r[2]:
                    self._cancel(oid)
                elif r[3] and not r[4] and r[6] is None:
                    r[6]=r[2]-reduction
                    self.modify_order(oid,r[6])
                excess-=reduction
        reserved=sum(r[2] for r in self._orders.values() if r[0]==sign)
        free=self.POSITION_LIMIT-sign*self.inventory-reserved
        for level,target in targets.items():
            if free<=0 or len(current)>=32:break
            at_level=sum(r[2] for oid,r in current if r[1]==level and not r[4])
            quantity=min(self.QUOTE_SIZE,free,target-at_level)
            if quantity<=0:continue
            oid=self.send_order(OrderRequest(side=Side.BUY if sign>0 else Side.SELL,
                price=level,quantity=quantity,order_type=OrderType.LIMIT))
            record=[sign,level,quantity,False,False,now,None]
            self._orders[oid]=record;current.append((oid,record));free-=quantity

'''
    text=text[:start]+method+text[end:]
    text=text.replace('self._orders[oid] = [sign,price,quantity,False,False,now]',
                      'self._orders[oid] = [sign,price,quantity,False,False,now,None]')
    text=text.replace('''        elif event.status == OrderStatus.CANCELED:''','''        elif event.status == OrderStatus.MODIFIED:
            record[2]=event.remaining_quantity
            record[6]=None
        elif event.status == OrderStatus.CANCELED:''')
    text=text.replace('''            else:
                record[4] = False''','''            else:
                record[4] = False
                record[6] = None''')
    return fix_pending_rejections(text)


def batch(names,data,stage):
    results={}
    with ProcessPoolExecutor(max_workers=3) as pool:
        jobs={pool.submit(run,ROOT/'sources'/(name+'.py'),data,ROOT/stage/name):name for name in names}
        for job in as_completed(jobs):
            name=jobs[job];r=job.result();results[name]=r
            print(stage,name,'NET',r['result']['pnl'],'penalty',r['result']['breach_penalty'],
                  'maxI',r['max_abs_inventory'],flush=True)
    (ROOT/(stage+'.json')).write_text(json.dumps(results,indent=2)+'\n');return results


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    specs={}
    for levels,size in ((1,50),(1,100),(2,50),(2,100),(3,50),(3,100),(2,200)):
        name=f'depth_{levels}_size_{size}'
        path=ROOT/'sources'/(name+'.py');path.write_text(source_for(levels,size))
        assert not check(path),check(path)
        specs[name]=dict(levels=levels,size=size,source_sha256=digest(path))
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=batch(specs,'logs/round1/screening.csv','screening')
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    full=batch(finalists,'data/round1.csv','full')
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],parameters=specs[winner],
        limitation='Sample tuning. Potential exposure can exceed 100; actual breaches incur the full native penalty.'),indent=2)+'\n')
    print('WINNER OVERBOOKED DEPTH',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
