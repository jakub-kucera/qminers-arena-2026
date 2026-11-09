"""Fit symmetric nonlinear flow/book forecasts on first60% public data only.

Full-public replays report the later40% separately. Public outcomes have
already been consumed in other studies: these are model-selection diagnostics,
not fresh validation or organizer private scores. Risk sizing is held fixed.
"""
import json
from concurrent.futures import ProcessPoolExecutor,as_completed
from datetime import datetime,timezone
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.utils.parallel import _get_threadpool_controller

from scripts.benchmark import digest
from scripts.build_round2_candidates import describe
from scripts.check_submission import check
from scripts.round2_jump_models import replace_once
from scripts.round2_workbench import load_manifest,native_stamp,run_candidate,write_json
from simulator.main import load_strategy_from_file
from simulator.simulator import ExchangeSimulator,SimulationConfig

ROOT=Path('logs/round2/pretrained_alpha')
BASE=Path('strategies/round2_research/round2_absolute_variance_112379.py')
BASE_SHA='4080cb3fc553d91a2849b6434e6dc563081b42d710b74c5bbcf2d0c4e1e62cba'


def collect(manifest):
    path=ROOT/'features.npz';meta_path=ROOT/'features.json'
    stamp=dict(data_sha256=manifest['development_sha256'],base_sha256=digest(BASE),native=native_stamp(),
               horizon_us=400000,sample_us=20000,extractor_sha256=digest(__file__))
    if path.exists():
        assert json.loads(meta_path.read_text())==stamp,'Cached training features changed'
        return dict(np.load(path))
    assert digest(BASE)==BASE_SHA
    strategy=load_strategy_from_file(BASE)
    strategy._quote=lambda *args:None
    strategy._hedge=lambda *args:None
    strategy._learn=lambda *args:None
    original=strategy.on_order_book_change
    times=[];features=[];origins=[];mid_times=[];mids=[]
    last_observed=None

    def callback(snapshot,trades):
        nonlocal last_observed
        bid=next((o.price for o in snapshot.bids if o.owner=='market'),None)
        ask=next((o.price for o in snapshot.asks if o.owner=='market'),None)
        if bid is not None and ask is not None and bid<ask:
            mid=(bid+ask)*.5
            if not mids or mids[-1]!=mid:
                mid_times.append(snapshot.timestamp_us);mids.append(mid)
        original(snapshot,trades)
        if strategy._observations and strategy._observations[-1][0]==snapshot.timestamp_us and last_observed!=snapshot.timestamp_us:
            time,mid,frame=strategy._observations[-1]
            times.append(time);origins.append(mid);features.append(frame);last_observed=time

    strategy.on_order_book_change=callback
    config=SimulationConfig(max_position=100,max_potential_position=1000,
        position_breach_penalty_per_second=10000,order_accept_delay_ms=5,public_depth=20)
    engine=ExchangeSimulator(strategy,config);result=engine.run(Path(manifest['development']))
    assert result.pnl==0 and result.traded_volume==0
    times=np.asarray(times,dtype=np.int64);features=np.asarray(features,dtype=float)
    origins=np.asarray(origins,dtype=float);mid_times=np.asarray(mid_times,dtype=np.int64);mids=np.asarray(mids)
    target=times+400000
    indices=np.searchsorted(mid_times,target,side='left')-1
    valid=(target<=engine._last_event_us)&(indices>=0)
    data=dict(t=times[valid],x=features[valid],y=np.clip(mids[indices[valid]]-origins[valid],-1,1))
    assert data['x'].shape[1]==29 and np.isfinite(data['x']).all()
    np.savez_compressed(path,**data);write_json(meta_path,stamp)
    print('COLLECTED',len(data['y']),'public-development training rows; no user orders.',flush=True)
    return data


