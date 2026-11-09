"""V2 tuning of bounded quote persistence through small price changes."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/sample_v2/persistence_search')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT
    base=Path('logs/sample_v2/target310/sources/variant_04.py').read_text()
    old='''            if price is None or record[1] != price:
                self._cancel(oid)
                changing = True'''
    assert old in base
    specs={}
    configs=[(age,1) for age in (20000,50000,100000,250000,500000,1000000,2000000)]
    configs += [(250000,2),(500000,2),(1000000,2)]
    for age,ticks in configs:
        n=f'persist_{age}_{ticks}'
        new=f'''            if price is None:
                self._cancel(oid)
                changing = True
            elif record[1] != price:
                if now-record[5] < {age} and abs(price-record[1]) <= {ticks}:
                    continue
                self._cancel(oid)
                changing = True'''
        text=base.replace(old,new)
        path=ROOT/'sources'/(n+'.py');path.write_text(text)
        assert not check(path),check(path)
        specs[n]={'max_age_us':age,'max_distance_ticks':ticks,'sha256':digest(path)}
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/sample_v2/search/screening.csv','screening')
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    (ROOT/'finalists.json').write_text(json.dumps(finalists,indent=2)+'\n')
    full=search_queue.batch(finalists,'data/sample_v2.csv','full')
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps({'name':winner,'parameters':specs[winner],
        'result':full[winner],'limitation':'Tuned on previously evaluated v2 data.'},indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
