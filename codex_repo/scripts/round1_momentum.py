"""Round-1 comparison of forecast-driven taker entries and passive exits."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/momentum_maker')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT
    base=Path('logs/round1/target550/sources/execution_13.py').read_text()
    specs={}
    for index,(trigger,timeout) in enumerate((t,d) for t in (.05,.1,.2) for d in (500000,2000000)):
        n=f'momentum_{index}'
        text=base.replace('        self._orders = {}','''        self._orders = {}
        self._entry_basis = None
        self._opened_us = None
        self._last_entry_us = -200000''',1)
        text=text.replace('        if quantity <= 0 or (current and quantity < 1):','''        quantity = min(quantity,max(0,-sign*self.inventory-reserved))
        if quantity <= 0 or (current and quantity < 1):''')
        start=text.index('        fair = mid +')
        end=text.index('    def on_private_order_update',start)
        public=f'''        if self.inventory == 0:
            for oid in list(self._orders):
                self._cancel(oid)
            if not self._orders and self._labels >= self.MIN_LABELS and abs(prediction) > {trigger} and now-self._last_entry_us >= 200000:
                sign = 1 if prediction > 0 else -1
                quantity = min(100,aq if sign > 0 else bq)
                if quantity > 0:
                    price = ask if sign > 0 else bid
                    oid = self.send_order(OrderRequest(side=Side.BUY if sign > 0 else Side.SELL,
                        price=price,quantity=quantity,order_type=OrderType.IOC))
                    self._orders[oid] = [sign,price,quantity,False,False,now]
                    self._last_entry_us = now
        elif self._entry_basis is not None:
            sign = -1 if self.inventory > 0 else 1
            if now-self._opened_us > {timeout} or prediction*self.inventory < -25:
                price = ask if sign < 0 else bid
            else:
                price = max(ask,ceil(self._entry_basis+1)) if sign < 0 else min(bid,floor(self._entry_basis-1))
            for oid,r in list(self._orders.items()):
                if r[0] != sign:
                    self._cancel(oid)
            self._quote(now,sign,price)

'''
        text=text[:start]+public+text[end:]
        text=text.replace('    def on_private_order_update(self, event):','''    def on_private_order_update(self, event):
        before = self.inventory''')
        text+='''
        if event.status in (OrderStatus.FILLED,OrderStatus.PARTIALLY_FILLED):
            if before == 0:
                self._entry_basis = event.fill_price
                self._opened_us = event.timestamp_us
            elif abs(self.inventory) > abs(before):
                self._entry_basis = (abs(before)*self._entry_basis+event.filled_quantity*event.fill_price)/abs(self.inventory)
            if self.inventory == 0:
                self._entry_basis = None
                self._opened_us = None
'''
        path=ROOT/'sources'/(n+'.py');path.write_text(text)
        assert not check(path),check(path)
        specs[n]={'entry_threshold':trigger,'timeout_us':timeout,'profit_ticks':1,'sha256':digest(path)}
    (ROOT/'specifications.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/round1/screening.csv','screening')
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:2]
    finalists=[n for n in finalists if screen[n]['result']['pnl']>141000]
    full=search_queue.batch(finalists,'data/round1.csv','full') if finalists else {}
    winner=max(full,key=lambda n:full[n]['result']['pnl']) if full else None
    (ROOT/'winner.json').write_text(json.dumps({'name':winner,'parameters':specs.get(winner),
        'result':full.get(winner),'limitation':'Further tuning on already evaluated round-1 data.'},indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'] if winner else 'no prefix improvement',flush=True)


if __name__=='__main__':main()
