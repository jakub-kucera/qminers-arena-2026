"""Preserve closing quotes relative to actual average entry cost through small dips."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/entry_value')


def source_for(profit,release):
    text=Path('strategies/round1_private_554347.py').read_text()
    text=text.replace('        self._orders = {}','        self._orders = {}\n        self._entry_price = None',1)
    update='''            old_inventory=self.inventory
            new_inventory=old_inventory+record[0]*event.filled_quantity
            if old_inventory==0 or old_inventory*record[0]>0:
                old_price=event.fill_price if self._entry_price is None else self._entry_price
                self._entry_price=(abs(old_inventory)*old_price+event.filled_quantity*event.fill_price)/(abs(old_inventory)+event.filled_quantity)
            elif old_inventory*new_inventory<0:
                self._entry_price=event.fill_price
            elif new_inventory==0:
                self._entry_price=None
'''
    text=text.replace('''        elif event.status in (OrderStatus.FILLED,OrderStatus.PARTIALLY_FILLED):
            self.inventory''', '''        elif event.status in (OrderStatus.FILLED,OrderStatus.PARTIALLY_FILLED):
'''+update+'''            self.inventory''')
    long_condition='True' if release is None else f'mid>=self._entry_price-{release}'
    short_condition='True' if release is None else f'mid<=self._entry_price+{release}'
    decision=f'''        if self._entry_price is not None:
            if self.inventory>0 and {long_condition}:
                sell=max(sell,ceil(self._entry_price+{profit}-1e-9))
            elif self.inventory<0 and {short_condition}:
                buy=min(buy,floor(self._entry_price-{profit}+1e-9))
'''
    text=text.replace('        # Withdraw the side',decision+'        # Withdraw the side')
    return text


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT;specs={}
    for profit in (0,1,2):
        for release in (2,5,None):
            name=f'entry_{profit}_release_{release}'
            path=ROOT/'sources'/(name+'.py');path.write_text(source_for(profit,release))
            assert not check(path),check(path)
            specs[name]=dict(profit_floor_ticks=profit,release_if_mid_loss_exceeds=release,source_sha256=digest(path))
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/round1/screening.csv','screening',workers=3)
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    full=search_queue.batch(finalists,'data/round1.csv','full',workers=3)
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],parameters=specs[winner],
        limitation='Sample tuning. Release threshold only removes the profit floor; it does not guarantee a stop-loss fill.'),indent=2)+'\n')
    print('WINNER ENTRY VALUE',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
