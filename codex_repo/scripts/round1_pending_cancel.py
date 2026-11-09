"""Cancel stale pending orders without waiting for their acceptance notification."""
import json
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
from scripts.round1_cancel_replace import source_for as replacement_source
from scripts.round1_standing_liquidity import run
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/pending_cancel')


def fix_pending_rejections(text):
    """A rejected cancellation does not reject the original submission.

    Native batching can report cancel rejection before original acceptance
    at the same timestamp. Preserve its reservation and retry after ACCEPTED.
    """
    text=text.replace('        self._orders = {}','        self._orders = {}\n        self._cancel_requested = set()',1)
    text=text.replace('        record = self._orders[order_id]\n',
                      '        record = self._orders[order_id]\n        self._cancel_requested.add(order_id)\n',1)
    start=text.index('        elif event.status == OrderStatus.REJECTED:')
    end=text.index('        was_hedge = ',start)
    branch='''        elif event.status == OrderStatus.REJECTED:
            cancel_rejection=event.message is not None and 'cancel rejected:' in event.message
            if cancel_rejection:
                record[4]=False
            elif not record[3]:
                del self._orders[event.order_id]
                self._cancel_requested.discard(event.order_id)
            else:
                record[4]=False
                if len(record)>6:
                    record[6]=None
        if event.status==OrderStatus.ACCEPTED and event.order_id in self._cancel_requested:
            self._cancel(event.order_id)
        if event.status in (OrderStatus.FILLED,OrderStatus.CANCELED):
            self._cancel_requested.discard(event.order_id)

'''
    return text[:start]+branch+text[end:]


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
    for release in (0.0,0.5,1.0):
        for slots in (8,32):
            name=f'pending_release_{release}_slots_{slots}'
            text=replacement_source(release,False)
            assert 'if record[3] and not record[4]:' in text
            text=text.replace('if record[3] and not record[4]:','if not record[4]:')
            text=fix_pending_rejections(text)
            text=text.replace('if len(current) >= 8:',f'if len(current) >= {slots}:')
            path=ROOT/'sources'/(name+'.py');path.write_text(text)
            assert not check(path),check(path)
            specs[name]=dict(release=release,slots=slots,source_sha256=digest(path))
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=batch(specs,'logs/round1/screening.csv','screening')
    for name,r in screen.items():
        if specs[name]['release']==0:
            assert r['max_potential_inventory_at_submission']<=100 and r['result']['breach_penalty']==0
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    full=batch(finalists,'data/round1.csv','full')
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],parameters=specs[winner],
        limitation='Sample tuning. Nonzero release variants allow short charged breaches; all results include the native penalty.'),indent=2)+'\n')
    print('WINNER PENDING CANCEL',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
