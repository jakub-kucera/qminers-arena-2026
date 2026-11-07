"""Gate new exposure by queue service time estimated from trades/cancellations.

Uses actual quantity ahead and observed recent opposing trade/cancel flow.
Reduction quotes remain available. Saved volatility sizing is held fixed.
"""
from pathlib import Path

from scripts.build_round2_candidates import describe
from scripts.round2_jump_models import replace_once,run_study


def queue_wait(base,maximum_wait):
    text=replace_once(base,'        self._orders = {}','''        self._orders = {}
        self._queue_bid_quantity=self._queue_ask_quantity=0
        self._cancel_bid_quantity=self._cancel_ask_quantity=0.0''')
    text=replace_once(text,'        self._net *= decay',
        '''        self._cancel_bid_quantity*=decay
        self._cancel_ask_quantity*=decay
        self._net *= decay''')
    text=replace_once(text,'            self._cancel_net+=-1 if order.side==Side.BUY else 1',
        '''            if order.side==Side.BUY and order.price==bid:
                self._cancel_bid_quantity+=order.quantity
            elif order.side==Side.SELL and order.price==ask:
                self._cancel_ask_quantity+=order.quantity
            self._cancel_net+=-1 if order.side==Side.BUY else 1''')
    text=replace_once(text,'        self._cached_bid,self._cached_ask,self._cached_time = bid,ask,now',
        '''        self._queue_bid_quantity,self._queue_ask_quantity=bq,aq
        self._cached_bid,self._cached_ask,self._cached_time = bid,ask,now''')
    anchor='''        limit=self._upper_target if sign>0 else -self._lower_target'''
    block=f'''        if price is not None and sign*self.inventory>=0:
            ahead=self._queue_bid_quantity if sign>0 else self._queue_ask_quantity
            known=[self.queue_ahead[oid] for oid,r in current
                   if r[1]==price and not r[4] and oid in self.queue_ahead]
            if known:ahead=min(known)
            rate=(self._volume-self._net+2*self._cancel_bid_quantity if sign>0 else
                  self._volume+self._net+2*self._cancel_ask_quantity)
            if ahead/max(100,rate)>{maximum_wait}:
                for oid,_ in current:self._cancel(oid)
                return
'''
    return replace_once(text,anchor,block+anchor)


def main():
    base=Path('strategies/round2_research/round2_absolute_variance_112379.py').read_text()
    cases={}
    for wait in (.1,.25,.5):
        name=f'queue_expected_wait_{wait}'
        cases[name]=describe(queue_wait(base,wait),
            'Development-only queue service-time entry hypothesis: '+name+
            '. Saved risk sizing held fixed; only causal quantities, trades and cancellations.')
    run_study(cases,'logs/round2/queue_wait',workers=2)


if __name__=='__main__':main()
