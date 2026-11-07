"""Learn fill-conditional edges from public aggressive trades and matured markouts."""
from pathlib import Path

from scripts.round2_jump_models import build_candidates,replace_once,run_study
from scripts.build_round2_candidates import describe


HELPERS='''    def _conditional_features(self,sign,edge,features):
        indices=(0,2,3,8,9,10,11,15,16,17,18,19,20,21,22,28)
        return (1.0,min(2,edge))+tuple(sign*features[i] for i in indices)

    def _learn_conditional(self,now,mid,trades):
        if self._conditional_previous is not None:
            old_time,old_bid,old_ask,old_features=self._conditional_previous
            if now-old_time<=100000:
                groups={}
                for trade in trades:
                    if trade.taker_owner!='market':
                        continue
                    sign=1 if trade.book_side=='bid' else -1
                    touch=old_bid if sign>0 else old_ask
                    if abs(trade.price-touch)>1:
                        continue
                    key=(trade.taker_order_id,sign)
                    if key not in groups:
                        groups[key]=[0,0.0]
                    groups[key][0]+=trade.quantity
                    groups[key][1]+=trade.quantity*trade.price
                for (_,sign),(quantity,value) in groups.items():
                    price=value/quantity
                    edge=sign*((old_bid+old_ask)*0.5-price)
                    frame=self._conditional_features(sign,edge,old_features)
                    self._conditional_pending.append((now,sign,price,frame,min(20,quantity)))
        while self._conditional_pending and self._conditional_pending[0][0]+CONDITIONAL_HORIZON<=now:
            stamp,sign,price,frame,weight=self._conditional_pending.popleft()
            if now-stamp>CONDITIONAL_HORIZON+1000000:
                continue
            dt=0 if self._conditional_last_label is None else now-self._conditional_last_label
            self._conditional_last_label=now
            decay=exp(-max(0,dt)/600000000)
            target=max(-3,min(3,sign*(mid-price)))
            self._conditional_mass=self._conditional_mass*decay+weight
            self._conditional_labels+=1
            for i in range(18):
                self._conditional_xy[i]=self._conditional_xy[i]*decay+weight*frame[i]*target
                for j in range(18):
                    self._conditional_xx[i][j]=self._conditional_xx[i][j]*decay+weight*frame[i]*frame[j]
        if self._conditional_labels<200 or (self._conditional_last_fit is not None and now-self._conditional_last_fit<1000000):
            return
        self._conditional_last_fit=now
        matrix=[self._conditional_xx[i][:]+[self._conditional_xy[i]] for i in range(18)]
        for i in range(18):
            matrix[i][i]+=max(10,0.003*self._conditional_mass)
        for col in range(18):
            pivot=matrix[col][col]
            if not isfinite(pivot) or pivot<=1e-12:
                return
            for j in range(col,19):matrix[col][j]/=pivot
            for i in range(18):
                if i==col:continue
                factor=matrix[i][col]
                for j in range(col,19):matrix[i][j]-=factor*matrix[col][j]
        weights=[matrix[i][18] for i in range(18)]
        if all(isfinite(w) for w in weights):self._conditional_weights=weights

    def _conditional_edge(self,sign,price,mid,features):
        frame=self._conditional_features(sign,sign*(mid-price),features)
        return sum(w*x for w,x in zip(self._conditional_weights,frame))

'''


def conditional_model(base,horizon,mode):
    text=replace_once(base,'        self._orders = {}','''        self._orders = {}
        self._conditional_previous=None
        self._conditional_pending=deque(maxlen=16384)
        self._conditional_xx=[[0.0]*18 for _ in range(18)]
        self._conditional_xy=[0.0]*18
        self._conditional_weights=[0.0]*18
        self._conditional_mass=0.0
        self._conditional_labels=0
        self._conditional_last_label=self._conditional_last_fit=None''')
    text=replace_once(text,'    def _learn(self, now, mid):',
        HELPERS.replace('CONDITIONAL_HORIZON',str(horizon))+'    def _learn(self, now, mid):')
    text=replace_once(text,'            self._previous_touch = None',
        '            self._previous_touch = None\n            self._conditional_previous=None')
    text=replace_once(text,'        self._learn(now,mid)',
        '''        self._learn(now,mid)
        self._learn_conditional(now,mid,trades)
        self._conditional_previous=(now,bid,ask,features)''')
    if mode=='gate':
        decision='''        if self._conditional_labels>=200:
            if self.inventory>=0 and self._conditional_edge(1,buy,mid,features)<0:
                buy=None
            if self.inventory<=0 and self._conditional_edge(-1,sell,mid,features)<0:
                sell=None
'''
    else:
        decision='''        if self._conditional_labels>=200:
            if self.inventory>=0 and self._conditional_edge(1,buy,mid,features)<0:
                buy=min(buy,bid-1)
            if self.inventory<=0 and self._conditional_edge(-1,sell,mid,features)<0:
                sell=max(sell,ask+1)
'''
    text=replace_once(text,'        # Withdraw the side',decision+'        # Withdraw the side')
    return text


def main():
    robust=build_candidates(Path('strategies/round2/round2_transfer.py').read_text())['robust_label1']
    cases={}
    for horizon,mode in ((100000,'gate'),(400000,'gate'),(400000,'shade')):
        name=f'conditional_{horizon}_{mode}'
        cases[name]=describe(conditional_model(robust,horizon,mode),
            'Round-2 public-fill-conditional edge hypothesis: '+name+
            '. Features precede observed aggressive fills; labels mature causally; native fees unchanged.')
    run_study(cases,'logs/round2/conditional_market_fills',workers=2)


if __name__=='__main__':main()
