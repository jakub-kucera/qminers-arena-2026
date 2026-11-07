"""Preserve favorable front-of-queue quotes when a forecast proposes shading.

Absolute-volatility sizing is held fixed. This tests queue opportunity value,
not another volatility calibration.
"""
from pathlib import Path

from scripts.build_round2_candidates import describe
from scripts.round2_jump_models import replace_once,run_study


def queue_value(base,maximum_ahead,reduction_only=False):
    text=replace_once(base,'        self._orders = {}',
                     '        self._orders = {}\n        self._quote_fair=None')
    text=replace_once(text,'        self._cached_bid,self._cached_ask,self._cached_time = bid,ask,now',
        '        self._quote_fair=fair\n        self._cached_bid,self._cached_ask,self._cached_time = bid,ask,now')
    condition=' and sign*self.inventory<0' if reduction_only else ''
    old='''            if price is None or record[1]!=price:
                self._cancel(oid)
                continue'''
    new=f'''            touch=self._cached_bid if sign>0 else self._cached_ask
            keep_front=(price is not None and self._quote_fair is not None and
                record[1]==touch and not record[4] and
                self.queue_ahead.get(oid,1000000)<={maximum_ahead} and
                sign*(self._quote_fair-record[1])>=0.1{condition})
            if (price is None or record[1]!=price) and not keep_front:
                self._cancel(oid)
                continue'''
    return replace_once(text,old,new)


def main():
    base=Path('strategies/round2_research/round2_absolute_variance_112379.py').read_text()
    cases={}
    for name,ahead,reduction in (('front100_keep',100,False),('front500_keep',500,False),
                                 ('front100_reduce',100,True)):
        cases[name]=describe(queue_value(base,ahead,reduction),
            'Development-only queue opportunity-value hypothesis: '+name+
            '. Volatility sizing held fixed; current/past queue and fair estimate only.')
    run_study(cases,'logs/round2/queue_value',workers=3)


if __name__=='__main__':main()
