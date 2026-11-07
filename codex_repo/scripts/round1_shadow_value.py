"""Supervised value of hypothetical passive orders, including delay and FIFO.

Research-only shadow orders never alter the native book. Outcomes use raw tape
events; inputs use only public snapshots. Fixed models train on supplied data;
overlap with evaluation is recorded explicitly. First-fill markout is a proxy
for whole-policy PnL, which must still be measured by the unmodified engine.
"""
from array import array
from collections import deque
import json
from math import log
from pathlib import Path
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.utils.parallel import _get_threadpool_controller
from simulator.main import load_strategy_from_file
from simulator.models import MarketOperation,Side
from simulator.simulator import ExchangeSimulator,SimulationConfig
from scripts.round1_online_trees import source_for
from scripts import search_queue
from scripts.check_submission import check
from scripts.benchmark import digest

ROOT=Path('logs/round1/shadow_value')


def collect():
    path=ROOT/'features.npz'
    if path.exists():return np.load(path)
    source=ROOT/'collector_base.py';source.write_text(source_for(40,7,15000))
    parent=load_strategy_from_file(source).__class__
    class Collector(parent):
        def __init__(self):
            super().__init__();self.joins=deque();self.active=[];self.outcomes=deque()
            self.rows=array('d');self.last_shadow=-100000;self.filled=0;self.expired=0
        def _quote(self,*args):pass
        def _fit_trees(self,*args):pass
        def _learn(self,now,mid):
            while self._observations and self._observations[0][0]+100000 <= now:
                self._observations.popleft()
        def finish(self,shadow,stamp,price,quantity):
            self.outcomes.append((stamp+100000,shadow,price,quantity));self.filled+=1
        def before(self,event,book):
            now=event.timestamp_us
            while self.joins and self.joins[0]['ready'] <= now:
                s=self.joins.popleft();side=s['side'];opposite=Side.SELL if side==1 else Side.BUY
                crossed=None
                for order in book.iter_levels(opposite):
                    if (side==1 and order.price<=s['price']) or (side==-1 and order.price>=s['price']):
                        crossed=order
                    break
                if crossed is not None:
                    self.finish(s,s['ready'],crossed.price,min(100,crossed.remaining_quantity))
                else:
                    ownside=Side.BUY if side==1 else Side.SELL
                    s['ahead']=tuple(o.order_id for o in book.iter_levels(ownside) if o.price==s['price'])
                    self.active.append(s)
            keep=[]
            for s in self.active:
                if now>=s['expiry']:
                    self.rows.extend((s['stamp'],0.0,0.0,*s['features']));self.expired+=1
                    continue
                filled=0
                if event.operation==MarketOperation.INSERT:
                    crosses=(s['side']==1 and event.side==Side.SELL and event.price<=s['price']) or (s['side']==-1 and event.side==Side.BUY and event.price>=s['price'])
                    if crosses:
                        ownside=Side.BUY if s['side']==1 else Side.SELL
                        better=0
                        for order in book.iter_levels(ownside):
                            if (s['side']==1 and order.price>s['price']) or (s['side']==-1 and order.price<s['price']):
                                better+=order.remaining_quantity
                            else:break
                        ahead=0
                        for oid in s['ahead']:
                            order=book.get(oid)
                            if order is not None:ahead+=order.remaining_quantity
                        filled=min(100,max(0,event.volume-better-ahead))
                if filled:self.finish(s,now,s['price'],filled)
                else:keep.append(s)
            self.active=keep
        def on_order_book_change(self,snapshot,trades):
            super().on_order_book_change(snapshot,trades)
            bids=[o for o in snapshot.bids if o.owner=='market'];asks=[o for o in snapshot.asks if o.owner=='market']
            if not bids or not asks:return
            now=snapshot.timestamp_us;bid=bids[0].price;ask=asks[0].price;mid=(bid+ask)*0.5
            while self.outcomes and self.outcomes[0][0]<=now:
                due,s,price,quantity=self.outcomes.popleft()
                if now-due<=1000000:
                    payoff=quantity/100*s['side']*(mid-price)
                    self.rows.extend((s['stamp'],payoff,1.0,*s['features']))
            if now-self.last_shadow<50000 or not self._observations or self._observations[-1][0]!=now:return
            self.last_shadow=now;features=self._observations[-1][2]
            for side,orders,touch in ((1,bids,bid),(-1,asks,ask)):
                oriented=tuple(side*x if i<15 or i==19 else x for i,x in enumerate(features))
                for offset in (0,1):
                    price=touch-side*offset;queued=sum(o.quantity for o in orders if o.price==price)
                    frame=oriented+(side*(mid-price),log(1+queued)/10,float(offset))
                    self.joins.append(dict(stamp=now,ready=now+5000,expiry=now+105000,side=side,price=price,features=frame))
    class Engine(ExchangeSimulator):
        def _process_market_event(self,event):
            self.strategy.before(event,self.book)
            super()._process_market_event(event)
    s=Collector();Engine(s,SimulationConfig(order_accept_delay_ms=5,public_depth=20,
        max_position=100,max_potential_position=1000,position_breach_penalty_per_second=10000)).run(Path('data/round1.csv'))
    data=np.asarray(s.rows).reshape(-1,26)
    np.savez(path,t=data[:,0],y=data[:,1],filled=data[:,2],x=data[:,3:])
    (ROOT/'collection.json').write_text(json.dumps(dict(rows=len(data),filled=s.filled,expired=s.expired,
        limitation='Hypothetical first-fill outcomes on original market-only book; whole-policy inventory and counterfactual post-fill book effects excluded.'),indent=2)+'\n')
    print('COLLECTED SHADOWS',data.shape,'filled',s.filled,flush=True)
    return np.load(path)


