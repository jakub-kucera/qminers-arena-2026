"""Fresh limit-quote price centers and cancellation pressure, not only current depth."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/new_quote_value')


def source_for(tau,horizon):
    text=Path('strategies/round1_private_554347.py').read_text().replace('FEATURE_COUNT = 15','FEATURE_COUNT = 21')
    text=text.replace('HORIZON_US = 100000',f'HORIZON_US = {horizon}')
    text=text.replace('        self._orders = {}', '''        self._orders = {}
        self._known_market = {}
        self._new_counts = [0.0]*4
        self._new_values = [0.0]*4
        self._cancel_net = self._cancel_mass = 0.0
        self._new_quote_time = None''',1)
    block=f'''        dt=0 if self._new_quote_time is None else max(0,now-self._new_quote_time)
        self._new_quote_time=now
        decay_new=exp(-dt/{tau})
        for i in range(4):
            self._new_counts[i]*=decay_new
            self._new_values[i]*=decay_new
        self._cancel_net*=decay_new
        self._cancel_mass*=decay_new
        current={{o.order_id:o for orders in (snapshot.bids,snapshot.asks) for o in orders if o.owner=='market'}}
        for oid,order in current.items():
            if oid in self._known_market:
                continue
            distance=bid-order.price if order.side==Side.BUY else order.price-ask
            if distance>3:
                continue
            index=0 if order.side==Side.BUY else 1
            self._new_counts[index]+=1
            self._new_values[index]+=order.price
            if order.quantity<=50:
                self._new_counts[index+2]+=1
                self._new_values[index+2]+=order.price
        traded={{t.maker_order_id for t in trades if t.maker_owner=='market'}}
        for oid,order in self._known_market.items():
            if oid in current or oid in traded:
                continue
            distance=bid-order.price if order.side==Side.BUY else order.price-ask
            if abs(distance)>3:
                continue
            self._cancel_net+=-1 if order.side==Side.BUY else 1
            self._cancel_mass+=1
        self._known_market=current
'''
    text=text.replace('        mid = (bid+ask)*0.5',block+'        mid = (bid+ask)*0.5')
    extra='''(self._new_counts[0]-self._new_counts[1])/(1+self._new_counts[0]+self._new_counts[1]),
                  max(-5,min(5,((self._new_values[0]-mid*self._new_counts[0])/(1+self._new_counts[0])+(self._new_values[1]-mid*self._new_counts[1])/(1+self._new_counts[1]))*0.5)),
                  max(-5,min(5,((self._new_values[2]-mid*self._new_counts[2])/(1+self._new_counts[2])+(self._new_values[3]-mid*self._new_counts[3])/(1+self._new_counts[3]))*0.5)),
                  self._cancel_net/(1+self._cancel_mass),
                  max(-5,min(5,(self._new_values[0]+self._new_values[1]-mid*(self._new_counts[0]+self._new_counts[1]))/(1+self._new_counts[0]+self._new_counts[1]))),
                  (self._new_counts[2]-self._new_counts[3])/(1+self._new_counts[2]+self._new_counts[3])'''
    text=text.replace('robust_imbalance*abs(robust_imbalance))','robust_imbalance*abs(robust_imbalance),'+extra+')')
    return text


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT;specs={}
    for tau in (50000,100000,500000):
        for horizon in (100000,500000):
            name=f'new_quotes_{tau}_{horizon}'
            path=ROOT/'sources'/(name+'.py');path.write_text(source_for(tau,horizon))
            assert not check(path),check(path)
            specs[name]=dict(tau_us=tau,horizon_us=horizon,source_sha256=digest(path))
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/round1/screening.csv','screening',workers=3)
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    full=search_queue.batch(finalists,'data/round1.csv','full',workers=3)
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],parameters=specs[winner],
        limitation='Sample tuning. First-seen quotes are observed at the public depth boundary; nearby-only filters reduce boundary appearance artifacts.'),indent=2)+'\n')
    print('WINNER NEW QUOTES',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
