"""Sample tuning of fill-intensity-aware passive quotes and inventory response."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/sample_v2/flow_maker_search')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT
    base=Path('logs/sample_v2/target310/sources/variant_04.py').read_text()
    configs=[(.25,skew,0) for skew in (-.05,-.1,-.25)]
    configs += [(alpha,.1,0) for alpha in (-.25,-.5)]
    configs += [(.25,.1,flow) for flow in (-.1,-.25,-.5,-1.0)]
    configs += [(.25,.1,flow) for flow in (.1,.25)]
    specs={}
    for index,(alpha,skew,flow) in enumerate(configs):
        n=f'flow_{index:02d}'
        text=base.replace('0.25*spread*imbalance',f'{alpha}*spread*imbalance + {flow}*spread*flow')
        text=text.replace('skew = 0.1 *',f'skew = {skew} *')
        path=ROOT/'sources'/(n+'.py');path.write_text(text)
        assert not check(path),check(path)
        specs[n]={'imbalance':alpha,'inventory_skew':skew,'flow_coefficient':flow,'sha256':digest(path)}
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/sample_v2/search/screening.csv','screening')
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    # Only spend full-replay work on a meaningful improvement over the current prefix.
    finalists=[n for n in finalists if screen[n]['result']['pnl']>88000]
    full=search_queue.batch(finalists,'data/sample_v2.csv','full') if finalists else {}
    winner=max(full,key=lambda n:full[n]['result']['pnl']) if full else None
    (ROOT/'winner.json').write_text(json.dumps({'name':winner,'parameters':specs.get(winner),
        'result':full.get(winner),'limitation':'Tuned on previously evaluated v2.'},indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'] if winner else 'no prefix improvement',flush=True)


if __name__=='__main__':main()
