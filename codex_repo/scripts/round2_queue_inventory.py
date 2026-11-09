"""Causal inventory targets with native priority-preserving order shrinks."""
from pathlib import Path

from scripts.round2_jump_models import build_candidates, replace_once, run_study
from scripts.build_round2_candidates import describe


QUOTE = '''    def _quote(self, now, sign, price):
        current=[(oid,r) for oid,r in self._orders.items() if r[0]==sign and oid!=self._hedge_id]
        limit=self._upper_target if sign>0 else -self._lower_target
        budget=max(0,limit-sign*self.inventory)
        retained=0
        for oid,record in current:
            if price is None or record[1]!=price:
                self._cancel(oid)
                continue
            if record[4]:
                continue
            desired=max(0,min(record[2],budget-retained))
            retained+=record[2]
            if record[3] and oid not in self._modify_pending:
                if desired==0:
                    self._cancel(oid)
                elif desired+10<record[2]:
                    self._modify_pending[oid]=desired
                    self.modify_order(oid,desired)
        if len(current)>=8 or price is None or price<=0:
            return
        reserved=sum(r[2] for r in self._orders.values() if r[0]==sign)
        effective=sum(0 if r[4] else r[2] for r in self._orders.values() if r[0]==sign)
        quantity=min(self.QUOTE_SIZE,budget-effective,self.POSITION_LIMIT-sign*self.inventory-reserved)
        if quantity<=0:
            return
        oid=self.send_order(OrderRequest(side=Side.BUY if sign>0 else Side.SELL,
            price=price,quantity=quantity,order_type=OrderType.LIMIT))
        self._orders[oid]=[sign,price,quantity,False,False,now]
        self._last_action[sign]=now

'''


def queue_inventory(base,band,gain):
    text=replace_once(base,'        self._orders = {}','''        self._orders = {}
        self._modify_pending={}
        self._upper_target=50
        self._lower_target=-50
        self._target_updated=None
        self._target_prediction=0.0''')
    text=replace_once(text,'        record = self._orders[order_id]',
        '''        if order_id in self._modify_pending:
            return
        record = self._orders[order_id]''')
    start=text.index('    def _quote(');end=text.index('    def on_order_book_change(',start)
    text=text[:start]+QUOTE+text[end:]
    text=replace_once(text,'        # Withdraw the side',f'''        if self._target_updated is None or now-self._target_updated>=100000:
            dt=100000 if self._target_updated is None else now-self._target_updated
            self._target_prediction+=(1-exp(-dt/200000))*(prediction-self._target_prediction)
            self._target_updated=now
            target=max(-50,min(50,int({gain}*self._target_prediction)))
            self._upper_target=min(100,target+{band})
            self._lower_target=max(-100,target-{band})
        # Withdraw the side''')
    text=replace_once(text,'        if event.status == OrderStatus.ACCEPTED:',
        '''        if event.status==OrderStatus.MODIFIED:
            record[2]=event.remaining_quantity
            self._modify_pending.pop(event.order_id,None)
            return
        if event.status==OrderStatus.REJECTED and event.order_id in self._modify_pending:
            self._modify_pending.pop(event.order_id,None)
            return
        if event.status == OrderStatus.ACCEPTED:''')
    text=replace_once(text,'        was_hedge = event.order_id == self._hedge_id',
        '''        if event.order_id not in self._orders:
            self._modify_pending.pop(event.order_id,None)
        was_hedge = event.order_id == self._hedge_id''')
    return text


def main():
    robust=build_candidates(Path('strategies/round2/round2_transfer.py').read_text())['robust_label1']
    cases={}
    for name,band,gain in (('queue_target25',25,150),('queue_target50',50,150),('queue_fixed50',50,0)):
        cases[name]=describe(queue_inventory(robust,band,gain),
            'Round-2 priority-preserving inventory target hypothesis: '+name+
            '. Shrinks retain actual reservations until native acknowledgement; native paid overlap remains.')
    run_study(cases,'logs/round2/queue_inventory',workers=2)


if __name__=='__main__':main()
