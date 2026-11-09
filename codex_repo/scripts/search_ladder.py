"""V2 tuning of pre-positioned price ladders with a common exposure budget."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/sample_v2/ladder_search')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT
    base=Path('logs/sample_v2/target310/sources/variant_04.py').read_text()
    start=base.index('    def _quote(');end=base.index('    def on_order_book_change(',start)
    specs={}
    for index,weights in enumerate(((.9,.1),(.75,.25),(.5,.5),(.7,.2,.1))):
        n=f'ladder_{index}'
        method=f'''    def _quote(self, now, sign, price):
        current = [(oid,r) for oid,r in self._orders.items() if r[0] == sign]
        levels = [] if price is None else [(price-sign*i,w) for i,w in enumerate({weights}) if price-sign*i > 0]
        wanted = {{p for p,w in levels}}
        for oid,r in current:
            if r[1] not in wanted:
                self._cancel(oid)
        if not levels or now-self._last_action[sign] < self.REQUOTE_US:
            return
        capacity = self.POSITION_LIMIT-sign*self.inventory
        reserved = sum(r[2] for oid,r in current)
        free = max(0,capacity-reserved)
        for p,weight in levels:
            at_price = [(oid,r) for oid,r in current if r[1] == p]
            if len(at_price) >= 4:
                continue
            deficit = max(0,int(capacity*weight)-sum(r[2] for oid,r in at_price))
            quantity = min(self.QUOTE_SIZE,free,deficit)
            if quantity < 5:
                continue
            oid = self.send_order(OrderRequest(side=Side.BUY if sign > 0 else Side.SELL,
                price=p,quantity=quantity,order_type=OrderType.LIMIT))
            self._orders[oid] = [sign,p,quantity,False,False,now]
            free -= quantity
            self._last_action[sign] = now

'''
        text=base[:start]+method+base[end:]
        path=ROOT/'sources'/(n+'.py');path.write_text(text)
        assert not check(path),check(path)
        specs[n]={'level_weights':weights,'sha256':digest(path)}
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/sample_v2/search/screening.csv','screening')
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:2]
    finalists=[n for n in finalists if screen[n]['result']['pnl']>88000]
    full=search_queue.batch(finalists,'data/sample_v2.csv','full') if finalists else {}
    winner=max(full,key=lambda n:full[n]['result']['pnl']) if full else None
    (ROOT/'winner.json').write_text(json.dumps({'name':winner,'parameters':specs.get(winner),
        'result':full.get(winner),'limitation':'Tuned on previously evaluated v2.'},indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'] if winner else 'no prefix improvement',flush=True)


if __name__=='__main__':main()
