"""Fit latency-aligned conditional maker-fill value, with risk sizing fixed.

Only public first60% trade outcomes fit the model. Every feature frame precedes
the fill by at least5ms; proposed prices must exist in that historical book.
Later public data is beyond fitting but globally consumed, never fresh/private.
"""
import json
from collections import deque
from concurrent.futures import ProcessPoolExecutor,as_completed
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.utils.parallel import _get_threadpool_controller

from scripts.benchmark import digest
from scripts.build_round2_candidates import describe
from scripts.check_submission import check
from scripts.round2_jump_models import replace_once
from scripts.round2_pretrained_alpha import BASE,BASE_SHA,export
from scripts.round2_workbench import load_manifest,native_stamp,run_candidate,write_json
from simulator.main import load_strategy_from_file
from simulator.simulator import ExchangeSimulator,SimulationConfig

ROOT=Path('logs/round2/pretrained_fill_value')
INDICES=(0,2,3,8,9,10,11,15,16,17,18,19,20,21,22,28)


def frame_for(sign,edge,features):
    return (1.0,min(3,edge))+tuple(sign*features[i] for i in INDICES)


def collect(manifest):
    path=ROOT/'features.npz';meta_path=ROOT/'features.json'
    stamp=dict(data_sha256=manifest['development_sha256'],base_sha256=digest(BASE),
        native=native_stamp(),latency_us=5000,horizon_us=400000,extractor_sha256=digest(__file__))
    if path.exists():
        assert json.loads(meta_path.read_text())==stamp
        return dict(np.load(path))
    assert digest(BASE)==BASE_SHA
    text=replace_once(BASE.read_text(),'OBSERVATION_INTERVAL_US = 20000','OBSERVATION_INTERVAL_US = 0')
    path_source=ROOT/'collector_source.py';path_source.write_text(text)
    s=load_strategy_from_file(path_source)
    s._quote=lambda *args:None;s._hedge=lambda *args:None;s._learn=lambda *args:None
    original=s.on_order_book_change
    history=deque();times=[];prices=[];signs=[];features=[];weights=[];mid_times=[];mids=[]

    def callback(snapshot,trades):
        now=snapshot.timestamp_us
        while len(history)>1 and history[1][0]<=now-5000:history.popleft()
        if history and history[0][0]<=now-5000 and now-history[0][0]<=100000:
            _,bid,ask,previous,bprices,aprices=history[0]
            groups={}
            for trade in trades:
                if trade.taker_owner!='market' or trade.maker_owner!='market':continue
                sign=1 if trade.book_side=='bid' else -1
                touch=bid if sign>0 else ask
                if trade.price not in (bprices if sign>0 else aprices) or abs(trade.price-touch)>2:continue
                key=(trade.taker_order_id,sign,trade.price)
                groups[key]=groups.get(key,0)+trade.quantity
            for (_,sign,price),quantity in groups.items():
                edge=sign*((bid+ask)*.5-price)
                times.append(now);prices.append(price);signs.append(sign)
                features.append(frame_for(sign,edge,previous));weights.append(min(20,quantity))
        bid=next((o.price for o in snapshot.bids if o.owner=='market'),None)
        ask=next((o.price for o in snapshot.asks if o.owner=='market'),None)
        valid=bid is not None and ask is not None and bid<ask
        if valid:
            mid=(bid+ask)*.5
            if not mids or mids[-1]!=mid:mid_times.append(now);mids.append(mid)
        original(snapshot,trades)
        if valid and s._observations and s._observations[-1][0]==now:
            history.append((now,bid,ask,s._observations[-1][2],
                {o.price for o in snapshot.bids if o.owner=='market'},
                {o.price for o in snapshot.asks if o.owner=='market'}))

    s.on_order_book_change=callback
    engine=ExchangeSimulator(s,SimulationConfig(max_position=100,max_potential_position=1000,
        position_breach_penalty_per_second=10000,order_accept_delay_ms=5,public_depth=20))
    result=engine.run(Path(manifest['development']));assert result.pnl==0 and result.traded_volume==0
    times=np.asarray(times,dtype=np.int64);prices=np.asarray(prices);signs=np.asarray(signs)
    x=np.asarray(features);weight=np.asarray(weights)
    indices=np.searchsorted(mid_times,times+400000,side='left')-1
    valid=(times+400000<=engine._last_event_us)&(indices>=0)
    y=np.clip(signs[valid]*(np.asarray(mids)[indices[valid]]-prices[valid]),-3,3)
    data=dict(t=times[valid],x=x[valid],y=y,w=weight[valid])
    assert data['x'].shape[1]==18 and np.isfinite(data['x']).all()
    np.savez_compressed(path,**data);write_json(meta_path,stamp)
    print('COLLECTED',len(y),'latency-aligned public-fill labels; no user trades.',flush=True)
    return data


