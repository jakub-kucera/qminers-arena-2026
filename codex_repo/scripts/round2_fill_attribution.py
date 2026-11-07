"""Research-only exact midpoint PnL decomposition and descriptive fill markouts.

Instrumentation never changes native matching, callbacks, positions or fees.
Last valid public midpoint is carried through invalid books. Future markouts
are post-run diagnostics, never features made available to the strategy.
"""
import argparse
import json
from bisect import bisect_left
from collections import defaultdict
from pathlib import Path

from scripts.benchmark import digest, evaluate
from scripts.search_passive import CandidateEngine
from simulator.main import load_strategy_from_file
from simulator.models import OrderStatus, Side


class AttributionEngine(CandidateEngine):
    def __init__(self,strategy,config):
        super().__init__(strategy,config)
        self.reference_mid=None
        self.mid_times=[];self.mid_values=[];self.fills=[]
        self.execution_edge=self.holding_small=self.holding_jump=0.0
        self.previous_cash=self.previous_inventory=0
        self.jump_contributions=[]
        self.volatility_exposure=defaultdict(lambda:[0,0.0,0.0])

    def _advance_time(self,timestamp_us):
        elapsed=max(0,timestamp_us-self.current_ts_us)
        if elapsed and hasattr(self.strategy,'_vol_sigma'):
            sigma=self.strategy._vol_sigma
            boundary=next((v for v in (.5,1,2,4,8) if sigma<=v),None)
            key='sigma<= '+str(boundary) if boundary is not None else 'sigma>8'
            row=self.volatility_exposure[key]
            row[0]+=elapsed
            row[1]+=elapsed*abs(self._inventory)
            row[2]+=elapsed*self.strategy._upper_target
        super()._advance_time(timestamp_us)

    def _private_notify(self,event):
        hedge=event.order_id==getattr(self.strategy,'_hedge_id',None)
        super()._private_notify(event)
        if event.status in (OrderStatus.FILLED,OrderStatus.PARTIALLY_FILLED):
            assert self.reference_mid is not None
            quantity=self._inventory-self.previous_inventory
            cash=self._cash-self.previous_cash
            self.execution_edge+=cash+quantity*self.reference_mid
            self.fills.append((event.timestamp_us,1 if quantity>0 else -1,
                               abs(quantity),event.fill_price,hedge))
            self.previous_cash=self._cash;self.previous_inventory=self._inventory

    def _emit_public_snapshot(self):
        bid=next((o.price for o in self._visible_orders(Side.BUY) if o.owner=='market'),None)
        ask=next((o.price for o in self._visible_orders(Side.SELL) if o.owner=='market'),None)
        if bid is not None and ask is not None and bid<ask:
            mid=(bid+ask)/2
            if mid!=self.reference_mid:
                if self.reference_mid is not None:
                    delta=mid-self.reference_mid
                    value=self._inventory*delta
                    if abs(delta)>=2:
                        self.holding_jump+=value
                        self.jump_contributions.append((self.current_ts_us,delta,self._inventory,value))
                    else:self.holding_small+=value
                self.mid_times.append(self.current_ts_us);self.mid_values.append(mid)
                self.reference_mid=mid
        super()._emit_public_snapshot()

    def attribution(self,result):
        midpoint_value=self._cash+self._inventory*self.reference_mid-self._breach_penalty
        adjustment=result.pnl-midpoint_value
        total=self.execution_edge+self.holding_small+self.holding_jump-self._breach_penalty+adjustment
        assert abs(total-result.pnl)<1e-6,(total,result.pnl)
        markouts={}
        for horizon in (0,5000,100000,400000,2000000,25000000):
            sums=defaultdict(lambda:[0,0.0,0])
            for time,sign,quantity,price,hedge in self.fills:
                target=time+horizon
                if target>self._last_event_us:continue
                index=bisect_left(self.mid_times,target)-1
                if index<0:continue
                value=sign*(self.mid_values[index]-price)
                for group in ('all','hedge' if hedge else 'maker'):
                    sums[group][0]+=quantity;sums[group][1]+=quantity*value;sums[group][2]+=1
            markouts[str(horizon)]={g:dict(lots=r[0],weighted_edge=r[1],
                ticks_per_lot=r[1]/r[0],fill_events=r[2]) for g,r in sums.items() if r[0]}
        return dict(execution_edge_at_previous_mid=self.execution_edge,
            inventory_pnl_mid_changes_below2=self.holding_small,
            inventory_pnl_mid_changes_at_least2=self.holding_jump,
            native_breach_penalty=self._breach_penalty,
            final_native_liquidation_adjustment=adjustment,identity_net_pnl=total,
            worst_jump_contributions=sorted(self.jump_contributions,key=lambda r:r[-1])[:20],
            fill_markouts=markouts,
            volatility_exposure={k:dict(seconds=r[0]/1e6,
                mean_absolute_actual_inventory=r[1]/r[0],mean_planned_cap=r[2]/r[0])
                for k,r in self.volatility_exposure.items() if r[0]},
            limitation='Descriptive post-run markouts at the last valid midpoint strictly before the horizon. Includes fills already closed before that horizon. Hedge classification uses the strategy hedge ID; marketable LIMIT orders are in maker group.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--strategy',type=Path,required=True)
    parser.add_argument('--backtest',type=Path,default=Path('logs/round2/development.csv'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--reference-result',type=Path)
    args=parser.parse_args()
    # Retain the instrumented instance without changing evaluate's configuration.
    instances=[]
    class CapturedEngine(AttributionEngine):
        def __init__(self,*a,**kw):
            super().__init__(*a,**kw);instances.append(self)
    summary=evaluate(load_strategy_from_file(args.strategy),args.backtest,args.output,600,CapturedEngine)
    engine=instances[0]
    if args.reference_result:
        reference=json.loads(args.reference_result.read_text())
        assert summary['result']==reference,'Instrumentation changed native results'
    class Result:
        pnl=summary['result']['pnl']
    report=dict(source=str(args.strategy),source_sha256=digest(args.strategy),
        data=str(args.backtest),data_sha256=digest(args.backtest),native_result=summary['result'],
        instrumentation_verified_against_reference=bool(args.reference_result),
        attribution=engine.attribution(Result()))
    (args.output/'attribution.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
