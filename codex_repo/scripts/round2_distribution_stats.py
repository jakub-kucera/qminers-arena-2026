"""Reproducible distribution and conditional-markout analysis of the public tape."""
import csv
import json
from collections import Counter,defaultdict
from pathlib import Path

import numpy as np
from scipy import stats

from scripts.benchmark import digest
from scripts.round2_workbench import write_json

ROOT=Path('logs/round2/distribution_research')
HORIZONS=(5000,25000,100000,400000,1000000,2000000,5000000)


def summary(x,weights=None):
    x=np.asarray(x,dtype=float)
    if len(x)==0:return {'n':0}
    return dict(n=len(x),mean=float(np.average(x,weights=weights)),sd=float(np.std(x)),
        quantiles=dict(zip(('0','.001','.01','.05','.25','.5','.75','.95','.99','.999','1'),
            map(float,np.quantile(x,(0,.001,.01,.05,.25,.5,.75,.95,.99,.999,1))))),
        positive_fraction=float(np.mean(x>0)),negative_fraction=float(np.mean(x<0)),
        excess_kurtosis=float(stats.kurtosis(x)) if np.ptp(x)>0 else None)


def labels(data,times,prices,signs,horizon,end):
    ix=np.searchsorted(data['mid_t'],times+horizon,side='left')-1
    valid=(ix>=0)&(times+horizon<=end)
    return valid,signs*(data['mid'][np.maximum(ix,0)]-prices)


def block_interval(t,y,w,block_us=60000000):
    """Descriptive 60-second block bootstrap; serial dependence can persist longer."""
    blocks=t//block_us
    unique=np.unique(blocks)
    num=np.array([np.sum(y[blocks==b]*w[blocks==b]) for b in unique])
    den=np.array([np.sum(w[blocks==b]) for b in unique])
    if len(num)<2:return None
    rng=np.random.default_rng(713024)
    draw=rng.integers(0,len(num),(1000,len(num)))
    values=np.sum(num[draw],axis=1)/np.maximum(1,np.sum(den[draw],axis=1))
    return list(map(float,np.quantile(values,(.025,.975))))


