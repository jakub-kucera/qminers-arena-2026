"""Distinct causal book-cohort and jump-state predictors on public development."""
from pathlib import Path

from scripts.build_round2_candidates import describe
from scripts.round2_jump_models import build_candidates,replace_once,run_study
from scripts.round2_queue_inventory import queue_inventory


def jump_features(base):
    text=replace_once(base,'FEATURE_COUNT = 29','FEATURE_COUNT = 39')
    text=replace_once(text,'        self._orders = {}','''        self._orders = {}
        self._regime_time=None
        self._regime_mid=None
        self._regime_emas=None
        self._regime_variance=0.0
        self._regime_last_jump=0
        self._regime_move=0.0''')
    block='''        if self._regime_time is None:
            self._regime_emas=[mid]*3
            self._regime_mid=mid
            self._regime_last_jump=now
        regime_dt=0 if self._regime_time is None else now-self._regime_time
        change=mid-self._regime_mid
        self._regime_variance=self._regime_variance*exp(-regime_dt/500000)+min(400,change*change)
        if abs(change)>=1:
            self._regime_last_jump=now
            self._regime_move=change
        for i,tau in enumerate((20000,100000,2000000)):
            self._regime_emas[i]+=(1-exp(-regime_dt/tau))*(mid-self._regime_emas[i])
        age=now-self._regime_last_jump
        volatility=min(5,self._regime_variance**0.5)
        move=max(-5,min(5,self._regime_move))*exp(-age/100000)
        features+=tuple(max(-5,min(5,mid-ema)) for ema in self._regime_emas)
        features+=(move,volatility,count_imbalance*volatility,depth_count*move,
                   flow*volatility,min(5,spread),count_imbalance*min(5,spread))
        self._regime_mid,self._regime_time=mid,now
'''
    return replace_once(text,'        self._learn(now,mid)',block+'        self._learn(now,mid)')


def cohorts(base):
    text=replace_once(base,'FEATURE_COUNT = 29','FEATURE_COUNT = 37')
    text=replace_once(text,'        bn = an = bd_n = ad_n = 0','''        bucket_bid=[0,0,0,0]
        bucket_ask=[0,0,0,0]
        bucket_dbid=[0,0,0,0]
        bucket_dask=[0,0,0,0]
        bn = an = bd_n = ad_n = 0''')
    text=replace_once(text,'                weight = min(20,order.quantity)','''                bucket=0 if order.quantity<=5 else 1 if order.quantity<=20 else 2 if order.quantity<=100 else 3
                if order.side==Side.BUY:
                    bucket_dbid[bucket]+=1
                    if distance==0:bucket_bid[bucket]+=1
                else:
                    bucket_dask[bucket]+=1
                    if distance==0:bucket_ask[bucket]+=1
                weight = min(20,order.quantity)''')
    return replace_once(text,'        self._learn(now,mid)',
        '''        features+=tuple((b-a)/max(1,b+a) for b,a in zip(bucket_bid,bucket_ask))
        features+=tuple((b-a)/max(1,b+a) for b,a in zip(bucket_dbid,bucket_dask))
        self._learn(now,mid)''')


def main():
    base=build_candidates(Path('strategies/round2/round2_transfer.py').read_text())['robust_label1']
    base=queue_inventory(base,50,0)
    small=replace_once(base,'                weight = min(20,order.quantity)',
        '                if order.quantity>20:\n                    continue\n                weight = min(20,order.quantity)')
    small=replace_once(small,'bd_value/max(1,bd_r)','(bd_value/bd_r if bd_r else bid)')
    small=replace_once(small,'ad_value/max(1,ad_r)','(ad_value/ad_r if ad_r else ask)')
    cases={'queue50_jump_features':jump_features(base),'queue50_cohorts':cohorts(base),
           'queue50_small_orders':small}
    cases={n:describe(t,'Round-2 development regime-feature hypothesis: '+n+
                      '. Only observed book/price history and matured labels; native rules unchanged.') for n,t in cases.items()}
    run_study(cases,'logs/round2/regime_features',workers=2)


if __name__=='__main__':main()
