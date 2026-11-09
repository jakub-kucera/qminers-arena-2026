"""Separate strict-100 IOC family for price dislocations; no volatility sizing.

Trades only when predicted return exceeds crossing cost. Uses a single IOC at
a time and fixed20-lot entries, with causal labels and native latency/fees.
"""
import argparse
from pathlib import Path

from scripts.build_round2_candidates import describe
from scripts.round2_jump_models import replace_once,run_study


STRUCTURE='''        bid_levels={}
        ask_levels={}
        for o in snapshot.bids:
            if o.owner=='market':bid_levels[o.price]=bid_levels.get(o.price,0)+1
        for o in snapshot.asks:
            if o.owner=='market':ask_levels[o.price]=ask_levels.get(o.price,0)+1
        bprices=sorted(bid_levels,reverse=True)
        aprices=sorted(ask_levels)
        bmode=max(bid_levels,key=lambda p:bid_levels[p])
        amode=max(ask_levels,key=lambda p:ask_levels[p])
        bmedian=sorted(o.price for o in snapshot.bids if o.owner=='market')
        amedian=sorted(o.price for o in snapshot.asks if o.owner=='market')
        mode_center=(bmode+amode)*.5
        median_center=(bmedian[len(bmedian)//2]+amedian[len(amedian)//2])*.5
        mean_center=(sum(bmedian)/len(bmedian)+sum(amedian)/len(amedian))*.5
        bgap=bprices[0]-bprices[1] if len(bprices)>1 else 0
        agap=aprices[1]-aprices[0] if len(aprices)>1 else 0
        bspan=bprices[0]-bprices[-1]
        aspan=aprices[-1]-aprices[0]
        features+=tuple(max(-20,min(20,x)) for x in
            (mode_center-mid,median_center-mid,mean_center-mid,agap-bgap,
             bspan-aspan,(len(bmedian)-len(amedian))/max(1,len(bmedian)+len(amedian)),
             count_imbalance*spread,flow*spread))
'''

TRADING='''        self._cached_bid,self._cached_ask,self._cached_time=bid,ask,now
        if self._orders or spread>8:
            return
        if self.inventory:
            if self._taker_entry_us is not None and now-self._taker_entry_us<self.HORIZON_US:
                return
            sign=-1 if self.inventory>0 else 1
            quantity=abs(self.inventory)
        else:
            if self._labels<self.MIN_LABELS or abs(prediction)<=spread*.5+0.25:
                return
            sign=1 if prediction>0 else -1
            quantity=20
            self._taker_entry_us=now
        price=ask if sign>0 else bid
        oid=self.send_order(OrderRequest(side=Side.BUY if sign>0 else Side.SELL,
            price=price,quantity=quantity,order_type=OrderType.IOC))
        self._orders[oid]=[sign,price,quantity,False,False,now]

'''


def taker_source(base,horizon,fixed_center=False):
    text=replace_once(base,'FEATURE_COUNT = 29','FEATURE_COUNT = 37')
    text=replace_once(text,'HORIZON_US = 400000',f'HORIZON_US = {horizon}')
    text=replace_once(text,'MODEL_MEMORY_US = 100000000000','MODEL_MEMORY_US = 300000000')
    text=replace_once(text,'POSITION_LIMIT = 1000','POSITION_LIMIT = 100')
    text=replace_once(text,'        self._orders = {}','        self._orders = {}\n        self._taker_entry_us=None')
    start=text.index('    def _quote(');end=text.index('    def on_order_book_change(',start)
    text=text[:start]+'    def _quote(self,now,sign,price):\n        return\n\n'+text[end:]
    text=replace_once(text,'        self._learn(now,mid)',STRUCTURE+'        self._learn(now,mid)')
    text=replace_once(text,'prediction = max(-2.0,min(2.0,sum(w*x for w,x in zip(self._weights,features))))',
        'prediction = max(-20.0,min(20.0,sum(w*x for w,x in zip(self._weights,features))))')
    if fixed_center:
        text=replace_once(text,'        self._labels = 0','        self._labels = self.MIN_LABELS')
        text=replace_once(text,'        self._learn(now,mid)','        # Fixed observed-book dislocation model; no fitting.')
    start=text.index('        fair = mid + ');end=text.index('    def on_private_order_update(',start)
    replacement=('        prediction=0.5*(mode_center-mid)\n' if fixed_center else '')+TRADING
    text=text[:start]+replacement+text[end:]
    return text


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers',type=int,default=1)
    args=parser.parse_args()
    base=Path('strategies/round2/round2_transfer.py').read_text()
    cases={}
    for horizon,center in ((100000,False),(400000,False),(100000,True)):
        name=f'dislocation_ioc_h{horizon}_'+('mode_center' if center else 'learned')
        cases[name]=describe(taker_source(base,horizon,center),
            'Development-only dislocation IOC hypothesis: '+name+
            '. Fixed20-lot entries, single pending order,100-lot wall; no absolute-volatility sizing.')
    run_study(cases,'logs/round2/dislocation_taker',workers=args.workers)


if __name__=='__main__':main()
