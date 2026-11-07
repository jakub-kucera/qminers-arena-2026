"""Causal online fair-price calibration for the passive v2 execution layer."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/sample_v2/learned_maker')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT
    base=Path('logs/sample_v2/target310/sources/variant_04.py').read_text()
    learner=Path('strategies/arena_strategy.py').read_text()
    learn=learner[learner.index('    def _learn('):learner.index('    def _send_toward(')]
    fields='''        self._observations = deque(maxlen=64)
        self._last_observation_us = -100000
        self._last_fit_us = None
        self._last_label_us = None
        self._labels = 0
        self._mass = 0.0
        self._xx = [[0.0] * 3 for _ in range(3)]
        self._xy = [0.0] * 3
        self._weights = [0.0] * 3
        self._fast_mid = self._slow_mid = None
        self._model_time = None
'''
    model='''        if self._model_time is None or now-self._model_time > 10000000:
            self._fast_mid = self._slow_mid = mid
            self._observations.clear()
        else:
            dt=max(0,now-self._model_time)
            self._fast_mid += (1-exp(-dt/500000))*(mid-self._fast_mid)
            self._slow_mid += (1-exp(-dt/2000000))*(mid-self._slow_mid)
        self._model_time = now
        features=(flow,max(-5,min(5,self._fast_mid-self._slow_mid)),imbalance)
        self._learn(now,mid)
        if now-self._last_observation_us >= self.OBSERVATION_INTERVAL_US:
            self._observations.append((now,mid,features))
            self._last_observation_us = now
        prediction = 0.25*spread*imbalance
        if self._labels >= self.MIN_LABELS:
            prediction = max(-2.0,min(2.0,sum(w*x for w,x in zip(self._weights,features))))
'''
    specs={}
    for horizon in (100000,500000,2000000):
        for ridge in (.01,.05):
            for blend in (.5,1.0):
                n=f'model_{horizon}_{ridge}_{blend}'
                text=base.replace('from math import exp, ceil, floor','from collections import deque\nfrom math import exp, ceil, floor, isfinite')
                text=text.replace('    POSITION_LIMIT = 100',f'''    HORIZON_US = {horizon}
    OBSERVATION_INTERVAL_US = 100000
    MIN_LABELS = 200
    MODEL_MEMORY_US = 300000000
    POSITION_LIMIT = 100''')
                text=text.replace('        self._orders = {}','        self._orders = {}\n'+fields,1)
                method=learn.replace('0.05 * self._mass',f'{ridge} * self._mass')
                text=text.replace('    def _cancel(',method+'    def _cancel(',1)
                text=text.replace('        fair = mid + 0.25*spread*imbalance - skew',model+f'        fair = mid + {blend}*prediction + {1-blend}*0.25*spread*imbalance - skew')
                path=ROOT/'sources'/(n+'.py');path.write_text(text)
                assert not check(path),check(path)
                specs[n]={'horizon_us':horizon,'ridge':ridge,'model_blend':blend,'sha256':digest(path)}
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/sample_v2/search/screening.csv','screening')
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    full=search_queue.batch(finalists,'data/sample_v2.csv','full')
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps({'name':winner,'parameters':specs[winner],
        'result':full[winner],'limitation':'Tuned on previously evaluated v2.'},indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
