"""Sample-v2 tuning of favorable quote retention to preserve queue priority."""
import json
from concurrent.futures import ProcessPoolExecutor,as_completed
from pathlib import Path
from scripts.search_passive import run
from scripts.check_submission import check
from scripts.benchmark import digest

ROOT=Path('logs/sample_v2/queue_search')


def batch(names,data,stage,workers=3):
    results={}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        jobs={pool.submit(run,ROOT/'sources'/(n+'.py'),data,ROOT/stage/n):n for n in names}
        for job in as_completed(jobs):
            n=jobs[job]; r=job.result(); results[n]=r
            print(stage,n,'pnl',r['result']['pnl'],'dd',r['max_drawdown_1s'],flush=True)
    (ROOT/(stage+'.json')).write_text(json.dumps(results,indent=2)+'\n')
    return results


def main():
    ROOT.mkdir(parents=True,exist_ok=True); (ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists(): raise SystemExit('Results already exist')
    base=Path('strategies/passive_v2_q60.py').read_text()
    base=base.replace('POSITION_LIMIT = 90','POSITION_LIMIT = 100').replace('QUOTE_SIZE = 60','QUOTE_SIZE = 200')
    base=base.replace('REQUOTE_US = 50_000','REQUOTE_US = 5000').replace('{-1:-50_000, 1:-50_000}','{-1:-5000, 1:-5000}')
    base=base.replace('skew = 0.25 *','skew = 0.1 *')
    old='''            if price is None or record[1] != price:
                self._cancel(current)'''
    assert old in base
    specs={}
    for ticks in (1,2,4):
        for age in (500_000,2_000_000,10_000_000):
            name=f'keep_{ticks}_{age}'
            new=f'''            if price is None:
                self._cancel(current)
            elif record[1] != price:
                favorable = (price - record[1]) * sign > 0
                if favorable and abs(price-record[1]) <= {ticks} and now-record[5] < {age}:
                    return
                self._cancel(current)'''
            source=ROOT/'sources'/(name+'.py');source.write_text(base.replace(old,new))
            assert not check(source),check(source)
            specs[name]={'favorable_ticks':ticks,'max_age_us':age,'sha256':digest(source)}
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=batch(specs,'logs/sample_v2/search/screening.csv','screening')
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    (ROOT/'finalists.json').write_text(json.dumps(finalists,indent=2)+'\n')
    full=batch(finalists,'data/sample_v2.csv','full')
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps({'name':winner,'result':full[winner],
        'parameters':specs[winner],'limitation':'Further sample tuning after prior validation was consumed.'},indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__': main()
