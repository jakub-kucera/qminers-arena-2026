"""Describe profit inside and outside market-only shock windows."""
import csv
import json
from pathlib import Path
from scripts.round2_workbench import write_json


def main():
    root=Path('logs/round2_main_sync')
    market=json.loads((root/'market_dynamics_1s.json').read_text())
    manifest=json.loads(Path('logs/round2_local_intake/manifest.json').read_text())
    assert market['data_sha256']==manifest['data_sha256']
    studies={'reference296715':'round2_t2_noquote_combo',
             'flow304476':'round2_t2_flow_magnitude',
             'depth310978':'round2_t2_impact_ablation',
             'robust316031':'round2_t2_robust_shocks'}
    report=dict(data_sha256=manifest['data_sha256'],windows=market['largest_drop_windows'],models={},
        scope='One-second sampled diagnostics on consumed public tape; no time rules in strategies')
    for name,study in studies.items():
        folder=Path('logs')/study
        audit=json.loads((folder/'full_audit.json').read_text())
        native=json.loads((folder/'official_cli/result.json').read_text());assert native==audit['result']
        assert audit['data_sha256']==manifest['data_sha256']
        curve={float(r['elapsed_s']):float(r['pnl']) for r in csv.DictReader((folder/'official_cli/pnl.csv').open())}
        model=dict(net_pnl=native['pnl'],source_sha256=audit['source_sha256'],windows={})
        for key,w in market['largest_drop_windows'].items():
            start=(w['start_us']-manifest['first_us'])/1e6
            end=(w['end_us']-manifest['first_us'])/1e6
            gain=curve[end]-curve[start]
            model['windows'][key]=dict(pnl_inside=gain,pnl_outside=native['pnl']-gain)
        peak=peak_time=0;worst=dict(amount=0,start_s=0,end_s=0)
        for t,pnl in curve.items():
            if pnl>peak:peak=pnl;peak_time=t
            if peak-pnl>worst['amount']:worst=dict(amount=peak-pnl,start_s=peak_time,end_s=t)
        model['sampled_max_drawdown']=worst
        report['models'][name]=model
    prices={(t-manifest['first_us'])/1e6:mid for t,mid in market['price_samples']}
    report['rebound_5398_5400']=dict(start_s=5398,end_s=5400,start_mid=prices[5398],end_mid=prices[5400],rise_ticks=prices[5400]-prices[5398])
    write_json(root/'crash_comparison.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
