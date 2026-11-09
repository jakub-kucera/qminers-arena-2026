"""Low-dimensional causal residual learning around the verified209795 model."""
from pathlib import Path
from scripts.benchmark import digest
from scripts.round2_ra_composite import main as run_study


def build():
    p=Path('strategies/round2/round2_local_209795.py')
    assert digest(p)=='df93cf43167894a1fe00a67b459f32d655ecbc8a5d5a2e4f036f54645e05af90'
    base=p.read_text();cases={}
    for ridge in (5,25):
        for blend in (.5,1.0):
            text=base.replace('        self._cal_groups=[0.0]*4','''        self._res_xx=[[0.0]*6 for _ in range(6)]
        self._res_xy=[0.0]*6
        self._res_weights=[0.0]*6
        self._res_time=None
        self._res_fit_time=None
        self._res_buy_features=self._res_sell_features=None
        self._cal_groups=[0.0]*4''',1)
            methods=f'''    def _res_features(self,sign,spread,prediction):
        group=(0 if sign>0 else 1)+2*int(spread>=2)
        return tuple(1.0 if i==group else 0.0 for i in range(4))+(sign*self._m2_big,max(-1,min(1,sign*prediction/2)))

    def _res_update(self,now,features,response,quantity):
        if features is None:
            return
        decay=1.0 if self._res_time is None else exp(-max(0,now-self._res_time)/300000000)
        self._res_time=now
        weight=min(1.0,quantity/100)
        response=max(-3,min(3,response))
        for i in range(6):
            self._res_xy[i]=decay*self._res_xy[i]+weight*features[i]*response
            for j in range(6):
                self._res_xx[i][j]=decay*self._res_xx[i][j]+weight*features[i]*features[j]
        if self._res_fit_time is not None and now-self._res_fit_time<1000000:
            return
        self._res_fit_time=now
        matrix=[self._res_xx[i][:]+[self._res_xy[i]] for i in range(6)]
        for i in range(6):
            matrix[i][i]+={ridge}
        for col in range(6):
            pivot=matrix[col][col]
            if pivot<=1e-12 or not isfinite(pivot):
                return
            for j in range(col,7):
                matrix[col][j]/=pivot
            for i in range(6):
                if i==col:
                    continue
                factor=matrix[i][col]
                for j in range(col,7):
                    matrix[i][j]-=factor*matrix[col][j]
        weights=[matrix[i][6] for i in range(6)]
        if all(isfinite(w) for w in weights):
            self._res_weights=weights

    def _res_predict(self,now,features):
        if self._res_time is None:
            return 0.0
        stale=exp(-max(0,now-self._res_time)/300000000)
        return max(-0.5,min(0.5,stale*sum(w*x for w,x in zip(self._res_weights,features))))

'''
            text=text.replace('    def _fill_value(self, features, direction):',methods+'    def _fill_value(self, features, direction):',1)
            text=text.replace('observed,sign,price,predicted,quantity,bucket=self._cal_labels.popleft()',
                'observed,sign,price,predicted,quantity,bucket,context=self._cal_labels.popleft()',1)
            anchor='                self._cal_groups[index]=max(-0.5,min(0.5,self._cal_groups[index]))'
            assert text.count(anchor)==1
            text=text.replace(anchor,anchor+'\n                self._res_update(now,context,realized-predicted,quantity)',1)
            anchor='            self._value_spread=spread'
            text=text.replace(anchor,'''            self._res_buy_features=self._res_features(1,spread,prediction)
            self._res_sell_features=self._res_features(-1,spread,prediction)
'''+anchor,1)
            anchor='event.filled_quantity,int(self._value_spread>=2)))'
            assert text.count(anchor)==1
            text=text.replace(anchor,'event.filled_quantity,int(self._value_spread>=2),self._res_buy_features if record[0]>0 else self._res_sell_features))',1)
            for index,sign in ((0,1),(1,-1)):
                anchor=f'(0.0*self._cal_error+1.0*self._cal_groups[{index}+2*int(spread>=2)])'
                assert text.count(anchor)==1
                text=text.replace(anchor,f'({1-blend}*self._cal_groups[{index}+2*int(spread>=2)]+{blend}*self._res_predict(now,self._res_features({sign},spread,prediction)))',1)
            cases[f'ridge{ridge}_blend{blend}']=text
    return cases


if __name__=='__main__':
    run_study(Path('logs/round2_residual_ridge'),build(),
        'Six-feature regularized online fill-residual model: four side/spread groups, lagged flow alignment and signed price prediction. Ridge5/25, blend50/100percent,300s memory,400ms mature labels,0.5 bounded corrections. Preserve all candidates.')
