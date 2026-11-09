"""Bounded causal maker/large-aggressor switching study for the updated 150k goal."""
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
import json
from scripts.benchmark import digest
from scripts.check_submission import check
from scripts.round2_workbench import load_manifest,run_candidate,write_json

ROOT=Path('logs/round2_regime_composite')


def build():
    base=Path('research/round2_adaptation_20261107/sources/calibrate_fast_escape.py').read_text()
    init='''        self.inventory = 0
        self._m2_big=0
        self._m2_shadow_pos=0
        self._m2_shadow_cash=0.0
        self._m2_history=deque()
        self._m2_last_sample=None
        self._m2_start=None
        self._m2_pending=None
        self._m2_ids=set()'''
    base=base.replace('        self.inventory = 0',init,1)
    anchor='if event.status in (OrderStatus.FILLED,OrderStatus.PARTIALLY_FILLED) and self._value_us is not None:'
    assert anchor in base
    base=base.replace(anchor,anchor[:-1]+' and event.order_id not in self._m2_ids:',1)
    base=base.replace('        was_hedge = event.order_id == self._hedge_id','''        if event.order_id in self._m2_ids and event.status in (OrderStatus.FILLED,OrderStatus.CANCELED,OrderStatus.REJECTED):
            self._m2_ids.discard(event.order_id)
            if self._m2_pending==event.order_id:
                self._m2_pending=None
        was_hedge = event.order_id == self._hedge_id''',1)
    cases={}
    for seconds in (60,300):
        for threshold in (0,5):
            methods=f'''    def _m2_target(self,now,bid,ask,trades):
        if self._m2_start is None:
            self._m2_start=now
        net=0
        for trade in trades:
            if trade.taker_owner=='market':
                net+=trade.quantity if trade.book_side=='ask' else -trade.quantity
        if net>=500:
            self._m2_big=1
        elif net<=-500:
            self._m2_big=-1
        step=self._m2_big-self._m2_shadow_pos
        if step:
            self._m2_shadow_cash-=step*(ask if step>0 else bid)
            self._m2_shadow_pos=self._m2_big
        score=self._m2_shadow_cash+self._m2_shadow_pos*(bid+ask)*.5
        if self._m2_last_sample is None or now-self._m2_last_sample>=1000000:
            self._m2_history.append((now,score))
            self._m2_last_sample=now
        boundary=now-{seconds*1000000}
        while len(self._m2_history)>1 and self._m2_history[1][0]<=boundary:
            self._m2_history.popleft()
        if now-self._m2_start>={seconds*1000000} and score>10 and score-self._m2_history[0][1]>{threshold}:
            return 100*self._m2_big
        return None

    def _m2_trade(self,now,target,bid,ask):
        for oid,record in list(self._orders.items()):
            if oid not in self._m2_ids:
                self._cancel(oid)
        if self._m2_pending is not None:
            return
        difference=target-self.inventory
        if not difference:
            return
        sign=1 if difference>0 else -1
        reserved=sum(r[2] for r in self._orders.values() if r[0]==sign)
        quantity=min(abs(difference),max(0,100-sign*self.inventory-reserved))
        if quantity<=0:
            return
        price=ask if sign>0 else bid
        oid=self.send_order(OrderRequest(side=Side.BUY if sign>0 else Side.SELL,
            price=price,quantity=quantity,order_type=OrderType.IOC))
        self._orders[oid]=[sign,price,quantity,False,False,now]
        self._m2_pending=oid
        self._m2_ids.add(oid)

'''
            text=base.replace('    def on_order_book_change(self, snapshot, trades):',methods+'    def on_order_book_change(self, snapshot, trades):',1)
            anchor='        self._desired_buy,self._desired_sell,self._desired_time = buy,sell,now'
            assert anchor in text
            text=text.replace(anchor,'''        m2_target=self._m2_target(now,bid,ask,trades)
        if m2_target is not None:
            self._desired_buy=self._desired_sell=None
            self._desired_time=now
            self._m2_trade(now,m2_target,bid,ask)
            return
'''+anchor,1)
            cases[f'mix_{seconds}s_gate{threshold}']=text
    return cases


def main():
    m=load_manifest(Path('logs/round2_local_intake'))
    ROOT.mkdir(exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    candidates=[]
    for name,text in build().items():
        path=ROOT/'sources'/(name+'.py')
        if path.exists():assert path.read_text()==text
        else:path.write_text(text)
        assert not check(path),check(path)
        candidates.append(dict(name=name,file=str(path),source_sha256=digest(path),risk='strict100'))
    protocol=dict(goal=150000,scope='First80% previously consumed development; no fresh holdout remains for public claims.',
        candidates=candidates,data_sha256=m['validation_prefix_sha256'],native=m['native'],
        hypothesis='Choose maker or large-aggressor IOC policy from causal recent one-lot shadow profitability, using one shared 100-lot budget.',
        selection='Require positive 30-60m and 60-80m increments. Prefer larger combined net gain in those windows; freeze one before full replay.',
        safeguards='Retain pending cancellations; exclude IOC fills from maker calibration; shadow is a no-latency proxy, actual trades use native costs.')
    p=ROOT/'protocol.json'
    if p.exists():assert json.loads(p.read_text())==protocol
    else:write_json(p,protocol)
    p=ROOT/'results.json';results=json.loads(p.read_text()) if p.exists() else {}
    with ProcessPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(run_candidate,c,m['validation_prefix'],ROOT/c['name'],
                         (m['first_us']+1800000000,m['development_cutoff_us'],m['validation_cutoff_us'])):c['name']
              for c in candidates if c['name'] not in results}
        for job in as_completed(jobs):
            name=jobs[job];r=job.result();marks=r['boundary_pnl']
            r['later30']=marks[str(m['development_cutoff_us'])]-marks[str(m['first_us']+1800000000)]
            r['last20']=marks[str(m['validation_cutoff_us'])]-marks[str(m['development_cutoff_us'])]
            results[name]=r;write_json(p,results)
            print(name,r['result']['pnl'],'later30',r['later30'],'last20',r['last20'],flush=True)


if __name__=='__main__':main()
