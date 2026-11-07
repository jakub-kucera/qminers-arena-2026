"""Liquidity-scaled flow and pressure features for causal round-1 forecasts."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/impact_model')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT
    base=Path('logs/round1/nonlinear/sources/nonlinear_8_0.001_100000.py').read_text()
    specs={}
    for mode in ('relative_flow','inverse_depth','all'):
        for horizon in (100000,500000):
            n=f'impact_{mode}_{horizon}'
            if mode=='relative_flow':
                extra=',relative_flow,activity_pressure';dimensions=10
            elif mode=='inverse_depth':
                extra=',flow*inverse_depth,imbalance*inverse_depth';dimensions=10
            else:
                extra=',relative_flow,activity_pressure,flow*inverse_depth,imbalance*inverse_depth';dimensions=12
            text=base.replace('FEATURE_COUNT = 8',f'FEATURE_COUNT = {dimensions}').replace('HORIZON_US = 100000',f'HORIZON_US = {horizon}')
            text=text.replace('        ofi = max(-3,min(3,self._ofi))','''        inverse_depth = min(3.0,1000.0/max(1,bq+aq))
        relative_flow = max(-3.0,min(3.0,10*self._net/max(1,bq+aq)))
        activity_pressure = imbalance*min(3.0,10*self._volume/max(1,bq+aq))
        ofi = max(-3,min(3,self._ofi))''')
            text=text.replace('ofi*abs(ofi))','ofi*abs(ofi)'+extra+')')
            path=ROOT/'sources'/(n+'.py');path.write_text(text)
            assert not check(path),check(path)
            specs[n]={'features':mode,'horizon_us':horizon,'dimensions':dimensions,'sha256':digest(path)}
    (ROOT/'specifications.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/round1/screening.csv','screening')
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:2]
    finalists=[n for n in finalists if screen[n]['result']['pnl']>147000]
    full=search_queue.batch(finalists,'data/round1.csv','full') if finalists else {}
    winner=max(full,key=lambda n:full[n]['result']['pnl']) if full else None
    (ROOT/'winner.json').write_text(json.dumps({'name':winner,'parameters':specs.get(winner),
        'result':full.get(winner),'limitation':'Further tuning on already evaluated round-1 data.'},indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'] if winner else 'no prefix improvement',flush=True)


if __name__=='__main__':main()
