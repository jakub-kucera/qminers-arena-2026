"""Net-PnL test of larger resting quotes with explicit charged breach time.

This experiment intentionally permits short excursions beyond the penalty-free
100-lot threshold; the official 10000/second penalty remains enabled.
"""
import json
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
from scripts.check_submission import check
from scripts.benchmark import digest,evaluate
from scripts.search_passive import CandidateEngine
from simulator.main import load_strategy_from_file

ROOT=Path('logs/round1/burst')


def run(source,data,out):
    s=load_strategy_from_file(source)
    r=evaluate(s,Path(data),Path(out),600,CandidateEngine)
    r['source']=str(source);r['source_sha256']=digest(source)
    assert r['max_potential_inventory_at_submission']<=400
    return r


def batch(names,data,stage):
    results={}
    with ProcessPoolExecutor(max_workers=3) as pool:
        jobs={pool.submit(run,ROOT/'sources'/(n+'.py'),data,ROOT/stage/n):n for n in names}
        for job in as_completed(jobs):
            n=jobs[job];r=job.result();results[n]=r
            print(stage,n,'net pnl',r['result']['pnl'],'penalty',r['result']['breach_penalty'],
                  'peak inventory',r['max_abs_inventory'],flush=True)
    (ROOT/(stage+'.json')).write_text(json.dumps(results,indent=2)+'\n');return results


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    base=Path('logs/round1/target550/sources/execution_13.py').read_text()
    specs={}
    for index,(gross,stop) in enumerate(((150,50),(150,100),(250,50),(250,100))):
        n=f'burst_{index}'
        text=base.replace('POSITION_LIMIT = 100','POSITION_LIMIT = 400')
        text=text.replace('self.POSITION_LIMIT-sign*self.inventory-reserved',f'min({gross}-reserved,self.POSITION_LIMIT-sign*self.inventory-reserved)')
        text=text.replace('self.inventory >= self.POSITION_LIMIT',f'self.inventory >= {stop}').replace('self.inventory <= -self.POSITION_LIMIT',f'self.inventory <= -{stop}')
        text=text.replace('        self._orders = {}','''        self._orders = {}
        self._hedge_id = None
        self._cached_bid = self._cached_ask = None''',1)
        helper='''    def _hedge(self, now):
        if abs(self.inventory) <= 100 or self._hedge_id is not None:
            return
        if self._cached_bid is None or self._cached_ask is None:
            return
        sign = -1 if self.inventory > 0 else 1
        reserved = sum(r[2] for r in self._orders.values() if r[0] == sign)
        quantity = min(abs(self.inventory)-100,max(0,self.POSITION_LIMIT-sign*self.inventory-reserved))
        if quantity <= 0:
            return
        price = self._cached_ask+1 if sign > 0 else max(1,self._cached_bid-1)
        oid = self.send_order(OrderRequest(side=Side.BUY if sign > 0 else Side.SELL,
            price=price,quantity=quantity,order_type=OrderType.IOC))
        self._orders[oid] = [sign,price,quantity,False,False,now]
        self._hedge_id = oid

'''
        text=text.replace('    def _cancel(',helper+'    def _cancel(',1)
        text=text.replace('        mid = (bid+ask)*0.5','        self._cached_bid,self._cached_ask = bid,ask\n        mid = (bid+ask)*0.5')
        text=text.replace('        self._quote(now,1,buy)','        self._hedge(now)\n        self._quote(now,1,buy)')
        text+='''
        if event.order_id == self._hedge_id and event.status in (OrderStatus.FILLED,OrderStatus.CANCELED,OrderStatus.REJECTED):
            self._hedge_id = None
        self._hedge(event.timestamp_us)
'''
        path=ROOT/'sources'/(n+'.py');path.write_text(text)
        assert not check(path),check(path)
        specs[n]={'gross_resting_target':gross,'stop_adding_at_inventory':stop,'hard_bound':400,'sha256':digest(path)}
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=batch(specs,'logs/round1/screening.csv','screening')
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:2]
    finalists=[n for n in finalists if screen[n]['result']['pnl']>142000]
    full=batch(finalists,'data/round1.csv','full') if finalists else {}
    winner=max(full,key=lambda n:full[n]['result']['pnl']) if full else None
    (ROOT/'winner.json').write_text(json.dumps({'name':winner,'parameters':specs.get(winner),'result':full.get(winner)},indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'] if winner else 'no prefix improvement',flush=True)


if __name__=='__main__':main()
