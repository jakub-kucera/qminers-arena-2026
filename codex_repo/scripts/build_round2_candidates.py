"""Build standalone, predeclared round-2 hypotheses from immutable sources.

These are candidates for new data, not verified round-2 winners. Generation
never changes round1_submission.py or any preserved round-1 checkpoint.
"""
import argparse
import ast
import json
from pathlib import Path

from scripts.benchmark import digest
from scripts.check_submission import check

REPO = Path(__file__).resolve().parents[1]
BASE = REPO/'strategies/round1_quote_flow_624076.py'
BASE_SHA256 = '0aaff6caee4c8708afb0f3bc54a8f1d3beaa5a641477db192be09cfeb6993b45'
DESTINATION = REPO/'strategies/round2'


def describe(text, description):
    tree = ast.parse(text)
    assert isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant)
    return '"""'+description+'\n\nRound-2 hypothesis; performance on round-2 data is unknown.\n' \
        'Uses only current/past public information and causally matured labels.\n"""\n' \
        + ''.join(text.splitlines(keepends=True)[tree.body[0].end_lineno:])


DUAL_LEARNER = '''    def _forecast_for(self, weights, features):
        return max(-2.0,min(2.0,sum(w*x for w,x in zip(weights,features))))

    def _ridge_weights(self, xx, xy, mass):
        n=self.FEATURE_COUNT
        matrix=[xx[i][:]+[xy[i]] for i in range(n)]
        for i in range(n):
            matrix[i][i]+=max(10.0,0.001*mass)
        for col in range(n):
            pivot=matrix[col][col]
            if not isfinite(pivot) or pivot<=1e-12:
                return None
            for j in range(col,n+1):
                matrix[col][j]/=pivot
            for i in range(n):
                if i==col:
                    continue
                factor=matrix[i][col]
                for j in range(col,n+1):
                    matrix[i][j]-=factor*matrix[col][j]
        weights=[matrix[i][n] for i in range(n)]
        return weights if all(isfinite(w) for w in weights) else None

    def _learn(self, now, mid):
        while self._observations and self._observations[0][0]+self.HORIZON_US<=now:
            observed,origin,features,long_prediction,fast_prediction=self._observations.popleft()
            if now-observed>self.HORIZON_US+1000000:
                continue
            elapsed=0 if self._last_label_us is None else max(0,now-self._last_label_us)
            self._last_label_us=now
            slow_decay=exp(-elapsed/self.MODEL_MEMORY_US)
            fast_decay=exp(-elapsed/self.FAST_MEMORY_US)
            response=max(-20.0,min(20.0,mid-origin))
            self._mass=self._mass*slow_decay+1.0
            self._fast_mass=self._fast_mass*fast_decay+1.0
            for i in range(self.FEATURE_COUNT):
                self._xy[i]=self._xy[i]*slow_decay+features[i]*response
                self._fast_xy[i]=self._fast_xy[i]*fast_decay+features[i]*response
                for j in range(self.FEATURE_COUNT):
                    product=features[i]*features[j]
                    self._xx[i][j]=self._xx[i][j]*slow_decay+product
                    self._fast_xx[i][j]=self._fast_xx[i][j]*fast_decay+product
            # Predictions were saved at observation time, before this label.
            self._long_loss+=self.SCORE_ALPHA*(min(25.0,(response-long_prediction)**2)-self._long_loss)
            self._fast_loss+=self.SCORE_ALPHA*(min(25.0,(response-fast_prediction)**2)-self._fast_loss)
            self._labels+=1
        if self._labels<self.MIN_LABELS:
            return
        if self._last_fit_us is not None and now-self._last_fit_us<1000000:
            return
        self._last_fit_us=now
        long_weights=self._ridge_weights(self._xx,self._xy,self._mass)
        fast_weights=self._ridge_weights(self._fast_xx,self._fast_xy,self._fast_mass)
        if long_weights is not None:
            self._long_weights=long_weights
        if fast_weights is not None:
            self._fast_weights=fast_weights
        temperature=max(0.01,0.1*(self._fast_loss+self._long_loss))
        relative=max(-6.0,min(6.0,(self._fast_loss-self._long_loss)/temperature))
        self._fast_mix=max(0.1,min(0.9,1.0/(1.0+3.0*exp(relative))))
        self._weights=[(1-self._fast_mix)*a+self._fast_mix*b
                       for a,b in zip(self._long_weights,self._fast_weights)]

'''


