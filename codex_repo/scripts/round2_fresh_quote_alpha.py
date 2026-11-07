"""Faster quote-center and observable order-age alpha, with risk rules fixed."""
from pathlib import Path

from scripts.build_round2_candidates import describe
from scripts.round2_jump_models import replace_once
from scripts.round2_full_public_study import run_public_study


def fast_quotes(base,tau):
    text=replace_once(base,'FEATURE_COUNT = 29','FEATURE_COUNT = 33')
    text=replace_once(text,'        self._orders = {}','''        self._orders = {}
        self._fresh_counts=[0.0]*4
        self._fresh_values=[0.0]*4''')
    text=replace_once(text,'        decay_new=exp(-dt/500000)',
        f'''        decay_fresh=exp(-dt/{tau})
        for i in range(4):
            self._fresh_counts[i]*=decay_fresh
            self._fresh_values[i]*=decay_fresh
        decay_new=exp(-dt/500000)''')
    text=replace_once(text,'            self._new_counts[index]+=1',
        '''            self._fresh_counts[index]+=1
            self._fresh_values[index]+=order.price
            if order.quantity<=50:
                self._fresh_counts[index+2]+=1
                self._fresh_values[index+2]+=order.price
            self._new_counts[index]+=1''')
    addition='''        fresh_center=((self._fresh_values[0]-mid*self._fresh_counts[0])/(1+self._fresh_counts[0])+
                      (self._fresh_values[1]-mid*self._fresh_counts[1])/(1+self._fresh_counts[1]))*.5
        small_center=((self._fresh_values[2]-mid*self._fresh_counts[2])/(1+self._fresh_counts[2])+
                      (self._fresh_values[3]-mid*self._fresh_counts[3])/(1+self._fresh_counts[3]))*.5
        features+=((self._fresh_counts[0]-self._fresh_counts[1])/(1+self._fresh_counts[0]+self._fresh_counts[1]),
                   max(-5,min(5,fresh_center)),max(-5,min(5,small_center)),
                   (self._fresh_counts[2]-self._fresh_counts[3])/(1+self._fresh_counts[2]+self._fresh_counts[3]))
'''
    return replace_once(text,'        self._learn(now,mid)',addition+'        self._learn(now,mid)')


def order_age(base,threshold):
    text=replace_once(base,'FEATURE_COUNT = 29','FEATURE_COUNT = 34')
    text=replace_once(text,'        self._orders = {}','        self._orders = {}\n        self._first_seen={}')
    text=replace_once(text,'        bn = an = bd_n = ad_n = 0','''        age_seen={}
        young=[0,0,0,0]
        old=[0,0,0,0]
        age_price=[0.0,0.0]
        age_count=[0,0]
        bn = an = bd_n = ad_n = 0''')
    text=replace_once(text,'                weight = min(20,order.quantity)',f'''                first=self._first_seen.get(order.order_id,now)
                age_seen[order.order_id]=first
                side_index=0 if order.side==Side.BUY else 1
                bucket=young if now-first<={threshold} else old
                bucket[side_index+2]+=1
                if distance==0:bucket[side_index]+=1
                if now-first<={threshold}:
                    age_price[side_index]+=order.price
                    age_count[side_index]+=1
                weight = min(20,order.quantity)''')
    addition='''        self._first_seen=age_seen
        age_center=((age_price[0]/age_count[0] if age_count[0] else bid)+
                    (age_price[1]/age_count[1] if age_count[1] else ask))*.5-mid
        features+=((young[0]-young[1])/max(1,young[0]+young[1]),
                   (old[0]-old[1])/max(1,old[0]+old[1]),
                   (young[2]-young[3])/max(1,young[2]+young[3]),
                   (old[2]-old[3])/max(1,old[2]+old[3]),max(-5,min(5,age_center)))
'''
    return replace_once(text,'        self._learn(now,mid)',addition+'        self._learn(now,mid)')


def main():
    base=Path('strategies/round2_research/round2_absolute_variance_112379.py').read_text()
    cases={}
    for tau in (20000,100000):cases[f'fresh_quote_tau{tau}']=fast_quotes(base,tau)
    for threshold in (100000,500000):cases[f'order_age_{threshold}']=order_age(base,threshold)
    cases={n:describe(t,'Reused-public alpha-feature hypothesis: '+n+
        '. Volatility/risk rules held fixed; order age begins at observation, never inferred from IDs.') for n,t in cases.items()}
    run_public_study(cases,'logs/round2/fresh_quote_alpha',workers=2)


if __name__=='__main__':main()