def export(base,model,mix):
    trees=[]
    for stage in model._predictors:
        assert len(stage)==1
        rows=[]
        for n in stage[0].nodes:
            assert not bool(n['is_categorical'])
            rows.append((int(n['feature_idx']),float(n['num_threshold']),int(n['left']),int(n['right']),
                         float(n['value']),bool(n['is_leaf'])))
        trees.append(tuple(rows))
    intercept=float(model._baseline_prediction[0,0])
    text=replace_once(base,'    FEATURE_COUNT = 29',
        '    TREE_BASE='+repr(intercept)+'\n    TREES='+repr(tuple(trees))+'\n    FEATURE_COUNT = 29')
    text=replace_once(text,'        self._orders = {}','''        self._orders = {}
        self._tree_time=None
        self._tree_last_mid=None
        self._tree_cached=0.0''')
    helper='''    def _predict_fixed_trees(self,features):
        total=self.TREE_BASE
        for tree in self.TREES:
            index=0
            while not tree[index][5]:
                feature,threshold,left,right,_,_=tree[index]
                index=left if features[feature]<=threshold else right
            total+=tree[index][4]
        return total

'''
    text=replace_once(text,'    def _learn(self, now, mid):',helper+'    def _learn(self, now, mid):')
    block=f'''        if self._tree_time is None or now-self._tree_time>=20000 or mid!=self._tree_last_mid:
            self._tree_cached=self._predict_fixed_trees(features)
            self._tree_time=now
            self._tree_last_mid=mid
        prediction=max(-2,min(2,{1-mix}*prediction+{mix}*self._tree_cached))
'''
    text=replace_once(text,'        fair = mid + ',block+'        fair = mid + ')
    if mix==1:
        text=replace_once(text,'        self._learn(now,mid)','        # Fixed nonlinear forecast; no online forecast fitting.')
    return text


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    manifest=load_manifest(Path('logs/round2'));data=collect(manifest)
    x=data['x'];y=data['y'];reflected=x.copy()
    odd=[i for i in range(29) if i!=24]
    reflected[:,odd]*=-1
    xx=np.concatenate((x,reflected));yy=np.concatenate((y,-y))
    candidates=[];fit_specs={}
    for iterations,leaves in ((64,15),(128,15)):
        model=HistGradientBoostingRegressor(max_iter=iterations,max_leaf_nodes=leaves,
            min_samples_leaf=500,l2_regularization=100,learning_rate=.05,max_bins=64,
            early_stopping=False,random_state=57261)
        with _get_threadpool_controller().limit(limits=1):model.fit(xx,yy)
        for mix in (.5,1.0):
            name=f'nonlinear_{iterations}_leaves{leaves}_mix{mix}'
            source=describe(export(BASE.read_text(),model,mix),
                'Public-first60%-pretrained symmetric nonlinear alpha: '+name+
                '. Training performance is in-sample; later-public comparisons are reused model selection. Risk sizing unchanged.')
            path=ROOT/'sources'/(name+'.py')
            if path.exists():assert path.read_text()==source,'Frozen pretrained source changed'
            else:path.write_text(source)
            assert not check(path),check(path)
            s=load_strategy_from_file(path)
            sample=x[::max(1,len(x)//1000)]
            expected=model.predict(sample)
            actual=np.array([s._predict_fixed_trees(row) for row in sample])
            assert np.max(np.abs(actual-expected))<1e-10,'Export differs from fitted model'
            candidates.append(dict(name=name,file=str(path),source_sha256=digest(path),risk='native'))
            fit_specs[name]=dict(iterations=iterations,leaves=leaves,mix=mix,training_rows=len(x),
                training_data_sha256=manifest['development_sha256'],training_overlap_first60=True,
                no_absolute_price_time_or_ids=True,prediction_export_max_error=float(np.max(np.abs(actual-expected))))
        print('FIT',iterations,leaves,'export equality verified.',flush=True)
    write_json(ROOT/'specs.json',dict(created_at_utc=datetime.now(timezone.utc).isoformat(),candidates=candidates,
        fitting=fit_specs,native=native_stamp(),scope='Full PUBLIC sample-tuning replay; first60% used for fitting, later40% already consumed by previous selection/check.'))
    path=ROOT/'results.json'
    report=json.loads(path.read_text()) if path.exists() else dict(results={},native=native_stamp(),
        data_sha256=manifest['data_sha256'],scope='Full-public model selection. First60% fitting overlap; later40% chronologically beyond fitting but globally reused, not fresh or private.')
    assert report['native']==native_stamp() and report['data_sha256']==manifest['data_sha256']
    for c in candidates:
        if c['name'] in report['results']:assert report['results'][c['name']]['source_sha256']==c['source_sha256']
    with ProcessPoolExecutor(max_workers=2) as pool:
        jobs={pool.submit(run_candidate,c,manifest['data'],ROOT/'full'/c['name'],
            (manifest['development_cutoff_us'],manifest['validation_cutoff_us'])):c['name']
            for c in candidates if c['name'] not in report['results']}
        for job in as_completed(jobs):
            name=jobs[job];r=job.result()
            r['training_prefix_pnl']=r['boundary_pnl'][str(manifest['development_cutoff_us'])]
            r['post_fit_last40_pnl']=r['result']['pnl']-r['training_prefix_pnl']
            r['fit_specification']=fit_specs[name]
            report['results'][name]=r;write_json(path,report)
            print(name,'PUBLIC NET',r['result']['pnl'],'FIT PREFIX',r['training_prefix_pnl'],
                  'LATER40',r['post_fit_last40_pnl'],flush=True)


if __name__=='__main__':main()
