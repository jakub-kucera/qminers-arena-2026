"""Causal fill-value calibration and inventory escape; only consumed first 80%."""
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
import json
from scripts.benchmark import digest
from scripts.check_submission import check
from scripts.round2_workbench import load_manifest,run_candidate,write_json

ROOT=Path('logs/round2_adaptation')


def calibrate(base,rate):
    text=base.replace('        self.inventory = 0','''        self.inventory = 0
        self._cal_error=0.0
        self._cal_time=None
        self._cal_labels=deque(maxlen=4096)''',1)
    text=text.replace('        self._learn(now,mid)',f'''        if self._cal_time is not None:
            self._cal_error*=exp(-max(0,now-self._cal_time)/300000000)
        self._cal_time=now
        while self._cal_labels and self._cal_labels[0][0]+400000<=now:
            observed,sign,price,predicted,quantity=self._cal_labels.popleft()
            if now-observed<=1400000:
                realized=max(-3,min(3,sign*(mid-price)))
                alpha={rate}*min(1.0,quantity/100)
                self._cal_error+=alpha*(realized-predicted-self._cal_error)
                self._cal_error=max(-0.5,min(0.5,self._cal_error))
        self._learn(now,mid)''',1)
    text=text.replace('        if event.status == OrderStatus.ACCEPTED:',
        '''        if event.status in (OrderStatus.FILLED,OrderStatus.PARTIALLY_FILLED) and self._value_us is not None:
            if 0<=event.timestamp_us-self._value_us<=100000:
                predicted=self._bid_value if record[0]>0 else self._ask_value
                self._cal_labels.append((event.timestamp_us,record[0],event.fill_price,predicted,event.filled_quantity))
        if event.status == OrderStatus.ACCEPTED:''',1)
    text=text.replace('self._bid_value < 0.1','self._bid_value+self._cal_error < 0.1')
    text=text.replace('self._ask_value < 0.1','self._ask_value+self._cal_error < 0.1')
    return text


def escape(base):
    text=base.replace('        self.inventory = 0','''        self.inventory = 0
        self._entry_buy_allowed=False
        self._entry_sell_allowed=False''',1)
    offset='+self._cal_error' if 'self._cal_error' in text else ''
    for side,sign in [('buy',1),('sell',-1)]:
        value='_bid_value' if sign>0 else '_ask_value'
        anchor=f'        if self.{value}{offset} < 0.1:\n            {side}=None'
        assert anchor in text
        text=text.replace(anchor,f'''        self._entry_{side}_allowed=self.{value}{offset}>=0.1
        if not self._entry_{side}_allowed and {sign}*self.inventory>=0:
            {side}=None''',1)
    anchor='        quantity=min(self.QUOTE_SIZE,100-sign*self.inventory-effective,'
    assert anchor in text
    text=text.replace(anchor,'''        allowed=self._entry_buy_allowed if sign>0 else self._entry_sell_allowed
        budget=100-sign*self.inventory if allowed else max(0,-sign*self.inventory)
        quantity=min(self.QUOTE_SIZE,budget-effective,''',1)
    return text


def trend_escape(base):
    text=base.replace('        self.inventory = 0','''        self.inventory = 0
        self._risk_fast=self._risk_slow=None
        self._risk_time=None
        self._risk_direction=0''',1)
    text=text.replace('        self._learn(now,mid)','''        if self._risk_time is None or now-self._risk_time>10000000:
            self._risk_fast=self._risk_slow=mid
        else:
            dt=max(0,now-self._risk_time)
            self._risk_fast+=(1-exp(-dt/1000000))*(mid-self._risk_fast)
            self._risk_slow+=(1-exp(-dt/10000000))*(mid-self._risk_slow)
        self._risk_time=now
        drift=self._risk_fast-self._risk_slow
        self._risk_direction=1 if drift>2 else -1 if drift< -2 else 0
        self._learn(now,mid)''',1)
    marker='        self._cached_bid,self._cached_ask,self._cached_time'
    block='''        if self._risk_direction < 0:
            buy=None
            if self.inventory>0 and spread<=2:
                sell=bid
        elif self._risk_direction > 0:
            sell=None
            if self.inventory<0 and spread<=2:
                buy=ask
'''
    text=text.replace(marker,block+marker,1)
    text=text.replace('        quantity=min(self.QUOTE_SIZE,100-sign*self.inventory-effective,',
        '''        reducing=(sign>0 and self._cached_ask is not None and price>=self._cached_ask) or (sign<0 and self._cached_bid is not None and price<=self._cached_bid)
        budget=max(0,-sign*self.inventory) if reducing else 100-sign*self.inventory
        quantity=min(self.QUOTE_SIZE,budget-effective,''',1)
    return text


def build():
    base=Path('research/round2_conditional_fill_20261107/sources/fill_value_0p1.py').read_text()
    fast=calibrate(base,.03)
    return dict(calibrate_slow=calibrate(base,.005),calibrate_fast=fast,
                passive_escape=escape(base),calibrate_fast_escape=escape(fast),
                trend_escape=trend_escape(base),calibrate_fast_trend=trend_escape(fast))


def main():
    intake=load_manifest(Path('logs/round2_local_intake'))
    ROOT.mkdir(exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    candidates=[]
    for name,text in build().items():
        path=ROOT/'sources'/(name+'.py')
        if path.exists():assert path.read_text()==text
        else:path.write_text(text)
        assert not check(path),check(path)
        candidates.append(dict(name=name,file=str(path),source_sha256=digest(path),risk='strict100'))
    protocol=dict(scope='First 80% is now consumed development. Final20% remains reserved.',
                  candidates=candidates,data_sha256=intake['validation_prefix_sha256'],native=intake['native'],
                  hypotheses=['Bounded causal 400ms fill-error calibration with slow decay to avoid permanent shutdown',
                              'Permit passive reduction when the gate blocks new exposure',
                              'Fast drift risk control may flatten countertrend positions, paying native costs'],
                  selection='Require positive 30-60m and 60-80m increments, then prefer highest minimum per-minute gain across those windows. No final20% tuning.')
    p=ROOT/'protocol.json'
    if p.exists():assert json.loads(p.read_text())==protocol
    else:write_json(p,protocol)
    p=ROOT/'results.json';results=json.loads(p.read_text()) if p.exists() else {}
    for c in candidates:
        if c['name'] in results:
            assert results[c['name']]['source_sha256']==c['source_sha256']
            assert results[c['name']]['data_sha256']==protocol['data_sha256']
    with ProcessPoolExecutor(max_workers=6) as pool:
        jobs={pool.submit(run_candidate,c,intake['validation_prefix'],ROOT/c['name'],
                         (intake['first_us']+1800000000,intake['development_cutoff_us'],intake['validation_cutoff_us'])):c['name']
              for c in candidates if c['name'] not in results}
        for job in as_completed(jobs):
            name=jobs[job];r=job.result()
            marks=r['boundary_pnl'];r['later30']=marks[str(intake['development_cutoff_us'])]-marks[str(intake['first_us']+1800000000)]
            r['last20']=marks[str(intake['validation_cutoff_us'])]-marks[str(intake['development_cutoff_us'])]
            results[name]=r;write_json(p,results)
            print(name,'total',r['result']['pnl'],'later30',r['later30'],'last20',r['last20'],flush=True)


if __name__=='__main__':main()
