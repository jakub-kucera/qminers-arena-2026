"""V2 tuning of quote width and imbalance/inventory fair-price calibration."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.check_submission import check
from scripts.benchmark import digest

ROOT=Path('logs/sample_v2/pricing_search')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT
    base=Path('logs/sample_v2/target310/sources/variant_04.py').read_text()
    configs=[(.5,0,0,.1),(.5,.25,0,.1),(.5,.25,.025,.1),
        (.5,.25,.05,.1),(.5,.25,.1,.025),(.5,.25,.1,.2),
        (.5,.5,.1,.1),(.5,1,.1,.1),(.5,2,.1,.1),
        (.25,.25,.1,.1),(.1,.25,.1,.1),(.25,.5,.1,.1),
        (.1,.5,.1,.1),(.25,.25,.05,.1),(.25,1,.1,.1),(.1,1,.1,.1)]
    specs={}
    for index,(width,alpha,skew,band) in enumerate(configs):
        n=f'price_{index:02d}'
        text=base.replace('fair-0.5',f'fair-{width}').replace('fair+0.5',f'fair+{width}')
        text=text.replace('0.25*spread*imbalance',f'{alpha}*spread*imbalance')
        text=text.replace('skew = 0.1 *',f'skew = {skew} *')
        text=text.replace('abs(fair-mid) <= 0.1',f'abs(fair-mid) <= {band}')
        path=ROOT/'sources'/(n+'.py');path.write_text(text)
        assert not check(path),check(path)
        specs[n]={'halfwidth':width,'alpha':alpha,'skew':skew,'neutral_band':band,'sha256':digest(path)}
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/sample_v2/search/screening.csv','screening')
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    (ROOT/'finalists.json').write_text(json.dumps(finalists,indent=2)+'\n')
    full=search_queue.batch(finalists,'data/sample_v2.csv','full')
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps({'name':winner,'parameters':specs[winner],
        'result':full[winner],'limitation':'Further v2 tuning after previous validation was consumed.'},indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
