"""V2 tuning: replenish free inventory capacity without canceling older orders."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.check_submission import check
from scripts.benchmark import digest

ROOT=Path('logs/sample_v2/layer_search')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT
    base=Path('logs/sample_v2/band_search/sources/band_02.py').read_text()
    start=base.index('        current = None\n')
    end=base.index('        if price is None or price <= 0',start)
    specs={}
    for layers,minimum in ((2,10),(3,10),(4,10),(3,25),(4,1)):
        name=f'layers_{layers}_min_{minimum}'
        replacement=f'''        current = [(oid,r) for oid,r in self._orders.items() if r[0] == sign]
        changing = False
        for oid,record in current:
            if price is None or record[1] != price:
                self._cancel(oid)
                changing = True
        if changing or any(record[4] for oid,record in current):
            return
        if len(current) >= {layers}:
            return
'''
        text=base[:start]+replacement+base[end:]
        text=text.replace('        if quantity <= 0:',f'        if quantity <= 0 or (current and quantity < {minimum}):')
        text=text.replace('At most one order per side;',f'At most {layers} orders per side;')
        path=ROOT/'sources'/(name+'.py');path.write_text(text)
        assert not check(path),check(path)
        specs[name]={'max_layers':layers,'min_replenish':minimum,'sha256':digest(path)}
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/sample_v2/search/screening.csv','screening')
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:2]
    (ROOT/'finalists.json').write_text(json.dumps(finalists,indent=2)+'\n')
    full=search_queue.batch(finalists,'data/sample_v2.csv','full')
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps({'name':winner,'result':full[winner],
        'parameters':specs[winner],'limitation':'V2 sample tuning after validation data was consumed.'},indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
