"""Sample tuning of quoting while fully-reserved cancels are pending."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/sample_v2/pending_search')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT
    base=Path('logs/sample_v2/target310/sources/variant_04.py').read_text()
    old='''        for oid,record in current:
            if price is None or record[1] != price:
                self._cancel(oid)
                changing = True
        if changing or any(record[4] for oid,record in current):
            return'''
    assert old in base
    specs={}
    configs=[(0,0,False),(0,0,True)]
    configs += [(ticks,age,True) for ticks in (1,2) for age in (100_000,500_000,2_000_000,10_000_000)]
    for index,(ticks,age,overlap) in enumerate(configs):
        n=f'pending_{index:02d}'
        replacement=f'''        for oid,record in current:
            if price is None:
                self._cancel(oid)
                changing = True
            elif record[1] != price:
                favorable = (price-record[1])*sign > 0
                keep = favorable and abs(price-record[1]) <= {ticks} and now-record[5] < {age}
                if not keep:
                    self._cancel(oid)
                    changing = True
'''
        if not overlap:
            replacement+='''        if changing or any(record[4] for oid,record in current):
            return
'''
        text=base.replace(old,replacement.rstrip())
        path=ROOT/'sources'/(n+'.py');path.write_text(text)
        assert not check(path),check(path)
        specs[n]={'keep_ticks':ticks,'max_age_us':age,'allow_cancel_overlap':overlap,'sha256':digest(path)}
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/sample_v2/search/screening.csv','screening')
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    (ROOT/'finalists.json').write_text(json.dumps(finalists,indent=2)+'\n')
    full=search_queue.batch(finalists,'data/sample_v2.csv','full')
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps({'name':winner,'parameters':specs[winner],
        'result':full[winner],'limitation':'Tuned on previously evaluated v2.'},indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
