"""Keep the stable 15-feature forecast and adapt only its flow residual faster."""
import json
from pathlib import Path

from scripts import round1_claude_improvements as research
from scripts.round1_aggressor_groups import source_for
from scripts.round1_claude_capped_flow import source as capped_source
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/claude_residual_flow')


def augment(text,memory,gain):
    text=text.replace('FEATURE_COUNT = 23','FEATURE_COUNT = 15',1)
    text=text.replace('        self._orders = {}','''        self._orders = {}
        self._resid_observations=deque(maxlen=64)
        self._resid_xx=[[0.0]*8 for _ in range(8)]
        self._resid_xy=[0.0]*8
        self._resid_weights=[0.0]*8
        self._resid_mass=0.0
        self._resid_labels=0
        self._resid_last_label=None
        self._resid_last_fit=None
        self._resid_last_obs=-100000''',1)
    helper=f'''    def _residual_flow(self,now,mid,features,baseline):
        while self._resid_observations and self._resid_observations[0][0]+self.HORIZON_US<=now:
            stamp,origin,row,old_prediction=self._resid_observations.popleft()
            if now-stamp>self.HORIZON_US+1000000:
                continue
            elapsed=0 if self._resid_last_label is None else max(0,now-self._resid_last_label)
            decay=exp(-elapsed/{memory})
            self._resid_last_label=now
            target=max(-5.0,min(5.0,mid-origin-old_prediction))
            self._resid_mass=self._resid_mass*decay+1
            self._resid_labels+=1
            for i in range(8):
                self._resid_xy[i]=self._resid_xy[i]*decay+row[i]*target
                for j in range(8):
                    self._resid_xx[i][j]=self._resid_xx[i][j]*decay+row[i]*row[j]
        if self._resid_labels>=200 and (self._resid_last_fit is None or now-self._resid_last_fit>=1000000):
            self._resid_last_fit=now
            matrix=[self._resid_xx[i][:]+[self._resid_xy[i]] for i in range(8)]
            for i in range(8):
                matrix[i][i]+=max(10.0,0.001*self._resid_mass)
            valid=True
            for col in range(8):
                pivot=matrix[col][col]
                if not isfinite(pivot) or pivot<=1e-12:
                    valid=False
                    break
                for j in range(col,9):
                    matrix[col][j]/=pivot
                for i in range(8):
                    if i==col:
                        continue
                    factor=matrix[i][col]
                    for j in range(col,9):
                        matrix[i][j]-=factor*matrix[col][j]
            weights=[matrix[i][8] for i in range(8)]
            if valid and all(isfinite(w) for w in weights):
                self._resid_weights=weights
        if now-self._resid_last_obs>=self.OBSERVATION_INTERVAL_US:
            self._resid_observations.append((now,mid,features,baseline))
            self._resid_last_obs=now
        return max(-1.0,min(1.0,sum(w*x for w,x in zip(self._resid_weights,features))))

'''
    text=text.replace('    def _hedge(self, now):',helper+'    def _hedge(self, now):',1)
    return text.replace('        fair = mid + ',f'''        residual=self._residual_flow(now,mid,features[15:],prediction)
        prediction=max(-2.0,min(2.0,prediction+{gain}*residual))
        fair = mid + ''',1)


def main():
    base=Path('strategies/round1_claude_595k.py').read_text()
    raw=research.transfer_features(base,source_for(500000,100000))
    count=capped_source(1000000,1)
    cases={}
    for label,source in (('raw',raw),('count',count)):
        for memory in (300000000,1000000000,3000000000):
            cases[f'{label}_memory_{memory}']=augment(source,memory,1.0)
    (ROOT/'sources').mkdir(parents=True,exist_ok=True)
    specs={}
    for name,text in cases.items():
        path=ROOT/'sources'/(name+'.py');path.write_text(text)
        assert not check(path),check(path)
        specs[name]={'source_sha256':digest(path)}
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    research.ROOT=ROOT
    screen=research.batch(cases,'logs/round1/screening.csv','screening',workers=3)
    ranked=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)
    full=research.batch(ranked[:3],'data/round1.csv','full',workers=3)
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],
        limitation='Causal online residual fitting, tuned on consumed sample; all native fees included.'),indent=2)+'\n')
    print('WINNER RESIDUAL FLOW',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
