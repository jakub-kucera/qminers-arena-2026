"""No-trade comparison of development tapes, spread tails and sampled price moves."""
import argparse
import heapq
import json
import statistics
from collections import Counter
from pathlib import Path

from scripts.benchmark import digest
from simulator.simulator import ExchangeSimulator,SimulationConfig
from simulator.strategy import BaseStrategy


class DynamicsProbe(BaseStrategy):
    def __init__(self,period_us=25000000):
        super().__init__()
        self.period_us=period_us
        self.first=self.last=self.next_sample=None
        self.previous=None
        self.spread_time=Counter()
        self.samples=[]
        self.jumps=Counter()
        self.largest=[]
        self.low=self.high=None

    def on_order_book_change(self,snapshot,trades):
        now=snapshot.timestamp_us
        if self.first is None:
            self.first=now;self.next_sample=now+self.period_us
        if self.previous is not None:
            self.spread_time[self.previous[1]]+=now-self.last
        while self.next_sample<=now:
            self.samples.append((self.next_sample,self.previous[0] if self.previous is not None else None))
            self.next_sample+=self.period_us
        bid=next((o.price for o in snapshot.bids if o.owner=='market'),None)
        ask=next((o.price for o in snapshot.asks if o.owner=='market'),None)
        current=((bid+ask)/2,ask-bid) if bid is not None and ask is not None and bid<ask else None
        if current is not None:
            mid,spread=current
            self.low=mid if self.low is None else min(self.low,mid)
            self.high=mid if self.high is None else max(self.high,mid)
            if self.previous is not None:
                change=mid-self.previous[0]
                if change:
                    self.jumps[abs(change)]+=1
                    row=(abs(change),now,change,mid,spread)
                    if len(self.largest)<20:heapq.heappush(self.largest,row)
                    elif row>self.largest[0]:heapq.heapreplace(self.largest,row)
        self.previous=current;self.last=now

    def report(self):
        differences=[(b[1]-a[1]) for a,b in zip(self.samples,self.samples[1:])
                     if a[1] is not None and b[1] is not None]
        ordered=sorted(abs(x) for x in differences)
        total=sum(self.spread_time.values())
        def quantile(q):return ordered[min(len(ordered)-1,int(q*(len(ordered)-1)))] if ordered else None
        return {'duration_seconds':(self.last-self.first)/1e6,'sample_period_seconds':self.period_us/1e6,
            'valid_return_intervals':len(differences),
            'sampled_return_sd_ticks':statistics.stdev(differences) if len(differences)>1 else None,
            'absolute_return_quantiles':{str(q):quantile(q) for q in (.5,.9,.99)},
            'mid_range':[self.low,self.high],
            'spread_time_fraction':{str(s):t/total for s,t in sorted(self.spread_time.items())} if total else {},
            'spread_tail_time_fraction':{str(c):sum(t for s,t in self.spread_time.items() if s>c)/total if total else None for c in (1,2,5,10,20)},
            'valid_to_valid_mid_jumps':{str(c):sum(n for j,n in self.jumps.items() if j>=c) for c in (.5,1,2,5,10)},
            'largest_valid_to_valid_jumps':sorted(self.largest,reverse=True),
            'price_samples':self.samples,
            'limitations':['Development data only. Prices sampled immediately before the next event, not after it.',
                           '25-second samples omit shorter movements; micro-jumps can be transient quote effects.']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backtest',type=Path,action='append',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();reports={}
    for path in args.backtest:
        label=str(path)
        probe=DynamicsProbe();result=ExchangeSimulator(probe,SimulationConfig(public_depth=20)).run(path)
        assert result.pnl==0 and result.traded_volume==0
        reports[label]=probe.report();reports[label]['data_sha256']=digest(path)
        print(label,json.dumps({k:v for k,v in reports[label].items() if k not in
            ('price_samples','spread_time_fraction','largest_valid_to_valid_jumps')}),flush=True)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(reports,indent=2)+'\n')


if __name__=='__main__':main()
