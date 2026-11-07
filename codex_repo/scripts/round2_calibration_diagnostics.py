"""Read-only instrumentation of reference fills; verify exact replay parity."""
from collections import deque,defaultdict
from pathlib import Path
import json
from scripts.benchmark import digest,evaluate
from scripts.round2_workbench import BoundaryMarkEngine,load_manifest,write_json
from simulator.main import load_strategy_from_file
from simulator.models import OrderStatus

ROOT=Path('logs/round2_calibration_diagnostics')
SOURCE=Path('strategies/round2/round2_local_209795.py')
assert digest(SOURCE)=='df93cf43167894a1fe00a67b459f32d655ecbc8a5d5a2e4f036f54645e05af90'
Base=type(load_strategy_from_file(SOURCE))


class DiagnosticStrategy(Base):
    def __init__(self):
        super().__init__()
        self.trace_pending=deque()
        self.trace_stats=defaultdict(lambda:dict(quantity=0,callbacks=0,predicted=0.,clipped_mid=0.,raw_mid=0.,future_touch=0.,saturated_quantity=0))
        self.trace_dropped=0
        self.trace_sample_us=None
        self.trace_gates=defaultdict(int)

    def on_private_order_update(self,event):
        record=self._orders.get(event.order_id)
        if record is not None and event.status in (OrderStatus.FILLED,OrderStatus.PARTIALLY_FILLED):
            if self._value_us is not None and 0<=event.timestamp_us-self._value_us<=100000:
                sign=record[0];bucket=int(self._value_spread>=2)
                group=(0 if sign>0 else 1)+2*bucket
                raw=self._bid_value if sign>0 else self._ask_value
                correction=self._cal_groups[group]
                kind='taker' if event.order_id in self._m2_ids or event.order_id==self._hedge_id else 'maker'
                self.trace_pending.append((event.timestamp_us,kind,group,sign,event.fill_price,
                                           event.filled_quantity,raw+correction,abs(correction)>=.49))
        super().on_private_order_update(event)

    def on_order_book_change(self,snapshot,trades):
        super().on_order_book_change(snapshot,trades)
        now=snapshot.timestamp_us
        if self._cached_time!=now:
            return
        mid=(self._cached_bid+self._cached_ask)*.5
        while self.trace_pending and self.trace_pending[0][0]+400000<=now:
            observed,kind,group,sign,price,quantity,predicted,saturated=self.trace_pending.popleft()
            if now-observed>1400000:
                self.trace_dropped+=1;continue
            stats=self.trace_stats[f'{kind}_group{group}']
            realized=sign*(mid-price)
            touch=self._cached_bid if sign>0 else self._cached_ask
            stats['quantity']+=quantity;stats['callbacks']+=1
            stats['predicted']+=quantity*predicted
            stats['clipped_mid']+=quantity*max(-3,min(3,realized))
            stats['raw_mid']+=quantity*realized
            stats['future_touch']+=quantity*sign*(touch-price)
            stats['saturated_quantity']+=quantity*int(saturated)
        if self.trace_sample_us is None or now-self.trace_sample_us>=1000000:
            self.trace_sample_us=now
            self.trace_gates['samples']+=1
            self.trace_gates['buy_allowed']+=int(self._entry_buy_allowed)
            self.trace_gates['sell_allowed']+=int(self._entry_sell_allowed)
            self.trace_gates['buy_saturated']+=int(abs(self._cal_groups[2*int(self._value_spread>=2)])>=.49)
            self.trace_gates['sell_saturated']+=int(abs(self._cal_groups[1+2*int(self._value_spread>=2)])>=.49)


def main():
    m=load_manifest(Path('logs/round2_local_intake'))
    BoundaryMarkEngine.boundaries=(m['first_us']+1800000000,m['development_cutoff_us'],m['validation_cutoff_us'])
    bot=DiagnosticStrategy()
    result=evaluate(bot,Path(m['validation_prefix']),ROOT,600,BoundaryMarkEngine)
    reference=json.loads(Path('research/round2_calibration_dynamics_20261107/results.json').read_text())['rate0.01']
    assert result['result']==reference['result'],'Instrumentation changed replay result'
    groups={}
    for key,row in bot.trace_stats.items():
        qty=row['quantity']
        groups[key]={**row,**{f'{name}_per_lot':row[name]/qty for name in ('predicted','clipped_mid','raw_mid','future_touch')},
                     'saturated_quantity_fraction':row['saturated_quantity']/qty}
    report=dict(source_sha256=digest(SOURCE),data_sha256=m['validation_prefix_sha256'],
        native_result_parity=True,result=result['result'],groups=groups,gates=dict(bot.trace_gates),
        dropped_stale_labels=bot.trace_dropped,unmatured_at_end=len(bot.trace_pending),
        caveat='400ms overlapping descriptive markouts, not realized round trips. Taker predictions are maker-model diagnostics, not calibrated IOC forecasts. Sampled gates are event samples, not exact time weights.')
    write_json(ROOT/'diagnostics.json',report)
    print(json.dumps(dict(parity=True,pnl=result['result']['pnl'],groups=groups,gates=report['gates']),indent=2),flush=True)


if __name__=='__main__':main()
