"""Separate aggressive flow leaving resting liquidity from other aggressive flow."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/aggressor_groups')


def source_for(tau,horizon):
    text=Path('strategies/round1_private_554347.py').read_text().replace('FEATURE_COUNT = 15','FEATURE_COUNT = 23')
    text=text.replace('HORIZON_US = 100000',f'HORIZON_US = {horizon}')
    text=text.replace('        self._orders = {}', '''        self._orders = {}
        self._group_net=[0.0,0.0,0.0]
        self._group_volume=[0.0,0.0,0.0]
        self._group_price=[0.0,0.0,0.0]
        self._rest_count_net=self._rest_count=0.0''',1)
    block=f'''        group_decay=exp(-elapsed/{tau})
        for i in range(3):
            self._group_net[i]*=group_decay
            self._group_volume[i]*=group_decay
            self._group_price[i]*=group_decay
        self._rest_count_net*=group_decay
        self._rest_count*=group_decay
        if trades:
            visible={{o.order_id:o for orders in (snapshot.bids,snapshot.asks) for o in orders if o.owner=='market'}}
            counted=set()
            for trade in trades:
                if trade.taker_owner!='market':
                    continue
                direction=1 if trade.book_side=='ask' else -1
                group=0 if trade.taker_order_id in visible else 1
                self._group_net[group]+=direction*trade.quantity
                self._group_volume[group]+=trade.quantity
                self._group_price[group]+=trade.quantity*trade.price
                if group==0 and trade.taker_order_id not in counted:
                    counted.add(trade.taker_order_id)
                    remaining=visible[trade.taker_order_id]
                    self._group_net[0]+=direction*remaining.quantity
                    self._group_volume[0]+=remaining.quantity
                    self._group_price[0]+=remaining.quantity*remaining.price
                    self._rest_count_net+=direction
                    self._rest_count+=1
                if trade.maker_owner=='user':
                    self._group_net[2]+=direction*trade.quantity
                    self._group_volume[2]+=trade.quantity
                    self._group_price[2]+=trade.quantity*trade.price
'''
    text=text.replace('        decay = exp(-elapsed/500_000)',block+'        decay = exp(-elapsed/500_000)')
    extra='''self._group_net[0]/(1+self._group_volume[0]),
                  self._group_net[1]/(1+self._group_volume[1]),
                  self._group_net[2]/(1+self._group_volume[2]),
                  self._group_volume[0]/(1+self._group_volume[0]+self._group_volume[1]),
                  max(-5,min(5,(self._group_price[0]-mid*self._group_volume[0])/(1+self._group_volume[0]))),
                  max(-5,min(5,(self._group_price[1]-mid*self._group_volume[1])/(1+self._group_volume[1]))),
                  max(-5,min(5,(self._group_price[2]-mid*self._group_volume[2])/(1+self._group_volume[2]))),
                  self._rest_count_net/(1+self._rest_count)'''
    text=text.replace('robust_imbalance*abs(robust_imbalance))',
                      'robust_imbalance*abs(robust_imbalance),'+extra+')')
    return text


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT;specs={}
    for tau in (50000,100000,500000):
        for horizon in (100000,500000):
            name=f'groups_{tau}_{horizon}'
            path=ROOT/'sources'/(name+'.py');path.write_text(source_for(tau,horizon))
            assert not check(path),check(path)
            specs[name]=dict(tau_us=tau,horizon_us=horizon,source_sha256=digest(path))
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/round1/screening.csv','screening',workers=3)
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    full=search_queue.batch(finalists,'data/round1.csv','full',workers=3)
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],parameters=specs[winner],
        limitation='Sample tuning. Groups distinguish visible post-trade resting takers, not provably all G orders versus all IOC orders.'),indent=2)+'\n')
    print('WINNER AGGRESSOR GROUPS',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
