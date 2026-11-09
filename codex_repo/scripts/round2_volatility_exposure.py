"""Set planned exposure from absolute causal realized volatility in tick units.

Regular 100 ms samples use the preceding observed valid midpoint. EW squared
returns estimate ticks squared per second, without dividing by a historical
volatility baseline. The native matching engine and fees remain unchanged.
"""
from pathlib import Path

from scripts.build_round2_candidates import describe
from scripts.round2_jump_models import build_candidates,replace_once,run_study
from scripts.round2_queue_inventory import queue_inventory


VOLATILITY='''    def _update_absolute_volatility(self,now,mid):
        if self._vol_next is None:
            self._vol_next=now+100000
            self._vol_sample_mid=self._vol_previous_mid=mid
        while self._vol_next<=now:
            change=self._vol_previous_mid-self._vol_sample_mid
            alpha=1-exp(-0.1/VOL_TAU)
            self._vol_variance=(1-alpha)*self._vol_variance+alpha*change*change/0.1
            self._vol_sample_mid=self._vol_previous_mid
            self._vol_next+=100000
            self._vol_samples+=1
        self._vol_previous_mid=mid
        self._vol_sigma=max(0.25,self._vol_variance**0.5)

'''


def volatility_model(base,tau,budget,power):
    text=queue_inventory(base,50,0)
    text=replace_once(text,'        self._orders = {}','''        self._orders = {}
        self._vol_next=None
        self._vol_sample_mid=self._vol_previous_mid=None
        self._vol_variance=1.0
        self._vol_sigma=1.0
        self._vol_samples=0''')
    text=replace_once(text,'    def _learn(self, now, mid):',
        VOLATILITY.replace('VOL_TAU',str(tau))+'    def _learn(self, now, mid):')
    start=text.index('        if self._target_updated is None or now-self._target_updated>=100000:')
    end=text.index('        # Withdraw the side',start)
    block=f'''        self._update_absolute_volatility(now,mid)
        if self._target_updated is None or now-self._target_updated>=100000:
            self._target_updated=now
            cap=max(10,min(100,5*int(({budget}/self._vol_sigma**{power})/5)))
            self._upper_target=cap
            self._lower_target=-cap
'''
    return text[:start]+block+text[end:]


def main():
    base=build_candidates(Path('strategies/round2/round2_transfer.py').read_text())['jump_pause100ms']
    base=replace_once(base,'now-self._invalid_since >= 50_000','now-self._invalid_since >= 0')
    cases={}
    for tau,budget,power in ((10,100,1),(60,100,1),(10,150,1),(10,200,2)):
        name=f'absolute_vol_tau{tau}_risk{budget}_power{power}'
        cases[name]=describe(volatility_model(base,tau,budget,power),
            'Round-2 absolute-volatility exposure hypothesis: '+name+
            '. Sigma is ticks per square-root second, sampled causally each100ms; planned cap10..100; native overlap fees remain.')
    run_study(cases,'logs/round2/absolute_volatility',workers=2)


if __name__=='__main__':main()
