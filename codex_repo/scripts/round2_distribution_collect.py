"""Collect full PUBLIC distributions without trading; preserve raw multi-horizon labels.

All feature frames use public callbacks only. A fill's selected frame is at
least 5 ms old. Targets are joined offline and never passed to a strategy.
The full public sample is already consumed globally. Fits must explicitly
restrict their time range; seeing this file is not fresh validation.
"""
import argparse
from collections import deque
from pathlib import Path

import numpy as np

from scripts.benchmark import digest
from scripts.round2_distribution_features import augment,ODD_NAMES,EVEN_NAMES
from scripts.round2_pretrained_alpha import BASE,BASE_SHA
from scripts.round2_pretrained_fill_value import frame_for
from scripts.round2_jump_models import replace_once
from scripts.round2_workbench import native_stamp,write_json
from simulator.main import load_strategy_from_file
from simulator.simulator import ExchangeSimulator,SimulationConfig


def collect(path,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    assert not (output/'observations.npz').exists(),'Immutable extraction exists'
    assert digest(BASE)==BASE_SHA
    source=augment(BASE.read_text())
    source=replace_once(source,'OBSERVATION_INTERVAL_US = 20000','OBSERVATION_INTERVAL_US = 0')
    sp=output/'collector_source.py';sp.write_text(source)
    s=load_strategy_from_file(sp)
    s._quote=lambda *args:None;s._hedge=lambda *args:None;s._learn=lambda *args:None
    original=s.on_order_book_change
    history=deque();ft=[];fp=[];fs=[];fq=[];fx=[];frame_t=[];depleted=[];ahead=[];remaining=[]
    st=[];sm=[];sx=[];mt=[];mm=[];bt=[];bs=[];bq=[];bc=[];last_sample=-20000;last_progress=0

    def callback(snapshot,trades):
        nonlocal last_sample,last_progress
        now=snapshot.timestamp_us
        bid=next((o.price for o in snapshot.bids if o.owner=='market'),None)
        ask=next((o.price for o in snapshot.asks if o.owner=='market'),None)
        valid=bid is not None and ask is not None and bid<ask
        while len(history)>1 and history[1][0]<=now-5000:
            history.popleft()
        if history and history[0][0]<=now-5000 and now-history[0][0]<=100000:
            oldt,oldbid,oldask,f,extra,levels=history[0]
            groups={}
            for trade in trades:
                if trade.taker_owner!='market' or trade.maker_owner!='market':continue
                sign=1 if trade.book_side=='bid' else -1
                side=0 if sign==1 else 1
                touch=oldbid if side==0 else oldask
                if trade.price not in levels[side] or abs(trade.price-touch)>2:continue
                key=(trade.taker_order_id,sign,trade.price)
                groups[key]=groups.get(key,0)+trade.quantity
            for (_,sign,price),quantity in groups.items():
                side=0 if sign==1 else 1
                orders=snapshot.bids if side==0 else snapshot.asks
                rem=sum(o.quantity for o in orders if o.owner=='market' and o.price==price)
                edge=sign*((oldbid+oldask)*.5-price)
                vector=frame_for(sign,edge,f)+tuple(sign*v for v in extra[0])+extra[1]
                ft.append(now);fp.append(price);fs.append(sign);fq.append(quantity);fx.append(vector)
                frame_t.append(oldt);depleted.append(rem==0);ahead.append(levels[side][price]);remaining.append(rem)
        original(snapshot,trades)
        if valid:
            mid=(bid+ask)*.5
            if not mm or mm[-1]!=mid:mt.append(now);mm.append(mid)
            levels=[];counts=[]
            for orders in (snapshot.bids,snapshot.asks):
                d={};n={}
                for o in orders:
                    if o.owner=='market':d[o.price]=d.get(o.price,0)+o.quantity;n[o.price]=n.get(o.price,0)+1
                levels.append(d);counts.append(n)
            bt.append(now);bs.append(ask-bid);bq.append((levels[0][bid],levels[1][ask]));bc.append((counts[0][bid],counts[1][ask]))
            if s._observations and s._observations[-1][0]==now:
                f=s._observations[-1][2];extra=s._distribution_frame
                history.append((now,bid,ask,f,extra,levels))
                if now-last_sample>=20000:
                    st.append(now);sm.append(mid);sx.append(f+extra[0]+extra[1]);last_sample=now
        else:
            bt.append(now);bs.append(-1);bq.append((0,0));bc.append((0,0))
        if now-last_progress>=600000000:
            last_progress=now
            print('COLLECT',round(now/1e6),'seconds',len(ft),'fills',len(st),'frames',flush=True)

    s.on_order_book_change=callback
    config=SimulationConfig(max_position=100,max_potential_position=1000,
        position_breach_penalty_per_second=10000,order_accept_delay_ms=5,public_depth=20)
    engine=ExchangeSimulator(s,config);result=engine.run(Path(path))
    assert result.pnl==0 and result.traded_volume==0
    arrays=dict(fill_t=np.asarray(ft,dtype=np.int64),fill_frame_t=np.asarray(frame_t,dtype=np.int64),
        fill_price=np.asarray(fp),fill_sign=np.asarray(fs),fill_quantity=np.asarray(fq),fill_x=np.asarray(fx),
        fill_depleted=np.asarray(depleted),fill_ahead=np.asarray(ahead),fill_remaining=np.asarray(remaining),
        sample_t=np.asarray(st,dtype=np.int64),sample_mid=np.asarray(sm),sample_x=np.asarray(sx),
        mid_t=np.asarray(mt,dtype=np.int64),mid=np.asarray(mm),book_t=np.asarray(bt,dtype=np.int64),
        spread=np.asarray(bs,dtype=np.int16),touch_quantity=np.asarray(bq),touch_count=np.asarray(bc))
    assert np.all(arrays['fill_t']-arrays['fill_frame_t']>=5000)
    assert np.isfinite(arrays['fill_x']).all() and arrays['fill_x'].shape[1]==18+len(ODD_NAMES)+len(EVEN_NAMES)
    np.savez_compressed(output/'observations.npz',**arrays)
    stamp=dict(data=str(path),data_sha256=digest(path),base_sha256=digest(BASE),
        collector_sha256=digest(__file__),features_sha256=digest('scripts/round2_distribution_features.py'),
        source_sha256=digest(sp),native=native_stamp(),last_event_us=engine._last_event_us,
        sample_interval_us=20000,minimum_fill_feature_age_us=5000,
        fill_feature_names=['constant','entry_edge']+[f'base_{i}_signed' for i in (0,2,3,8,9,10,11,15,16,17,18,19,20,21,22,28)]+ODD_NAMES+EVEN_NAMES,
        scope='Previously consumed full public data. Statistical exploration; restrict model fit by time explicitly.')
    write_json(output/'metadata.json',stamp)
    print('SAVED',len(ft),'fills',len(st),'frames',flush=True)
    return arrays


def main():
    p=argparse.ArgumentParser();p.add_argument('--data',type=Path,default=Path('data/round2_public.csv'))
    p.add_argument('--output',type=Path,default=Path('logs/round2/distribution_research'))
    a=p.parse_args();collect(a.data,a.output)


if __name__=='__main__':main()
