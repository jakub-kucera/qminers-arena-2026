"""Persistent two-sided queues with paid inventory breaches and latency-bound hedges.

Uses the official 100-lot free threshold, 1000-lot acceptance wall, and full
10000/second penalty. Rank net PnL, never gross cash or unpenalized PnL.
"""
import json
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
from simulator.main import load_strategy_from_file
from scripts.benchmark import evaluate,digest
from scripts.search_passive import CandidateEngine
from scripts.check_submission import check

ROOT=Path('logs/round1/standing_liquidity')


def source_for(size,target):
    text=Path('strategies/round1_submission.py').read_text()
    text=text.replace('POSITION_LIMIT = 100','POSITION_LIMIT = 1000').replace('QUOTE_SIZE = 200',f'QUOTE_SIZE = {size}')
    text=text.replace('self.inventory/self.POSITION_LIMIT','self.inventory/100')
    text=text.replace('        self._orders = {}', '''        self._orders = {}
        self._hedge_id = None
        self._cached_bid = self._cached_ask = self._cached_time = None''',1)
    text=text.replace('quantity = min(self.QUOTE_SIZE, self.POSITION_LIMIT-sign*self.inventory-reserved)',
        'quantity = min(self.QUOTE_SIZE-reserved, self.POSITION_LIMIT-sign*self.inventory-reserved)')
    text=text.replace('prediction-skew > 0.3','prediction-skew > 2.1').replace('prediction-skew < -0.3','prediction-skew < -2.1')
    text=text.replace('self.inventory >= self.POSITION_LIMIT','self.inventory > 100').replace(
        'self.inventory <= -self.POSITION_LIMIT','self.inventory < -100')
    helper=f'''    def _hedge(self, now):
        if abs(self.inventory) <= 100 or self._hedge_id is not None:
            return
        if self._cached_time is None or now-self._cached_time > 100000:
            return
        sign = -1 if self.inventory > 0 else 1
        reserved = sum(r[2] for r in self._orders.values() if r[0] == sign)
        quantity = min(abs(self.inventory)-{target},max(0,self.POSITION_LIMIT-sign*self.inventory-reserved))
        if quantity <= 0:
            return
        price = self._cached_ask+10 if sign > 0 else max(1,self._cached_bid-10)
        oid = self.send_order(OrderRequest(side=Side.BUY if sign > 0 else Side.SELL,
            price=price,quantity=quantity,order_type=OrderType.IOC))
        self._orders[oid] = [sign,price,quantity,False,False,now]
        self._hedge_id = oid

'''
    text=text.replace('    def _cancel(self, order_id):',helper+'    def _cancel(self, order_id):')
    text=text.replace('        self._desired_buy,self._desired_sell,self._desired_time =',
        '        self._cached_bid,self._cached_ask,self._cached_time = bid,ask,now\n        self._hedge(now)\n        self._desired_buy,self._desired_sell,self._desired_time =')
    text=text.replace('''        if (self._desired_time is not None''','''        was_hedge = event.order_id == self._hedge_id
        if was_hedge and event.status in (OrderStatus.FILLED,OrderStatus.CANCELED,OrderStatus.REJECTED):
            self._hedge_id = None
        if (not was_hedge and self._desired_time is not None''')
    text+='''
        if was_hedge:
            self._hedge(event.timestamp_us)
'''
    return text


def run(source,data,out):
    s=load_strategy_from_file(Path(source))
    result=evaluate(s,Path(data),Path(out),600,CandidateEngine)
    assert result['max_potential_inventory_at_submission']<=1000
    result['source']=str(source);result['source_sha256']=digest(source)
    result['gross_pnl_before_penalty']=result['result']['pnl']+result['result']['breach_penalty']
    return result


def batch(names,data,stage):
    results={}
    with ProcessPoolExecutor(max_workers=4) as pool:
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
    for size in (100,300,600,900):
        for target in (0,100):
            name=f'standing_{size}_hedge_{target}'
            path=ROOT/'sources'/(name+'.py');path.write_text(source_for(size,target))
            assert not check(path),check(path)
            specs[name]=dict(size=size,hedge_target=target,source_sha256=digest(path))
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=batch(specs,'logs/round1/screening.csv','screening')
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:2]
    full=batch(finalists,'data/round1.csv','full')
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],parameters=specs[winner]),indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
