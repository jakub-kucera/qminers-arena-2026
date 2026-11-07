"""Spread the strict exposure budget across persistent FIFO price levels."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/ladder')


def source_for(weights,resize):
    text=Path('strategies/round1_private_554347.py').read_text()
    start=text.index('    def _quote(');end=text.index('    def on_order_book_change',start)
    method=f'''    def _quote(self, now, sign, price):
        capacity=self.POSITION_LIMIT-sign*self.inventory
        weights={weights!r}
        targets={{}}
        if price is not None:
            quantities=[int(max(0,capacity)*w) for w in weights]
            quantities[0]+=max(0,capacity)-sum(quantities)
            targets={{price-sign*i:q for i,q in enumerate(quantities) if q>0 and price-sign*i>0}}
        current=[(oid,r) for oid,r in self._orders.items() if r[0]==sign]
        for oid,r in current:
            if r[1] not in targets:
                self._cancel(oid)
'''
    if resize:
        method+='''        for level,target in targets.items():
            at_level=[(oid,r) for oid,r in current if r[1]==level]
            excess=sum(r[2] for oid,r in at_level)-target
            for oid,r in reversed(at_level):
                if excess<=0:
                    break
                reduction=min(r[2],excess)
                if reduction==r[2]:
                    self._cancel(oid)
                elif r[3] and not r[4] and r[6] is None:
                    r[6]=r[2]-reduction
                    self.modify_order(oid,r[6])
                excess-=reduction
'''
    method+='''        reserved=sum(r[2] for oid,r in current)
        free=capacity-reserved
        for level,target in targets.items():
            if free<=0 or len(current)>=32:
                break
            at_level=sum(r[2] for oid,r in current if r[1]==level)
            quantity=min(self.QUOTE_SIZE,free,target-at_level)
            if quantity<=0:
                continue
            oid=self.send_order(OrderRequest(side=Side.BUY if sign>0 else Side.SELL,
                price=level,quantity=quantity,order_type=OrderType.LIMIT))
            record=[sign,level,quantity,False,False,now,None]
            self._orders[oid]=record
            current.append((oid,record))
            free-=quantity

'''
    text=text[:start]+method+text[end:]
    text=text.replace('''        elif event.status == OrderStatus.CANCELED:''','''        elif event.status == OrderStatus.MODIFIED:
            record[2]=event.remaining_quantity
            record[6]=None
        elif event.status == OrderStatus.CANCELED:''')
    text=text.replace('''            else:
                record[4] = False''','''            else:
                record[4] = False
                record[6] = None''')
    return text


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT;specs={}
    distributions=[(0.8,0.2),(0.6,0.3,0.1),(0.8,0.1,0.1),(0.5,0.25,0.25)]
    for i,weights in enumerate(distributions):
        for resize in (False,True):
            name=f'ladder_{i}_resize_{resize}'
            path=ROOT/'sources'/(name+'.py');path.write_text(source_for(weights,resize))
            assert not check(path),check(path)
            specs[name]=dict(weights=weights,resize=resize,source_sha256=digest(path))
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/round1/screening.csv','screening',workers=3)
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    full=search_queue.batch(finalists,'data/round1.csv','full',workers=3)
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],parameters=specs[winner],
        limitation='Sample tuning; every outstanding quantity remains reserved until fill/cancel/modify confirmation.'),indent=2)+'\n')
    print('WINNER LADDER',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