def raw_statistics(path):
    quantities=defaultdict(list);time=[];insertions={};ages=[];counts=Counter();blocks=Counter()
    for r in csv.DictReader(Path(path).open()):
        t=int(round(float(r['Time'])*1e6));time.append(t)
        key=r['Operation']+'_'+r['Lifespan'];counts[key]+=1;blocks[(t//600000000,key)]+=1
        if r['Operation']=='Insert':
            q=int(r['Volume']);quantities[r['Lifespan']].append(q)
            if r['Lifespan']=='G':insertions[r['OrderId']]=(t,q)
        elif r['OrderId'] in insertions:
            start,q=insertions.pop(r['OrderId']);ages.append(((t-start)/1e6,q))
    ages=np.asarray(ages);qreport={}
    for name,q in quantities.items():
        q=np.asarray(q);logq=np.log(q)
        qreport[name]=dict(summary=summary(q),log_size=summary(logq),
            largest_one_percent_volume_fraction=float(q[q>=np.quantile(q,.99)].sum()/q.sum()),
            quantile_bins={f'{lo}..{hi}':int(np.sum((q>=lo)&(q<hi))) for lo,hi in
                ((1,10),(10,50),(50,200),(200,1000),(1000,1000000))})
    dt=np.diff(time)
    return dict(message_counts=dict(counts),size=qreport,interarrival_us=summary(dt),
        interarrival_cv=float(np.std(dt)/np.mean(dt)),
        cancellation_lifetimes_seconds=summary(ages[:,0]),
        cancellation_by_size={f'{lo}..{hi}':summary(ages[(ages[:,1]>=lo)&(ages[:,1]<hi),0])
            for lo,hi in ((1,50),(50,500),(500,1000000))},
        cancellation_survival={str(age):float(np.mean(ages[:,0]>age)) for age in (.1,.2,.4,.8,1.6,3.2)},
        ten_minute_counts={str(b):{key:n for (bb,key),n in blocks.items() if bb==b} for b in range(10)},
        limitation='Cancellation rows may refer to orders already filled; these are scheduled CSV lifetimes, not actual resting survival.')


def jump_followthrough(data):
    t=data['mid_t'];mid=data['mid'];change=np.diff(mid)
    selected=[];last=-1000000000
    for i in np.flatnonzero(abs(change)>=2)+1:
        if t[i]-last>=100000:selected.append(i);last=t[i]
    ix=np.array(selected,dtype=int)
    spread=data['spread'][np.searchsorted(data['book_t'],t[ix],side='right')-1]
    groups={}
    for name,mask in [('all',np.ones(len(ix),bool)),('spread_le2',spread<=2),
        ('spread_gt2',spread>2),('jump_ge5',abs(change[ix-1])>=5)]:
        rows={}
        for h in (5000,25000,100000,400000,1000000,2000000):
            valid=mask&(t[ix]+h<=data['book_t'][-1]);ind=ix[valid]
            j=np.searchsorted(t,t[ind]+h,side='left')-1
            y=np.sign(change[ind-1])*(mid[j]-mid[ind])
            rows[str(h)]={'n':len(y),'mean_signed_followthrough':float(np.mean(y)),
                'median':float(np.median(y)),'reversal_fraction':float(np.mean(y<0))}
        groups[name]=rows
    return dict(scope='Reused full-public descriptive outcomes; no executable-price/latency profitability claim',
        minimum_initial_jump_ticks=2,minimum_cluster_spacing_us=100000,groups=groups)


def main():
    data=dict(np.load(ROOT/'observations.npz'));meta=json.loads((ROOT/'metadata.json').read_text())
    end=meta['last_event_us'];report=dict(data_sha256=meta['data_sha256'],extractor_metadata=meta,
        scope='Descriptive analysis of previously consumed full PUBLIC data; no organizer validation/private access.')
    report['raw']=raw_statistics(meta['data'])
    duration=np.diff(data['book_t'],append=end)
    report['spread_time_fraction']={str(s):float(duration[data['spread']==s].sum()/duration.sum()) for s in np.unique(data['spread'])}
    report['touch_quantity']=summary(data['touch_quantity'].ravel())
    report['touch_count']=summary(data['touch_count'].ravel())
    report['returns']={};report['blocks']=[]
    for h in (10000,100000,400000,1000000,5000000,25000000):
        grid=np.arange(data['mid_t'][0]+h,end+1,h,dtype=np.int64)
        ix=np.searchsorted(data['mid_t'],grid,side='left')-1
        prices=data['mid'][ix];r=np.diff(prices)
        s=summary(r);s['variance_per_second']=float(np.var(r)/(h/1e6))
        s['lag1_return_correlation']=float(np.corrcoef(r[:-1],r[1:])[0,1])
        s['lag1_absolute_return_correlation']=float(np.corrcoef(abs(r[:-1]),abs(r[1:]))[0,1])
        s['largest_one_percent_squared_return_share']=float(np.sort(r*r)[-max(1,len(r)//100):].sum()/np.sum(r*r))
        report['returns'][str(h)]=s
    grid=np.arange(data['mid_t'][0]+100000,end,100000,dtype=np.int64)
    p=data['mid'][np.searchsorted(data['mid_t'],grid,side='left')-1];r=np.diff(p)
    for b in range(10):
        m=(grid[1:]>=b*600000000)&(grid[1:]<(b+1)*600000000)
        bk=(data['book_t']>=b*600000000)&(data['book_t']<(b+1)*600000000)
        report['blocks'].append(dict(block=b,start_seconds=b*600,return_100ms_sd=float(np.std(r[m])),
            large_return_fraction=float(np.mean(abs(r[m])>=2)),
            spread_gt2_time_fraction=float(duration[bk&(data['spread']>2)].sum()/max(1,duration[bk].sum()))))
    report['fill_markouts']={};t=data['fill_t'];w=np.minimum(data['fill_quantity'],20)
    masks={'all':np.ones(len(t),dtype=bool),'level_exhausted':data['fill_depleted'],
        'level_survives':~data['fill_depleted'],'quantity_le20':data['fill_quantity']<=20,
        'quantity_21_100':(data['fill_quantity']>20)&(data['fill_quantity']<=100),
        'quantity_gt100':data['fill_quantity']>100,
        'first60':t<3599997635,'later40':t>=3599997635}
    for h in HORIZONS:
        valid,y=labels(data,t,data['fill_price'],data['fill_sign'],h,end)
        rows={}
        for key,mask in masks.items():
            m=valid&mask
            rows[key]=dict(summary=summary(y[m]),weight20_mean=float(np.average(y[m],weights=w[m])),
                weight100_mean=float(np.average(y[m],weights=np.minimum(100,data['fill_quantity'][m]))),
                mean_clip3=float(np.average(np.clip(y[m],-3,3),weights=w[m])),
                loss_gt3_fraction=float(np.mean(y[m]<-3)),
                block_bootstrap_95=block_interval(t[m],y[m],w[m]))
        report['fill_markouts'][str(h)]=rows
    report['fill_feature_associations']={}
    valid,y=labels(data,t,data['fill_price'],data['fill_sign'],400000,end)
    for scope,mask in (('first60',t<3599997635),('later40',t>=3599997635)):
        m=mask&valid;yy=np.clip(y[m],-3,3);xx=data['fill_x'][m];rows=[]
        for j,name in enumerate(meta['fill_feature_names']):
            if np.std(xx[:,j])<1e-10:continue
            corr=float(np.corrcoef(xx[:,j],yy)[0,1])
            low,high=np.quantile(xx[:,j],(.2,.8));a=xx[:,j]<=low;b=xx[:,j]>=high
            rows.append(dict(name=name,column=j,correlation=corr,low20_markout=float(np.mean(yy[a])),
                high20_markout=float(np.mean(yy[b])),cutoffs=[float(low),float(high)]))
        report['fill_feature_associations'][scope]=sorted(rows,key=lambda a:-abs(a['correlation']))
    report['limitations']=[
        'Event-weighted quantity and count summaries differ from time-weighted spread summaries.',
        'Fill observations are market-maker fills, not counterfactual user executions; exhausted-level is an offline outcome label, never a runtime feature.',
        'The 60-second block bootstrap is descriptive; longer regime dependence and repeated hypothesis selection invalidate a confirmatory interpretation.',
        'Small visible order sizes can be remnants of larger partially filled orders.',
        'Cancellation lifetimes include later no-op cancellation requests after fills.',
        'No result is an organizer validation or private score.']
    write_json(Path('results/round2_distribution_statistics.json'),report)
    write_json(Path('results/round2_distribution_jump_followthrough.json'),jump_followthrough(data))
    with Path('results/round2_distribution_markouts.csv').open('w',newline='') as f:
        writer=csv.writer(f,lineterminator='\n');writer.writerow(['horizon_ms','group','count','mean','median','sd','weight20_mean','weight100_mean','clipped3_mean','loss_gt3_fraction'])
        for h,groups in report['fill_markouts'].items():
            for name,g in groups.items():
                s=g['summary'];writer.writerow([int(h)/1000,name,s['n'],s['mean'],s['quantiles']['.5'],s['sd'],g['weight20_mean'],g['weight100_mean'],g['mean_clip3'],g['loss_gt3_fraction']])
    print('RETURN STATS',json.dumps(report['returns'],indent=2),flush=True)
    for h in (400000,1000000,2000000):
        print('FILL HORIZON',h,{k:dict(n=v['summary']['n'],mean=round(v['weight20_mean'],4),clip=round(v['mean_clip3'],4)) for k,v in report['fill_markouts'][str(h)].items()},flush=True)
    for scope,rows in report['fill_feature_associations'].items():print('FEATURES',scope,rows[:15],flush=True)


if __name__=='__main__':main()
