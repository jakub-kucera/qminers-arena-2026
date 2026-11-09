"""Public-derived regime stress tapes, never replicas of hidden validation.

Select the three highest1s-volatility1000s public segments and repeat them.
Every seam cancels the previous segment's scheduled-live G IDs, seeds the new
segment's no-trade book, namespaces IDs and translates prices for continuity.
Strategies are not told about seams; scoring reports seam windows separately.
Repeated events, reset books and future-selected high-volatility segments make
these deliberately artificial, reused-data stress tests.
"""
import csv
import json
from pathlib import Path

import numpy as np

from scripts.benchmark import digest
from scripts.round2_workbench import load_manifest,native_stamp,write_json
from simulator.models import MarketOperation,OrderType,Side
from simulator.simulator import ExchangeSimulator,SimulationConfig
from simulator.strategy import BaseStrategy

ROOT=Path('logs/round2/regime_stress')
SPAN=1000000000


class NoTrade(BaseStrategy):
    def __init__(self):super().__init__();self.mid=10000.
    def on_order_book_change(self,snapshot,trades):
        if snapshot.bids and snapshot.asks:
            bid=snapshot.bids[0].price;ask=snapshot.asks[0].price
            if bid<ask:self.mid=(bid+ask)*.5


class CaptureBooks(ExchangeSimulator):
    def __init__(self,strategy,config):
        super().__init__(strategy,config);self.states={};self.scheduled=set();self.next_boundary=0
    def capture(self,t):
        orders=[dict(id=o.order_id,side='B' if o.side==Side.BUY else 'A',quantity=o.remaining_quantity,price=o.price)
            for side in (Side.BUY,Side.SELL) for o in self.book.iter_levels(side) if o.remaining_quantity>0]
        return dict(mid=self.strategy.mid,orders=orders,scheduled_ids=sorted(self.scheduled))
    def _process_market_event(self,event):
        while self.next_boundary<=event.timestamp_us:
            self.states[str(self.next_boundary)]=self.capture(self.next_boundary);self.next_boundary+=SPAN
        if event.operation==MarketOperation.INSERT and event.order_type==OrderType.LIMIT:self.scheduled.add(event.order_id)
        elif event.operation==MarketOperation.CANCEL:self.scheduled.discard(event.order_id)
        super()._process_market_event(event)


def write_time(t):return f'{t//1000000}.{t%1000000:06d}'


def prepare():
    m=load_manifest(Path('logs/round2'));ROOT.mkdir(parents=True,exist_ok=True)
    manifest=ROOT/'manifest.json'
    if manifest.exists():
        saved=json.loads(manifest.read_text());assert saved['data_sha256']==m['data_sha256']
        assert saved['generator_sha256']==digest(__file__)
        for tape in saved['tapes'].values():assert digest(tape['path'])==tape['sha256']
        return saved
    chunks=ROOT/'chunks';chunks.mkdir(exist_ok=True)
    handles=[(chunks/f'{i}.csv').open('w',newline='') for i in range(6)]
    writers=[csv.writer(h,lineterminator='\n') for h in handles]
    with Path(m['data']).open(newline='') as f:
        reader=csv.reader(f);header=next(reader)
        for w in writers:w.writerow(header)
        for row in reader:
            b=min(5,int(round(float(row[0])*1000000))//SPAN);writers[b].writerow(row)
    for h in handles:h.close()
    engine=CaptureBooks(NoTrade(),SimulationConfig(public_depth=20));result=engine.run(Path(m['data']))
    assert result.pnl==0 and result.traded_volume==0
    states=engine.states;states[str(6*SPAN)]=engine.capture(6*SPAN)
    write_json(ROOT/'boundary_books.json',states)
    observed=np.load('logs/round2/distribution_research/observations.npz')
    grid=np.arange(1000000,6*SPAN,1000000,dtype=np.int64)
    px=observed['mid'][np.searchsorted(observed['mid_t'],grid,side='left')-1];returns=np.diff(px)
    volatility=[float(np.std(returns[(grid[1:]>=i*SPAN)&(grid[1:]<(i+1)*SPAN)])) for i in range(6)]
    selected=sorted(np.argsort(volatility)[-3:].tolist())
    out=dict(data_sha256=m['data_sha256'],generator_sha256=digest(__file__),native=native_stamp(),
        volatility_1s_by_1000s_segment=volatility,selected_segments=selected,tapes={},
        limitations=[
            'Public events reused repeatedly; volatility selection uses the entire source segment, not a causal trading signal.',
            'No hidden tape was observed or reconstructed. Matching a few validation metrics cannot identify its distribution.',
            'Seams reset market books, align no-trade midpoint prices within0.5tick and preserve user state; actual policy-dependent midpoints can differ.',
            'Score both full PnL and PnL excluding2seconds before/after each seam. This does not erase state contamination.',
            'Historical donor evidence: M3 stop improved stitched proxies but did not improve actual validation.'])
    for name,speed_num,speed_den,repeats in [('highvol_1x',1,1,4),('highvol_1p25',5,4,5)]:
        sequence=selected*repeats;duration=SPAN*speed_den//speed_num;path=ROOT/(name+'.csv')
        prev_ids=[];last_mid=10000.;seams=[];segments=[]
        with path.open('w',newline='') as f:
            w=csv.writer(f,lineterminator='\n');w.writerow(header)
            for k,seg in enumerate(sequence):
                start=k*duration;source_start=seg*SPAN;state=states[str(source_start)]
                shift=int(round(last_mid-state['mid']));prefix=f's{k}_'
                if k:
                    seams.append(start)
                    for oid in prev_ids:w.writerow([write_time(start-1),'Cancel',oid,'','','',''])
                for order in state['orders']:
                    price=order['price']+shift;assert price>0
                    w.writerow([write_time(start),'Insert',prefix+order['id'],order['side'],order['quantity'],price,'G'])
                with (chunks/f'{seg}.csv').open(newline='') as src:
                    reader=csv.reader(src);next(reader)
                    for row in reader:
                        old=int(round(float(row[0])*1000000));row[0]=write_time(start+(old-source_start)*speed_den//speed_num)
                        row[2]=prefix+row[2]
                        if row[1]=='Insert':row[5]=str(int(row[5])+shift);assert int(row[5])>0
                        w.writerow(row)
                end_state=states[str(source_start+SPAN)]
                prev_ids=[prefix+oid for oid in end_state['scheduled_ids']]
                last_mid=end_state['mid']+shift
                segments.append(dict(source_segment=seg,start_us=start,end_us=start+duration,price_shift=shift))
            w.writerow([write_time(len(sequence)*duration-1),'Cancel','synthetic_end_marker','','','',''])
        tape=dict(path=str(path),sha256=digest(path),duration_seconds=len(sequence)*duration/1000000,
            speed=speed_num/speed_den,segments=segments,seams_us=seams,
            seam_exclusion_boundaries_us=sorted([t+d for t in seams for d in (-2000000,2000000)]))
        out['tapes'][name]=tape
        print('STRESS READY',name,'segments',selected,'duration',tape['duration_seconds'],flush=True)
    write_json(manifest,out);write_json(Path('results/round2_regime_tapes.json'),out)
    return out


if __name__=='__main__':prepare()
