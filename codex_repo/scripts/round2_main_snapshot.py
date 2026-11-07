"""Snapshot and audit active upstream-main models on the unchanged public tape."""
import json
import subprocess
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
from scripts.benchmark import digest
from scripts.check_submission import check
from scripts.round2_workbench import load_manifest,run_candidate,write_json


def main():
    commit=subprocess.check_output(['git','rev-parse','origin/main'],text=True).strip()
    # A main model must use precisely the same engine as this comparison.
    subprocess.run(['git','diff','--exit-code','origin/main','--','simulator'],check=True,stdout=subprocess.PIPE)
    root=Path('logs/round2_main_sync')/commit[:12];root.mkdir(parents=True,exist_ok=True)
    (root/'sources').mkdir(exist_ok=True)
    registry=json.loads(subprocess.check_output(['git','show',f'{commit}:strategies/round2/manifest.json']))
    m=load_manifest(Path('logs/round2_local_intake'))
    market=json.loads(Path('logs/round2_main_sync/market_dynamics.json').read_text())
    profile=next(iter(market.values()));assert profile['data_sha256']==m['data_sha256']
    prices=profile['price_samples'];windows={}
    for steps in (1,4):
        valid=[(prices[i-steps],prices[i]) for i in range(steps,len(prices))
               if prices[i-steps][1] is not None and prices[i][1] is not None]
        start,end=max(valid,key=lambda pair:pair[0][1]-pair[1][1])
        windows[f'largest_{steps*25}s_drop']=dict(start_us=start[0],end_us=end[0],start_mid=start[1],end_mid=end[1],drop_ticks=start[1]-end[1])
    candidates=[]
    for c in registry['candidates']:
        raw=subprocess.check_output(['git','show',f'{commit}:{c["file"]}'])
        p=root/'sources'/Path(c['file']).name
        if p.exists():assert p.read_bytes()==raw
        else:p.write_bytes(raw)
        assert not check(p),check(p)
        candidates.append(dict(name=c['name'],file=str(p),risk=c['risk'],source_sha256=digest(p),upstream_file=c['file'],registry_sha256=c['source_sha256']))
    protocol=dict(upstream_commit=commit,candidates=candidates,data_sha256=m['data_sha256'],native=m['native'],
        objective='Improve current upstream-main models by at least10000; additionally require10000 over existing local296715 to avoid claiming stale-main progress.',
        local_reference='strategies/round2/round2_local_296715.py',local_reference_sha256=digest('strategies/round2/round2_local_296715.py'),
        local_reference_pnl=296715,increment=10000,market_windows=windows,
        limitations='Consumed public tape; price windows descriptive, not future inputs or trading switches. User clarification about drop pending. Main snapshot does not claim future commits already monitored.')
    path=root/'protocol.json'
    if path.exists():assert json.loads(path.read_text())==protocol
    else:write_json(path,protocol)
    boundaries=sorted({m['development_cutoff_us'],m['validation_cutoff_us']}|{w[k] for w in windows.values() for k in ('start_us','end_us')})
    p=root/'results.json';results=json.loads(p.read_text()) if p.exists() else {}
    with ProcessPoolExecutor(max_workers=6) as pool:
        jobs={pool.submit(run_candidate,c,m['data'],root/c['name'],boundaries):c['name'] for c in candidates if c['name'] not in results}
        for future in as_completed(jobs):
            name=jobs[future];r=future.result();results[name]=r;write_json(p,results)
            print(name,r['result']['pnl'],flush=True)
    best=max(results,key=lambda name:results[name]['result']['pnl'])
    active=max((name for name in results if name!='round2_flat'),key=lambda name:results[name]['result']['pnl'])
    write_json(root/'baseline.json',dict(name=best,pnl=results[best]['result']['pnl'],upstream_commit=commit,
        active_name=active,active_pnl=results[active]['result']['pnl'],active_source_sha256=results[active]['source_sha256'],
        source_sha256=results[best]['source_sha256'],target=max(296715,results[best]['result']['pnl'])+10000,
        objective=protocol['objective'],scope='Current fetched main active registry; no unseen data'))


if __name__=='__main__':main()