def fill_value_source(base,model,threshold):
    text=export(base,model,.5)
    start=text.index('        if self._tree_time is None or now-self._tree_time>=20000 or mid!=self._tree_last_mid:')
    end=text.index('        fair = mid + ',start)
    text=text[:start]+text[end:]
    text=replace_once(text,'        self._orders = {}','''        self._orders = {}
        self._toxic_buy=self._toxic_sell=False
        self._fill_buyprice=self._fill_sellprice=None''')
    helper='''    def _fill_value_frame(self,sign,price,mid,features):
        indices=(0,2,3,8,9,10,11,15,16,17,18,19,20,21,22,28)
        return (1.0,min(3,sign*(mid-price)))+tuple(sign*features[i] for i in indices)

'''
    text=replace_once(text,'    def _learn(self, now, mid):',helper+'    def _learn(self, now, mid):')
    text=replace_once(text,'        budget=max(0,limit-sign*self.inventory)',
        '''        budget=max(0,limit-sign*self.inventory)
        if (sign>0 and self._toxic_buy) or (sign<0 and self._toxic_sell):
            budget=min(budget,max(0,-sign*self.inventory))''')
    decision=f'''        if (self._tree_time is None or now-self._tree_time>=20000 or mid!=self._tree_last_mid
                or buy!=self._fill_buyprice or sell!=self._fill_sellprice):
            self._toxic_buy=(buy is not None and
                self._predict_fixed_trees(self._fill_value_frame(1,buy,mid,features))<{threshold})
            self._toxic_sell=(sell is not None and
                self._predict_fixed_trees(self._fill_value_frame(-1,sell,mid,features))<{threshold})
            self._tree_time=now;self._tree_last_mid=mid
            self._fill_buyprice,self._fill_sellprice=buy,sell
'''
    return replace_once(text,'        # Withdraw the side',decision+'        # Withdraw the side')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    m=load_manifest(Path('logs/round2'));data=collect(m)
    model=HistGradientBoostingRegressor(max_iter=64,max_leaf_nodes=15,min_samples_leaf=300,
        l2_regularization=100,learning_rate=.05,max_bins=64,early_stopping=False,random_state=44890)
    with _get_threadpool_controller().limit(limits=1):
        model.fit(data['x'],data['y'],sample_weight=data['w'])
        sample=data['x'][::max(1,len(data['y'])//1000)];expected=model.predict(sample)
    candidates=[]
    for threshold in (-.1,0.0):
        name=f'latency_fill_value_threshold{threshold}'
        source=describe(fill_value_source(BASE.read_text(),model,threshold),
            'Public-first60%-pretrained latency-aligned conditional maker-fill value: '+name+
            '. In-sample fitting prefix; reused later-public selection; risk sizing unchanged.')
        p=ROOT/'sources'/(name+'.py')
        if p.exists():assert p.read_text()==source
        else:p.write_text(source)
        assert not check(p),check(p)
        s=load_strategy_from_file(p)
        actual=np.array([s._predict_fixed_trees(r) for r in sample])
        assert np.max(np.abs(actual-expected))<1e-10
        candidates.append(dict(name=name,file=str(p),source_sha256=digest(p),risk='native'))
    write_json(ROOT/'specs.json',dict(candidates=candidates,training_data_sha256=m['development_sha256'],
        training_rows=len(data['y']),training_overlap_first60=True,features_latency_us=5000,
        future_markout_us=400000,native=native_stamp()))
    path=ROOT/'results.json'
    report=json.loads(path.read_text()) if path.exists() else dict(results={},native=native_stamp(),
        data_sha256=m['data_sha256'],scope='Full-public sample tuning. Fit only first60% latency-aligned public fills; later40% beyond fit but globally reused. No server/private score.')
    assert report['native']==native_stamp() and report['data_sha256']==m['data_sha256']
    for c in candidates:
        if c['name'] in report['results']:assert report['results'][c['name']]['source_sha256']==c['source_sha256']
    with ProcessPoolExecutor(max_workers=2) as pool:
        jobs={pool.submit(run_candidate,c,m['data'],ROOT/'full'/c['name'],
            (m['development_cutoff_us'],m['validation_cutoff_us'])):c['name']
            for c in candidates if c['name'] not in report['results']}
        for job in as_completed(jobs):
            name=jobs[job];r=job.result()
            r['training_prefix_pnl']=r['boundary_pnl'][str(m['development_cutoff_us'])]
            r['post_fit_last40_pnl']=r['result']['pnl']-r['training_prefix_pnl']
            report['results'][name]=r;write_json(path,report)
            print(name,'PUBLIC NET',r['result']['pnl'],'FIT PREFIX',r['training_prefix_pnl'],
                  'LATER40',r['post_fit_last40_pnl'],flush=True)


if __name__=='__main__':main()
