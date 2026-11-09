"""Measure selection bias using actual fills of the frozen162K policy.

The probe adds read-only public feature capture to that exact policy. Its
learning interval, trading decisions and risk sizing are not changed. All
offline fitting is restricted to first60% public data. Own fills are selected
by the incumbent policy; a mixed model retains broader public-fill support.
"""
import json
from collections import deque
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.utils.parallel import _get_threadpool_controller

from scripts.benchmark import digest
from scripts.build_round2_candidates import describe
from scripts.check_submission import check
from scripts.round2_distribution_features import augment
from scripts.round2_distribution_models import export_fill
from scripts.round2_distribution_stats import labels,summary
from scripts.round2_full_public_study import run_public_study
from scripts.round2_jump_models import replace_once
from scripts.round2_pretrained_fill_value import frame_for
from scripts.round2_workbench import load_manifest,native_stamp,write_json
from simulator.main import load_strategy_from_file
from simulator.models import OrderStatus
from simulator.simulator import ExchangeSimulator,SimulationConfig

ROOT=Path('logs/round2/distribution_research/ownfills')
REFERENCE=Path('strategies/round2_fill_value_162253.py')
REFERENCE_SHA='1e06031145b06a67bd0b661c27af3d338b46b19b2514d29f1c9cd06046da3c49'


def collect():
    ROOT.mkdir(exist_ok=True);m=load_manifest(Path('logs/round2'));p=ROOT/'observations.npz'
    assert digest(REFERENCE)==REFERENCE_SHA
    if p.exists():return dict(np.load(p))
    text=augment(REFERENCE.read_text())
    text=replace_once(text,'        self._learn(now,mid)',
        '        self._research_features=features\n        self._learn(now,mid)')
    source=ROOT/'collector_source.py';source.write_text(text)
    s=load_strategy_from_file(source);public=s.on_order_book_change;private=s.on_private_order_update
    history=deque();records=[];mid_t=[];mids=[]

    def on_public(snapshot,trades):
        public(snapshot,trades)
        now=snapshot.timestamp_us
        bid=next((o.price for o in snapshot.bids if o.owner=='market'),None)
        ask=next((o.price for o in snapshot.asks if o.owner=='market'),None)
        if bid is not None and ask is not None and bid<ask:
            mid=(bid+ask)*.5
            if not mids or mids[-1]!=mid:mid_t.append(now);mids.append(mid)
            history.append((now,mid,s._research_features,s._distribution_frame))
        while len(history)>1 and history[1][0]<=now-100000:history.popleft()

    def on_private(event):
        now=event.timestamp_us
        if (event.status in (OrderStatus.FILLED,OrderStatus.PARTIALLY_FILLED)
                and event.order_id!=s._hedge_id and event.order_id in s._orders):
            old=next((r for r in reversed(history) if r[0]<=now-5000),None)
            if old is not None and now-old[0]<=100000:
                _,mid,f,extra=old;sign=s._orders[event.order_id][0]
                x=frame_for(sign,sign*(mid-event.fill_price),f)+tuple(sign*v for v in extra[0])+extra[1]
                if records and records[-1][:3]==(now,event.fill_price,sign):
                    r=records[-1];records[-1]=(r[0],r[1],r[2],r[3]+event.filled_quantity,r[4],r[5])
                else:records.append((now,event.fill_price,sign,event.filled_quantity,x,old[0]))
        private(event)

    s.on_order_book_change=on_public;s.on_private_order_update=on_private
    e=ExchangeSimulator(s,SimulationConfig(max_position=100,max_potential_position=1000,
        position_breach_penalty_per_second=10000,order_accept_delay_ms=5,public_depth=20))
    result=e.run(Path(m['development']))
    data=dict(t=np.array([r[0] for r in records]),price=np.array([r[1] for r in records]),
        sign=np.array([r[2] for r in records]),q=np.array([r[3] for r in records]),
        x=np.array([r[4] for r in records]),frame_t=np.array([r[5] for r in records]),
        mid_t=np.asarray(mid_t),mid=np.asarray(mids),end=np.array(e._last_event_us))
    np.savez_compressed(p,**data)
    write_json(ROOT/'metadata.json',dict(reference_source=str(REFERENCE),reference_sha256=REFERENCE_SHA,
        data_sha256=m['development_sha256'],native=native_stamp(),collector_sha256=digest(__file__),
        features_sha256=digest('scripts/round2_distribution_features.py'),observations=len(records),
        result=result.model_dump(mode='json'),scope='Actual incumbent-policy fills on first60% public; no later outcomes collected. Policy selection bias remains.'))
    print('OWN FILLS',len(records),'NET',result.pnl,flush=True)
    return data


def main():
    own=collect();public=dict(np.load('logs/round2/distribution_research/observations.npz'))
    m=load_manifest(Path('logs/round2'));cut=m['development_cutoff_us'];h=400000
    valid,y=labels(own,own['t'],own['price'],own['sign'],h,int(own['end']))
    pv,py=labels(public,public['fill_t'],public['fill_price'],public['fill_sign'],h,cut)
    report={};cases={};(ROOT/'models').mkdir(exist_ok=True)
    for mode in ('own','mixed'):
        x=own['x'][valid];target=y[valid];w=np.minimum(100,own['q'][valid]).astype(float)
        if mode=='mixed':
            x=np.concatenate((x,public['fill_x'][pv]));target=np.concatenate((target,py[pv]))
            w=np.concatenate((w*5,np.minimum(100,public['fill_quantity'][pv])))
        model=HistGradientBoostingRegressor(max_iter=64,max_leaf_nodes=15,min_samples_leaf=100 if mode=='own' else 300,
            l2_regularization=100,learning_rate=.05,max_bins=64,early_stopping=False,random_state=44890)
        with _get_threadpool_controller().limit(limits=1):
            model.fit(x,np.clip(target,-5,5),sample_weight=w)
            expected=model.predict(x[::max(1,len(x)//500)])
        name='distribution_'+mode+'_fills';source=describe(export_fill(model,True),
            'Round2 '+mode+' actual/incumbent-policy fill model. First60% public fitting overlap; native risk rules unchanged.')
        path=ROOT/'models'/(name+'.py');path.write_text(source);assert not check(path),check(path)
        s=load_strategy_from_file(path)
        actual=np.array([s._predict_fixed_trees(r) for r in x[::max(1,len(x)//500)]])
        assert np.max(abs(actual-expected))<1e-10
        cases[name]=source;report[name]=dict(training_rows=len(x),actual_fills=int(valid.sum()),
            source_sha256=digest(path),horizon_us=h,clip=5,weight_cap=100,actual_policy_weight=5 if mode=='mixed' else 1,
            actual_fill_markout=summary(y[valid],weights=np.minimum(100,own['q'][valid])))
    write_json(ROOT/'fit_specs.json',report)
    run_public_study(cases,ROOT/'replays',workers=2)


if __name__=='__main__':main()
