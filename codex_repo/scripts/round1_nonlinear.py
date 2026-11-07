"""Causal nonlinear feature expansion for the round-1 passive predictor."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/nonlinear')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT
    base=Path('logs/round1/target550/sources/execution_13.py').read_text()
    old='''        features=(flow,max(-5,min(5,self._fast_mid-self._slow_mid)),imbalance,
                  max(-3,min(3,self._ofi)),spread*imbalance)'''
    assert old in base
    specs={}
    for dimensions in (8,11):
        for ridge in (.001,.01,.05):
            for horizon in (100000,500000):
                n=f'nonlinear_{dimensions}_{ridge}_{horizon}'
                text=base.replace('FEATURE_COUNT = 5',f'FEATURE_COUNT = {dimensions}')
                text=text.replace('0.01 * self._mass',f'{ridge} * self._mass')
                text=text.replace('HORIZON_US = 100000',f'HORIZON_US = {horizon}')
                extra='' if dimensions==8 else ',flow*abs(imbalance),imbalance*abs(flow),imbalance*abs(ofi)'
                new='''        ofi = max(-3,min(3,self._ofi))
        features=(flow,max(-5,min(5,self._fast_mid-self._slow_mid)),imbalance,
                  ofi,spread*imbalance,flow*abs(flow),imbalance*abs(imbalance),ofi*abs(ofi)'''+extra+')'
                text=text.replace(old,new)
                path=ROOT/'sources'/(n+'.py');path.write_text(text)
                assert not check(path),check(path)
                specs[n]={'dimensions':dimensions,'ridge':ridge,'horizon_us':horizon,'sha256':digest(path)}
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/round1/screening.csv','screening')
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    finalists=[n for n in finalists if screen[n]['result']['pnl']>142000]
    full=search_queue.batch(finalists,'data/round1.csv','full') if finalists else {}
    winner=max(full,key=lambda n:full[n]['result']['pnl']) if full else None
    (ROOT/'winner.json').write_text(json.dumps({'name':winner,'parameters':specs.get(winner),
        'result':full.get(winner),'limitation':'Further tuning on already evaluated round-1 data.'},indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'] if winner else 'no prefix improvement',flush=True)


if __name__=='__main__':main()
