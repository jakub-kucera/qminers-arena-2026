"""Causal robust-label and jump-aware maker experiments on public development only."""
import argparse
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from scripts.benchmark import digest
from scripts.build_round2_candidates import describe
from scripts.check_submission import check
from scripts.round2_workbench import load_manifest, run_candidate, write_json, native_stamp


def replace_once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new, 1)


def build_candidates(base):
    response = 'max(-20.0, min(20.0, mid - old_mid))'
    cap1 = replace_once(base, response, 'max(-1.0, min(1.0, mid - old_mid))')
    cap2 = replace_once(base, response, 'max(-2.0, min(2.0, mid - old_mid))')
    cases = {'robust_label1': cap1, 'robust_label2': cap2}
    clean = replace_once(base, '        self._learn(now,mid)',
        '''        if spread<=2:
            self._learn(now,mid)
        else:
            while self._observations and self._observations[0][0]+self.HORIZON_US<=now:
                self._observations.popleft()''')
    clean = replace_once(clean, 'if now-self._last_observation_us >= self.OBSERVATION_INTERVAL_US:',
                         'if spread<=2 and now-self._last_observation_us >= self.OBSERVATION_INTERVAL_US:')
    cases['clean_endpoints'] = clean
    cases['clean_endpoints_cap1'] = replace_once(clean, response, 'max(-1.0, min(1.0, mid - old_mid))')
    short = replace_once(cap1, 'HORIZON_US = 400000', 'HORIZON_US = 100000')
    cases['short_robust100ms'] = short
    clipped = replace_once(cap2, 'ofi,spread*imbalance,', 'ofi,min(2,spread)*imbalance,')
    clipped = replace_once(clipped, 'depth_imbalance,depth_mid,',
                           'depth_imbalance,max(-2,min(2,depth_mid)),')
    cases['robust_features'] = clipped
    guard = replace_once(cap1, '        self._orders = {}',
                         '        self._orders = {}\n        self._last_mid=None\n        self._pause_until=0')
    guard = replace_once(guard, '        # Withdraw the side', '''        if self._last_mid is not None and abs(mid-self._last_mid)>=2:
            self._pause_until=now+100000
        self._last_mid=mid
        if spread>2 or now<self._pause_until:
            buy=sell=None
        # Withdraw the side''')
    cases['jump_pause100ms'] = guard
    # A causal bulk-order center: equally weight visible orders, reducing the
    # influence of one anomalous best quote. Prices remain submitted natively.
    center = replace_once(cap1, '        mid = (bid+ask)*0.5', '''        bid_prices=sorted(o.price for o in snapshot.bids if o.owner=='market')
        ask_prices=sorted(o.price for o in snapshot.asks if o.owner=='market')
        mid=(bid_prices[len(bid_prices)//2]+ask_prices[len(ask_prices)//2])*0.5''')
    cases['bulk_order_center'] = center
    return {name: describe(text, 'Round-2 development hypothesis: '+name+
        '. Causal public observations and matured labels; native fees unchanged.')
        for name, text in cases.items()}


def run_study(cases, output, workers=3):
    manifest=load_manifest(Path('logs/round2'))
    output=Path(output); (output/'sources').mkdir(parents=True,exist_ok=True)
    candidates=[]
    for name,text in cases.items():
        path=output/'sources'/(name+'.py')
        if path.exists(): assert path.read_text()==text, 'Immutable study source changed'
        else: path.write_text(text)
        errors=check(path)
        assert not errors, errors
        candidates.append(dict(name=name,file=str(path),source_sha256=digest(path),risk='native'))
    path=output/'results.json'
    report=json.loads(path.read_text()) if path.exists() else dict(
        scope='PUBLIC first-60% development tuning only; later public data unreplayed.',
        data_sha256=manifest['development_sha256'], native=native_stamp(), results={})
    assert report['data_sha256']==manifest['development_sha256']
    assert report['native']==native_stamp(), 'Evaluator/native rules changed'
    for c in candidates:
        if c['name'] in report['results']:
            assert report['results'][c['name']]['source_sha256']==c['source_sha256']
    write_json(output/'specs.json',dict(candidates=candidates,data_sha256=report['data_sha256'],native=report['native']))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        jobs={pool.submit(run_candidate,c,manifest['development'],output/c['name'],
                          (manifest['development_cutoff_us'],)):c['name']
              for c in candidates if c['name'] not in report['results']}
        for job in as_completed(jobs):
            name=jobs[job]; r=job.result(); report['results'][name]=r
            write_json(path,report)
            print(name,'NET',r['result']['pnl'],'fee',r['result']['breach_penalty'],
                  'volume',r['result']['traded_volume'],flush=True)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers',type=int,default=3)
    args=parser.parse_args()
    manifest=load_manifest(Path('logs/round2'))
    reference=next(c for c in manifest['candidates'] if c['name']=='round2_transfer')
    run_study(build_candidates(Path(reference['file']).read_text()),
              'logs/round2/jump_models',args.workers)


if __name__=='__main__': main()