def export(model,hurdle):
    text=source_for(40,7,15000)
    for line in ('import numpy as np\n','from sklearn.ensemble import HistGradientBoostingRegressor\n',
                 'from sklearn.utils.parallel import _get_threadpool_controller\n',
                 '        self._tree_rows = deque(maxlen=15000)\n','        self._tree_last_fit = None\n',
                 '        self._trees = []\n','        self._tree_intercept = 0.0\n',
                 '        self._learn(now,mid)\n','        self._fit_trees(now)\n'):
        text=text.replace(line,'')
    start=text.index('    def _learn(');end=text.index('    def _cancel(',start)
    lines=['    def _value(self, frame):','        '+','.join(f'f{i}' for i in range(23))+' = frame',
           f'        value = {float(model._baseline_prediction[0,0])!r}']
    def emit(nodes,index,indent):
        n=nodes[index];space=' '*indent
        if n['is_leaf']:lines.append(space+f"value += {float(n['value'])!r}")
        else:
            lines.append(space+f"if f{int(n['feature_idx'])} <= {float(n['num_threshold'])!r}:")
            emit(nodes,int(n['left']),indent+4);lines.append(space+'else:');emit(nodes,int(n['right']),indent+4)
    for stage in model._predictors:emit(stage[0].nodes,0,8)
    lines+=['        return value','','    def _frame(self, features, sign, price, mid, queued, offset):',
            '        return tuple(sign*x if i<15 or i==19 else x for i,x in enumerate(features))+(sign*(mid-price),log(1+queued)/10,float(offset))','']
    text=text[:start]+'\n'.join(lines)+'\n'+text[end:]
    text=text.replace('''        if self._trees:
            prediction = max(-2.0,min(2.0,1.0*self._predict_trees(features)))
''','')
    text=text.replace('        self._orders = {}','''        self._orders = {}
        self._action_time = None
        self._action_touch = None
        self._action_buy = self._action_sell = None''',1)
    decision=f'''        if self._action_time is None or now-self._action_time>=5000 or self._action_touch!=(bid,ask):
            bback=sum(o.quantity for o in snapshot.bids if o.owner=='market' and o.price==bid-1)
            aback=sum(o.quantity for o in snapshot.asks if o.owner=='market' and o.price==ask+1)
            b0=self._value(self._frame(features,1,bid,mid,bq,0))
            b1=self._value(self._frame(features,1,bid-1,mid,bback,1))
            a0=self._value(self._frame(features,-1,ask,mid,aq,0))
            a1=self._value(self._frame(features,-1,ask+1,mid,aback,1))
            bias=0.01*self.inventory/100
            self._action_buy=None if max(b0,b1)<{hurdle}+bias else bid if b0>=b1 else bid-1
            self._action_sell=None if max(a0,a1)<{hurdle}-bias else ask if a0>=a1 else ask+1
            self._action_time,self._action_touch=now,(bid,ask)
        buy,sell=self._action_buy,self._action_sell
'''
    text=text.replace('        # Withdraw the side',decision+'        # Withdraw the side')
    return text


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'full.json').exists():raise SystemExit('Results already exist')
    data=collect();specs={};search_queue.ROOT=ROOT
    for fraction,iterations,leaves in ((0.6,128,15),(1.0,128,31),(1.0,256,31)):
        mask=data['t']<12000000000*fraction
        model=HistGradientBoostingRegressor(max_iter=iterations,max_leaf_nodes=leaves,min_samples_leaf=200,
            l2_regularization=10,learning_rate=0.08,max_bins=64,early_stopping=False,random_state=1729)
        with _get_threadpool_controller().limit(limits=1):model.fit(data['x'][mask],np.clip(data['y'][mask],-3,3))
        for hurdle in (0.0,0.005):
            name=f'value_{fraction}_{iterations}_{leaves}_{hurdle}'
            path=ROOT/'sources'/(name+'.py');path.write_text(export(model,hurdle))
            assert not check(path),check(path)
            s=load_strategy_from_file(path);test=data['x'][::10000]
            assert np.max(np.abs(np.array([s._value(tuple(row)) for row in test])-model.predict(test)))<1e-10
            specs[name]=dict(training_fraction=fraction,iterations=iterations,leaves=leaves,hurdle=hurdle,
                source_sha256=digest(path),in_sample=fraction==1.0)
        print('FIT SHADOW',fraction,iterations,leaves,flush=True)
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/round1/screening.csv','screening',workers=3)
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:2]
    full=search_queue.batch(finalists,'data/round1.csv','full',workers=2)
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],parameters=specs[winner],
        limitation='Fixed trained action-value model; training overlap recorded in parameters. Virtual first-fill labels approximate whole-policy PnL.'),indent=2)+'\n')
    print('WINNER SHADOW',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
