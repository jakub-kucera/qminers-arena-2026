"""V2 sample tuning of a neutral band in the fair-price adjustment."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.check_submission import check
from scripts.benchmark import digest

ROOT=Path('logs/sample_v2/band_search')


def main():
    ROOT.mkdir(parents=True,exist_ok=True); (ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists(): raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT
    base=Path('strategies/passive_v2_q60.py').read_text()
    base=base.replace('POSITION_LIMIT = 90','POSITION_LIMIT = 100').replace('QUOTE_SIZE = 60','QUOTE_SIZE = 200')
    base=base.replace('REQUOTE_US = 50_000','REQUOTE_US = 5000').replace('{-1:-50_000, 1:-50_000}','{-1:-5000, 1:-5000}')
    configs=[(200,.1,b) for b in (.02,.05,.1,.15,.25)]
    configs += [(150,.1,b) for b in (.05,.1)]
    configs += [(200,.05,b) for b in (0,.05,.1)]
    configs += [(200,.15,b) for b in (0,.05)]
    specs={}
    for index,(size,skew,band) in enumerate(configs):
        name=f'band_{index:02d}'
        text=base.replace('QUOTE_SIZE = 200',f'QUOTE_SIZE = {size}')
        text=text.replace('skew = 0.25 *',f'skew = {skew} *')
        text=text.replace('        buy = min(bid,floor(fair-0.5))',f'''        if abs(fair-mid) <= {band}:
            fair = mid
        buy = min(bid,floor(fair-0.5))''')
        path=ROOT/'sources'/(name+'.py');path.write_text(text)
        assert not check(path),check(path)
        specs[name]={'size':size,'skew':skew,'band':band,'sha256':digest(path)}
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/sample_v2/search/screening.csv','screening')
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    (ROOT/'finalists.json').write_text(json.dumps(finalists,indent=2)+'\n')
    full=search_queue.batch(finalists,'data/sample_v2.csv','full')
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps({'name':winner,'result':full[winner],
        'parameters':specs[winner],'limitation':'V2 sample tuning; no unused validation tail remains.'},indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__': main()
