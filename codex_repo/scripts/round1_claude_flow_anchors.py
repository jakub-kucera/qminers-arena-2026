"""Test observed taker limit prices and event counts as public fair-value signals."""
import json
from pathlib import Path

from scripts import round1_claude_improvements as research
from scripts.benchmark import digest
from scripts.check_submission import check
from scripts.round1_aggressor_groups import source_for

ROOT = Path('logs/round1/claude_flow_anchors')


def count_block(tau, cap):
    return f'''        group_decay=exp(-elapsed/{tau})
        for i in range(3):
            self._group_net[i]*=group_decay
            self._group_volume[i]*=group_decay
            self._group_price[i]*=group_decay
        self._rest_count_net*=group_decay
        self._rest_count*=group_decay
        if trades:
            visible={{o.order_id:o for orders in (snapshot.bids,snapshot.asks) for o in orders if o.owner=='market'}}
            arrivals={{}}
            for trade in trades:
                if trade.taker_owner!='market':
                    continue
                row=arrivals.setdefault(trade.taker_order_id,[1 if trade.book_side=='ask' else -1,0,0.0,0,0.0])
                row[1]+=trade.quantity
                row[2]+=trade.quantity*trade.price
                if trade.maker_owner=='user':
                    row[3]+=trade.quantity
                    row[4]+=trade.quantity*trade.price
            for oid,row in arrivals.items():
                direction,quantity,value,own,own_value=row
                group=0 if oid in visible else 1
                price=visible[oid].price if group==0 else value/max(1,quantity)
                quantity+=visible[oid].quantity if group==0 else 0
                weight=min({cap},quantity)
                self._group_net[group]+=direction*weight
                self._group_volume[group]+=weight
                self._group_price[group]+=weight*price
                if group==0:
                    self._rest_count_net+=direction
                    self._rest_count+=1
                if own:
                    weight=min({cap},own)
                    self._group_net[2]+=direction*weight
                    self._group_volume[2]+=weight
                    self._group_price[2]+=weight*own_value/own
'''


def main():
    base=Path('strategies/round1_claude_595k.py').read_text()
    cases={}
    for tau in (100000,500000,1000000):
        source=research.transfer_features(base,source_for(tau,100000))
        cases[f'limit_anchor_{tau}']=source.replace('self._group_price[group]+=trade.quantity*trade.price',
            'self._group_price[group]+=trade.quantity*(visible[trade.taker_order_id].price if group==0 else trade.price)')
        if tau==1000000:
            continue
        for cap in (1,20,100):
            start=source.index('        group_decay=')
            end=source.index('        decay = exp(-elapsed/500_000)',start)
            cases[f'event_cap_{cap}_tau_{tau}']=source[:start]+count_block(tau,cap)+source[end:]
    (ROOT/'sources').mkdir(parents=True,exist_ok=True)
    specs={}
    for name,text in cases.items():
        path=ROOT/'sources'/(name+'.py')
        path.write_text(text)
        assert not check(path),check(path)
        specs[name]={'source_sha256':digest(path)}
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    research.ROOT=ROOT
    screen=research.batch(cases,'logs/round1/screening.csv','screening',workers=2)
    ranked=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)
    full=research.batch(ranked[:3],'data/round1.csv','full',workers=2)
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],
        limitation='Sample tuning. Limit prices are observed only when takers remain in the current public snapshot.'),indent=2)+'\n')
    print('WINNER ANCHORS',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
