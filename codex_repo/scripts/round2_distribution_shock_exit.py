"""Exit inventory opposed to an observed price shock when crossing is affordable.

Public jumps of at least2ticks show continuation over100ms in the descriptive
sample. This tests executable exits with the native5ms latency and a one-tick
IOC price allowance. It does not open directional positions or change risk caps.
"""
import argparse
from pathlib import Path

from scripts.build_round2_candidates import describe
from scripts.round2_full_public_study import run_public_study
from scripts.round2_jump_models import replace_once


def shock_exit(base,max_spread):
    text=replace_once(base,'        self._orders = {}','''        self._orders = {}
        self._shock_sign=0
        self._shock_until=0''')
    text=replace_once(text,'            self._pause_until=now+100000',
        '''            self._pause_until=now+100000
            self._shock_sign=1 if mid>self._last_mid else -1
            self._shock_until=now+100000''')
    text=replace_once(text,'        if abs(self.inventory) <= 100 or self._hedge_id is not None:',
        '''        if self.inventory==0 or self._hedge_id is not None:''')
    text=replace_once(text,'        sign = -1 if self.inventory > 0 else 1',f'''        exiting=(now<self._shock_until and self.inventory*self._shock_sign<0
            and self._cached_ask-self._cached_bid<={max_spread})
        desired=abs(self.inventory) if exiting else max(0,abs(self.inventory)-100)
        if desired<=0:
            return
        sign = -1 if self.inventory > 0 else 1''')
    text=replace_once(text,'quantity = min(abs(self.inventory)-100,max(0,self.POSITION_LIMIT-sign*self.inventory-reserved))',
        'quantity = min(desired,max(0,self.POSITION_LIMIT-sign*self.inventory-reserved))')
    text=replace_once(text,'        price = self._cached_ask+10 if sign > 0 else max(1,self._cached_bid-10)',
        '''        allowance=1 if exiting else 10
        price = self._cached_ask+allowance if sign > 0 else max(1,self._cached_bid-allowance)''')
    return text


def main():
    p=argparse.ArgumentParser();p.add_argument('--workers',type=int,default=2);a=p.parse_args()
    base=Path('strategies/round2_distribution_rich_167958.py').read_text()
    cases={f'distribution_shock_exit_spread{spread}':describe(shock_exit(base,spread),
        'Observed-shock inventory exit with affordable spread. Native latency/risk limits unchanged; reused-public tuning.')
        for spread in (2,4)}
    run_public_study(cases,'logs/round2/distribution_research/shock_replays',workers=a.workers)


if __name__=='__main__':main()
