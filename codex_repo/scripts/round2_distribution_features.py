"""Public-only microstructure features shared verbatim by collector and exports.

Sizes describe displayed remaining quantities, not hidden original sizes.
First-seen times describe visibility age, not unobservable order birth times.
No change to inventory sizing or the native exchange is made here.
"""
import inspect
from math import exp

from scripts.round2_jump_models import replace_once


def distribution_features(self, now, snapshot, bid, ask, mid):
    if self._distribution_time is not None and now-self._distribution_time<5000 and mid==self._distribution_mid:
        return self._distribution_frame
    dt=0 if self._distribution_time is None else max(0,now-self._distribution_time)
    decay=exp(-dt/200000)
    for i in range(8):
        self._distribution_fresh_count[i]*=decay
        self._distribution_fresh_value[i]*=decay
    seen={}
    counts=[[0.0]*4 for _ in range(2)]
    values=[[0.0]*4 for _ in range(2)]
    touch_counts=[[0.0]*4 for _ in range(2)]
    touch_volume=[0.0,0.0]
    young=[0.0,0.0]
    age=[0.0,0.0]
    age_mass=[0.0,0.0]
    far_count=[0.0,0.0]
    far_value=[0.0,0.0]
    max_size=[0.0,0.0]
    for side,orders in enumerate((snapshot.bids,snapshot.asks)):
        touch=bid if side==0 else ask
        for order in orders:
            if order.owner!='market':
                continue
            distance=abs(order.price-touch)
            first=self._distribution_seen.get(order.order_id,now)
            seen[order.order_id]=first
            if distance>4:
                far_count[side]+=1
                far_value[side]+=order.price-mid
                continue
            q=order.quantity
            group=0 if q<=10 else 1 if q<=50 else 2 if q<=200 else 3
            counts[side][group]+=1
            values[side][group]+=order.price-mid
            if distance==0:
                touch_counts[side][group]+=1
                touch_volume[side]+=q
                max_size[side]=max(max_size[side],q)
                age[side]+=min(2.0,(now-first)/1000000)
                age_mass[side]+=1
                if now-first<=100000:
                    young[side]+=1
            if order.order_id not in self._distribution_seen:
                k=2*group+side
                self._distribution_fresh_count[k]+=1
                self._distribution_fresh_value[k]+=order.price
    self._distribution_seen=seen
    odd=[]
    even=[min(10,ask-bid),min(10000,sum(touch_volume))/1000]
    for g in range(4):
        b,a=counts[0][g],counts[1][g]
        odd.extend(((b-a)/(1+b+a),
            (values[0][g]+values[1][g])/(1+b+a),
            (touch_counts[0][g]-touch_counts[1][g])/(1+touch_counts[0][g]+touch_counts[1][g])))
        cb,ca=self._distribution_fresh_count[2*g:2*g+2]
        vb,va=self._distribution_fresh_value[2*g:2*g+2]
        odd.extend(((cb-ca)/(1+cb+ca),max(-10,min(10,(vb+va-mid*(cb+ca))/(1+cb+ca)))))
        even.extend((min(40,b+a)/10,min(80,cb+ca)/10))
    odd.extend(((young[0]-young[1])/(1+young[0]+young[1]),
        age[0]/(1+age_mass[0])-age[1]/(1+age_mass[1]),
        (far_value[0]+far_value[1])/(1+far_count[0]+far_count[1]),
        (max_size[0]-max_size[1])/(1+max_size[0]+max_size[1])))
    even.extend(((young[0]+young[1])/(1+sum(age_mass)),
        sum(age)/(1+sum(age_mass)),min(100,sum(far_count))/10))
    self._distribution_frame=(tuple(odd),tuple(even))
    self._distribution_time=now
    self._distribution_mid=mid
    return self._distribution_frame


def augment(base):
    text=replace_once(base,'        self._orders = {}','''        self._orders = {}
        self._distribution_time=self._distribution_mid=None
        self._distribution_seen={}
        self._distribution_fresh_count=[0.0]*8
        self._distribution_fresh_value=[0.0]*8
        self._distribution_frame=((),())''')
    method=inspect.getsource(distribution_features).replace('def distribution_features(', 'def _distribution_features(',1)
    method='\n'.join('    '+line if line else '' for line in method.splitlines())+'\n\n'
    text=replace_once(text,'    def _learn(self, now, mid):',method+'    def _learn(self, now, mid):')
    return replace_once(text,'        self._learn(now,mid)',
        '        self._distribution_features(now,snapshot,bid,ask,mid)\n        self._learn(now,mid)')


ODD_NAMES=[f'{group}_{feature}' for group in ('q1_10','q11_50','q51_200','q201_plus')
    for feature in ('count_imbalance','price_center','touch_count_imbalance','fresh_count_imbalance','fresh_price_center')]
ODD_NAMES+=['young_touch_imbalance','touch_age_difference','far_price_center','largest_touch_imbalance']
EVEN_NAMES=['spread','touch_volume']+[f'{group}_{feature}'
    for group in ('q1_10','q11_50','q51_200','q201_plus') for feature in ('count','fresh_count')]
EVEN_NAMES+=['young_touch_fraction','touch_mean_age','far_count']