def dual_memory(text):
    text = text.replace('MODEL_MEMORY_US = 100000000000',
                        'MODEL_MEMORY_US = 100000000000\n    FAST_MEMORY_US = 300000000\n    SCORE_ALPHA = 0.001')
    anchor='        self._weights = [0.0] * self.FEATURE_COUNT'
    assert text.count(anchor)==1
    text=text.replace(anchor,anchor+'''
        self._long_weights=[0.0]*self.FEATURE_COUNT
        self._fast_weights=[0.0]*self.FEATURE_COUNT
        self._fast_xx=[[0.0]*self.FEATURE_COUNT for _ in range(self.FEATURE_COUNT)]
        self._fast_xy=[0.0]*self.FEATURE_COUNT
        self._fast_mass=0.0
        self._long_loss=self._fast_loss=0.25
        self._fast_mix=0.25''',1)
    start=text.index('    def _learn(');end=text.index('    def _hedge(',start)
    text=text[:start]+DUAL_LEARNER+text[end:]
    anchor='self._observations.append((now,mid,features))'
    assert text.count(anchor)==1
    return text.replace(anchor,'''self._observations.append((now,mid,features,
                self._forecast_for(self._long_weights,features),
                self._forecast_for(self._fast_weights,features)))''',1)


def candidates():
    assert digest(BASE)==BASE_SHA256,'The immutable round-1 base has changed'
    base=BASE.read_text()
    transfer=describe(base,'Round-1 624076 transfer reference. Paid cancel/replace overlap; 400 ms labels.')
    strict=base.replace('POSITION_LIMIT = 1000','POSITION_LIMIT = 100',1)
    anchor='effective=sum(ceil(r[2]*(1-1.0)) if r[4] else r[2] for r in self._orders.values() if r[0]==sign)'
    assert strict.count(anchor)==1
    strict=strict.replace(anchor,'effective = reserved',1)
    strict=describe(strict,'Strict 100-lot maker. Reserve every resting and pending cancellation until confirmed.')
    fast=base.replace('HORIZON_US = 400000','HORIZON_US = 200000',1).replace(
        'MODEL_MEMORY_US = 100000000000','MODEL_MEMORY_US = 900000000',1).replace(
        'abs(fair-mid) <= 0.18','abs(fair-mid) <= 0.12',1).replace('floor(fair-0.45)','floor(fair-0.5)').replace(
        'ceil(fair+0.45)','ceil(fair+0.5)')
    fast=describe(fast,'Faster adaptation hypothesis: 200 ms labels and 15-minute memory. Paid overlap.')
    dual=describe(dual_memory(base),'Dual-memory maker. Mix long/5-minute forecasts using matured prequential errors. Paid overlap.')
    guarded=describe((REPO/'strategies/guarded_strategy.py').read_text(),
                     'Guarded IOC trend alternative for sparse/trending books. Strict 80-lot exposure.')
    flat='''"""No-trade control for round-2 evaluation; zero-risk reference, not a forecast model."""
from simulator.strategy import BaseStrategy


class FlatStrategy(BaseStrategy):
    POSITION_LIMIT=100

    def __init__(self):
        super().__init__()
        self.inventory=0
        self.cash=0

    def on_order_book_change(self,snapshot,trades):
        pass

    def on_private_order_update(self,event):
        pass
'''
    return {
        'round2_transfer':(transfer,'native','Direct transfer reference'),
        'round2_strict100':(strict,'strict100','No paid breaches or overlapping released reservations'),
        'round2_fast_adapt':(fast,'native','Shorter labels and faster parameter adaptation'),
        'round2_dual_memory':(dual,'native','Causal error-weighted long/fast forecast mixture'),
        'round2_guarded_trend':(guarded,'strict80','Guarded IOC execution; different market hypothesis'),
        'round2_flat':(flat,'strict100','No-trade control'),
    }


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    DESTINATION.mkdir(parents=True,exist_ok=True)
    registry={'status':'Predeclared candidates; round-2 performance unknown.',
              'base_file':str(BASE.relative_to(REPO)),'base_sha256':digest(BASE),'candidates':[]}
    for name,(text,risk,intent) in candidates().items():
        path=DESTINATION/(name+'.py')
        if args.check or path.exists():
            assert path.exists() and path.read_text()==text, f'Generated candidate differs: {path}'
        else:
            path.write_text(text)
        assert not check(path),check(path)
        registry['candidates'].append(dict(name=name,file=str(path.relative_to(REPO)),
            source_sha256=digest(path),risk=risk,intent=intent))
    path=DESTINATION/'manifest.json';serialized=json.dumps(registry,indent=2)+'\n'
    if args.check or path.exists():
        assert path.exists() and path.read_text()==serialized,'Registry differs from generated candidates'
    else:
        path.write_text(serialized)
    print('Checked' if args.check else 'Prepared',len(registry['candidates']),'standalone round-2 candidates.')


if __name__=='__main__':
    main()
