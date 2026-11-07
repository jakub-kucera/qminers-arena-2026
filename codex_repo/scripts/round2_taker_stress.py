"""Compare strategy families on artificial public-derived regime stress tapes."""
import argparse
import json
from pathlib import Path

from scripts.benchmark import digest
from scripts.round2_taker_audit import batch
from scripts.round2_workbench import write_json

SOURCES={
    'T2':('strategies/round2_imported/r2_T2_take_only_safe.py','strict100'),
    'liquidity':('strategies/round2_taker_liquidity_269920.py','strict100'),
    'window_bias':('strategies/round2_taker_flowbias_227839.py','strict100'),
    'pure':('strategies/round2_taker_pure_209616.py','strict100'),
    'M4':('strategies/round2_imported/r2_M4_flow_window.py','strict100'),
    'maker181':('strategies/round2_distribution_ensemble_shock_180895.py','native'),
    'V2':('strategies/round2_imported/r2_V2_vol_exposure_dz18.py','native'),
}


def main():
    p=argparse.ArgumentParser();p.add_argument('--tape',choices=('highvol_1x','highvol_1p25'),default='highvol_1p25')
    p.add_argument('--names',nargs='+',choices=tuple(SOURCES),default=list(SOURCES));p.add_argument('--workers',type=int,default=3)
    args=p.parse_args();manifest=json.loads(Path('logs/round2/regime_stress/manifest.json').read_text());tape=manifest['tapes'][args.tape]
    assert digest(tape['path'])==tape['sha256'];candidates=[]
    for name in args.names:
        path,risk=SOURCES[name];candidates.append(dict(name=name,file=path,source_sha256=digest(path),risk=risk))
    out=Path('logs/round2/taker_stress')/args.tape
    report=batch(candidates,tape['path'],out,tape['seam_exclusion_boundaries_us'],args.workers,
        scope='Artificial repeated high-volatility PUBLIC segments. Native5ms latency unchanged. Not a replica, estimate, validation score or independent sample of the hidden tape.')
    for name,r in report['results'].items():
        seam_pnl=sum(r['boundary_pnl'][str(t+2000000)]-r['boundary_pnl'][str(t-2000000)] for t in tape['seams_us'])
        r['seam_window_pnl']=seam_pnl;r['net_excluding_seam_windows']=r['result']['pnl']-seam_pnl
        r['observed_synthetic_seconds']=tape['duration_seconds']
        print('STRESS CLEAN',args.tape,name,'full',r['result']['pnl'],'excluding seams',r['net_excluding_seam_windows'],flush=True)
    report['tape_provenance']=tape
    write_json(out/'scored_results.json',report);write_json(Path('results')/f'round2_taker_stress_{args.tape}.json',report)


if __name__=='__main__':main()
