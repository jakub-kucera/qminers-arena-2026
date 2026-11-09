"""Test whether the learned conditional fill edge should also set quote prices.

These two followups reuse the frozen167958 trees; no additional fitting and
no volatility-size changes. Existing latency, queue and reservation handling
remain authoritative. Full public outcomes are reused selection diagnostics.
"""
import argparse
from pathlib import Path

from scripts.build_round2_candidates import describe
from scripts.round2_full_public_study import run_public_study
from scripts.round2_jump_models import replace_once


def pricing_source(base,mode):
    text=replace_once(base,'        self._orders = {}','''        self._orders = {}
        self._pricing_time=None
        self._pricing_bid=self._pricing_ask=None
        self._pricing_buyedge=self._pricing_selledge=0.0''')
    block='''        if (self._pricing_time is None or now-self._pricing_time>=20000
                or bid!=self._pricing_bid or ask!=self._pricing_ask):
            self._pricing_buyedge=self._predict_fixed_trees(self._fill_value_frame(1,bid,mid,features))
            self._pricing_selledge=self._predict_fixed_trees(self._fill_value_frame(-1,ask,mid,features))
            self._pricing_time=now;self._pricing_bid,self._pricing_ask=bid,ask
'''
    if mode=='head_prices':
        block+='''        buy=bid if self._pricing_buyedge>=0 else max(1,bid-1)
        sell=ask if self._pricing_selledge>=0 else ask+1
'''
    elif mode=='retreat_negative':
        block+='''        if self._pricing_buyedge<0 and buy==bid and self.inventory>=0:
            buy=max(1,bid-1)
        if self._pricing_selledge<0 and sell==ask and self.inventory<=0:
            sell=ask+1
'''
    else:raise ValueError(mode)
    return replace_once(text,'        if self._last_mid is not None and abs(mid-self._last_mid)>=2:',
        block+'        if self._last_mid is not None and abs(mid-self._last_mid)>=2:')


def main():
    p=argparse.ArgumentParser();p.add_argument('--workers',type=int,default=2);a=p.parse_args()
    base=Path('strategies/round2_distribution_rich_167958.py').read_text()
    cases={f'distribution_{mode}':describe(pricing_source(base,mode),
        'Distribution-based quote-price hypothesis '+mode+'. Frozen first60% fill trees; reused public comparison; risk constants unchanged.')
        for mode in ('head_prices','retreat_negative')}
    run_public_study(cases,'logs/round2/distribution_research/pricing_replays',workers=a.workers)


if __name__=='__main__':main()
