"""Further v2 sample tuning after the original validation tail was consumed.

No out-of-sample claim is made by this search. All fills and pending exposure
are checked against the configured inventory bound by CandidateEngine.
"""
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from scripts.benchmark import digest
from scripts.check_submission import check
from scripts.search_passive import run


ROOT=Path('logs/sample_v2/challenge')


def batch(names,data,stage):
    results={}
    with ProcessPoolExecutor(max_workers=3) as pool:
        jobs={pool.submit(run,ROOT/'sources'/(n+'.py'),data,ROOT/stage/n):n for n in names}
        for job in as_completed(jobs):
            name=jobs[job]
            r=job.result()
            results[name]=r
            print(stage,name,'pnl',r['result']['pnl'],'dd',r['max_drawdown_1s'],
                  'inventory',r['max_abs_inventory'],flush=True)
    (ROOT/(stage+'.json')).write_text(json.dumps(results,indent=2)+'\n')
    return results


def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    if (ROOT/'screening.json').exists():
        raise SystemExit('Search results already exist; inspect them before starting a new search.')
    (ROOT/'sources').mkdir(exist_ok=True)
    # (cap, quote size, inventory skew, imbalance coefficient, cooldown microseconds)
    configs=[(100,60,.25,.25,50000),(100,100,.25,.25,50000),
        (100,200,.25,.25,50000),(100,100,0,0,50000),
        (100,200,0,0,5000),(100,100,.1,.25,5000),
        (100,200,.1,.25,5000),(100,100,.25,.5,5000),
        (100,100,.5,.5,5000),(100,200,0,.5,5000),
        (100,100,0,.25,5000),(100,200,0,0,50000),
        (100,200,.1,0,5000),(100,100,.1,0,5000),
        (95,200,0,0,5000),(90,200,0,0,5000)]
    specs={}
    template=Path('strategies/passive_v2_q60.py').read_text()
    for index,(cap,size,skew,alpha,cooldown) in enumerate(configs):
        name=f'candidate_{index:02d}'
        text=template.replace('POSITION_LIMIT = 90',f'POSITION_LIMIT = {cap}')
        text=text.replace('QUOTE_SIZE = 60',f'QUOTE_SIZE = {size}')
        text=text.replace('REQUOTE_US = 50_000',f'REQUOTE_US = {cooldown}')
        text=text.replace('{-1:-50_000, 1:-50_000}',f'{{-1:-{cooldown}, 1:-{cooldown}}}')
        text=text.replace('skew = 0.25 *',f'skew = {skew} *')
        text=text.replace('fair = mid + 0.25*spread*imbalance',f'fair = mid + {alpha}*spread*imbalance')
        path=ROOT/'sources'/(name+'.py'); path.write_text(text)
        assert not check(path),check(path)
        specs[name]={'cap':cap,'quote_size':size,'skew':skew,'imbalance':alpha,'cooldown_us':cooldown,
                     'source_sha256':digest(path)}
    (ROOT/'specifications.json').write_text(json.dumps(specs,indent=2)+'\n')
    screened=batch(specs,'logs/sample_v2/search/screening.csv','screening')
    ranked=sorted(screened,key=lambda n:screened[n]['result']['pnl'],reverse=True)
    # Compare the best three plus the best candidate retaining a margin to 100.
    margin=max((n for n in specs if specs[n]['cap']<100),key=lambda n:screened[n]['result']['pnl'])
    finalists=list(dict.fromkeys(ranked[:3]+[margin]))
    (ROOT/'finalists.json').write_text(json.dumps(finalists,indent=2)+'\n')
    full=batch(finalists,'data/sample_v2.csv','full')
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps({'name':winner,'parameters':specs[winner],
        'result':full[winner],'limitation':'Tuned on v2; its original reserved tail was already evaluated.'},indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':
    main()
