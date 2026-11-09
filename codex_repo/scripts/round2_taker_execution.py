"""Observe LIMIT/IOC execution without changing native fills or strategy actions."""
import json
from collections import Counter
from pathlib import Path

from scripts.benchmark import digest,evaluate
from scripts.round2_taker_audit import TakerAuditEngine
from scripts.round2_workbench import load_manifest,write_json
from simulator.main import load_strategy_from_file
from simulator.models import OrderStatus


class ExecutionAudit(TakerAuditEngine):
    def __init__(self,strategy,config):
        super().__init__(strategy,config)
        self.execution_orders={}
        self.execution_counts={}

    def submit_order(self,request):
        oid=super().submit_order(request)
        kind=request.order_type.value
        self.execution_orders[oid]=[kind,request.quantity,0]
        counts=self.execution_counts.setdefault(kind,Counter())
        counts['submitted_orders']+=1
        counts['submitted_lots']+=request.quantity
        return oid

    def _private_notify(self,event):
        row=self.execution_orders.get(event.order_id)
        if row is None:
            # A delayed cancel may reject after the order already terminated.
            super()._private_notify(event)
            return
        counts=self.execution_counts[row[0]]
        if event.status in (OrderStatus.FILLED,OrderStatus.PARTIALLY_FILLED):
            if row[2]==0:counts['orders_with_a_fill']+=1
            row[2]+=event.filled_quantity
            counts['filled_lots']+=event.filled_quantity
        if event.status in (OrderStatus.FILLED,OrderStatus.CANCELED):
            counts['terminal_orders']+=1
            counts['unfilled_lots_at_terminal']+=max(0,row[1]-row[2])
            if row[2]==0:counts['terminal_without_any_fill']+=1
        super()._private_notify(event)
        if event.status in (OrderStatus.FILLED,OrderStatus.CANCELED):
            del self.execution_orders[event.order_id]


def main():
    source=Path('strategies/round2_taker_liquidity_269920.py')
    previous=json.loads(Path('results/round2_taker_liquidity_269920.json').read_text())
    assert digest(source)==previous['source_sha256']
    m=load_manifest(Path('logs/round2'))
    instances=[]
    def factory(strategy,config):
        engine=ExecutionAudit(strategy,config);instances.append(engine);return engine
    result=evaluate(load_strategy_from_file(source),Path(m['data']),Path('logs/round2/taker_execution'),1000,factory)
    assert result['result']==previous['evaluation']['result'],'Instrumentation changed native result'
    engine=instances[0]
    assert sum(c['filled_lots'] for c in engine.execution_counts.values())==result['result']['traded_volume']
    report=dict(source=str(source),source_sha256=digest(source),data_sha256=m['data_sha256'],
        unchanged_result=True,result=result['result'],by_order_type=engine.execution_counts,
        note='Order request types, not inferred maker/taker fill roles. No fill miss alone establishes profitable opportunity; unfilled orders may have avoided losses.')
    write_json(Path('results/round2_taker_execution.json'),report)
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
