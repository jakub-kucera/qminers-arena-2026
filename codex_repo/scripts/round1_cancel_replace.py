"""Pipeline replacements before cancel acknowledgments, charging all real breaches.

The free threshold stays 100 and acceptance wall 1000. Replacement overlap
deliberately relaxes only the strategy's provisional reservation, and every
result includes the native penalty and 5ms hedge latency.
"""
import json
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
from scripts.round1_standing_liquidity import source_for as standing_source,run
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/cancel_replace')


def source_for(release,private):
    text=standing_source(200,100)
    text=text.replace('prediction-skew > 2.1','prediction-skew > 0.3').replace('prediction-skew < -2.1','prediction-skew < -0.3')
    text=text.replace('self.inventory > 100','self.inventory >= 100').replace('self.inventory < -100','self.inventory <= -100')
    # Restore hedge trigger's original strict comparison after changing quote vetoes.
    text=text.replace('sign = -1 if self.inventory >= 100 else 1','sign = -1 if self.inventory > 0 else 1')
    old='quantity = min(self.QUOTE_SIZE-reserved, self.POSITION_LIMIT-sign*self.inventory-reserved)'
    assert old in text
    text=text.replace(old,f'''effective=sum(ceil(r[2]*(1-{release})) if r[4] else r[2] for r in self._orders.values() if r[0]==sign)
        quantity=min(self.QUOTE_SIZE,100-sign*self.inventory-effective,
                     self.POSITION_LIMIT-sign*self.inventory-reserved)''')
    if private:
        text=text.replace('''        if was_hedge:
            self._hedge(event.timestamp_us)''','''        if was_hedge or event.status in (OrderStatus.FILLED,OrderStatus.PARTIALLY_FILLED):
            self._hedge(event.timestamp_us)''')
    return text


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
    for release in (0.0,0.25,0.5,0.75,1.0):
        for private in ((False,) if release==0 else (False,True)):
            name=f'release_{release}_private_{private}'
            path=ROOT/'sources'/(name+'.py');path.write_text(source_for(release,private))
            assert not check(path),check(path)
            specs[name]=dict(released_cancel_reservation_fraction=release,private_hedge=private,source_sha256=digest(path))
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=batch(specs,'logs/round1/screening.csv','screening')
    assert screen['release_0.0_private_False']['result']['pnl']==162623
    assert screen['release_0.0_private_False']['result']['breach_penalty']==0
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    full=batch(finalists,'data/round1.csv','full')
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],parameters=specs[winner],
        limitation='Sample tuning. Actual inventory can exceed 100 temporarily; native penalties are included in net PnL.'),indent=2)+'\n')
    print('WINNER CANCEL REPLACE',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
