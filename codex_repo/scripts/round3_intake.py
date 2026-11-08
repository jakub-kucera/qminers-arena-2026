"""Round-3 intake and first60% profiling/screening; later public40% preserved.

Reuses unchanged native evaluation. No round-2 cache or source is overwritten.
"""
import argparse
import json
from pathlib import Path

from scripts.benchmark import digest
from scripts.compare_market_dynamics import DynamicsProbe
from scripts.profile_round import MarketProbe,ProfileSimulator
from scripts.round2_distribution_stats import raw_statistics
from scripts.round2_taker_audit import batch
from scripts.round2_workbench import prepare,load_manifest,native_stamp,write_json
from simulator.simulator import SimulationConfig
from simulator.strategy import BaseStrategy

ROOT=Path('logs/round3')
SOURCES=[
    ('strategies/round2_final_317057.py','strict100','User final: robust online forecast with flow-impact features; no quotes'),
    ('strategies/round2_taker_liquidity_pure_294098.py','strict100','Simpler pure liquidity forecast, without final robust/impact additions'),
    ('strategies/round2_taker_liquidity_269920.py','strict100','Liquidity forecast with one-lot quote probes'),
    ('strategies/round2_imported/r2_M4_flow_window.py','strict100','Independent 125ms /575lot flow follower with causal self-gate'),
    ('strategies/round2_distribution_ensemble_shock_180895.py','native','Volatility-sized maker with round2-pretrained fill heads and shock exits'),
    ('strategies/round1_quote_flow_624076.py','native','Fixed-exposure round1 maker; tests return of spread-capture opportunity'),
    ('strategies/round2/round2_flat.py','strict100','No-trade zero-risk control'),
]


def intake():
    m=prepare('data/round3_public.csv',ROOT,[p for p,_,_ in SOURCES])
    roles={Path(p).stem:(risk,intent) for p,risk,intent in SOURCES}
    for c in m['candidates']:c['risk'],c['intent']=roles[c['name']]
    m.update(round=3,protocol_assumption='Existing round2 rules and public/validation/private distinction pending any new organizer changes supplied by user.',
        inspection_scope='Full-file structural validation, timestamp splits and hashes only. Head/tail rows were viewed at intake. No later40% statistical profiling or strategy replay.',
        initial_evaluation_scope='First60% public development only; middle20% reserved for selection, last20% reserved for later local check.')
    write_json(ROOT/'manifest.json',m);write_json(Path('results/round3_intake_manifest.json'),m)
    print(json.dumps({k:m[k] for k in ('rows','first_us','last_us','development_rows','development_cutoff_us','validation_cutoff_us','data_sha256')},indent=2),flush=True)


class CombinedProbe(BaseStrategy):
    def __init__(self):
        super().__init__()
        self.market=MarketProbe(block_us=600000000)
        self.dynamics={str(h):DynamicsProbe(h) for h in (1000000,25000000)}

    def on_order_book_change(self,snapshot,trades):
        self.market.on_order_book_change(snapshot,trades)
        for p in self.dynamics.values():p.on_order_book_change(snapshot,trades)


def profile_one(path,label):
    p=CombinedProbe();engine=ProfileSimulator(p,SimulationConfig(public_depth=20))
    result=engine.run(Path(path));assert result.pnl==0 and result.traded_volume==0
    report=dict(label=label,data=str(path),data_sha256=digest(path),native=native_stamp(),
        scope='First60% public tape only; no later round3 outcomes inspected.',
        profiler_sources={name:digest('scripts/'+name) for name in
            ('round3_intake.py','profile_round.py','compare_market_dynamics.py','round2_distribution_stats.py')},
        market=p.market.report(),operations=dict(engine.operations),
        max_events_in_aligned_5ms_bucket=engine.max_bucket_count,
        dynamics={k:v.report() for k,v in p.dynamics.items()},raw=raw_statistics(path),
        limitations=[
            'Signal labels overlap; correlations do not establish significance or net strategy PnL.',
            'One-lot quote round trips omit own impact, exit decision latency and actual callbacks.',
            'Public middle20% and last20% not profiled or replayed in this initial study.',
            'Scheduled cancel lifetimes include no-op requests after earlier fills.'])
    out=ROOT/'profile';out.mkdir(exist_ok=True)
    write_json(out/(label+'.json'),report)
    print(label,'SD1s',report['dynamics']['1000000']['sampled_return_sd_ticks'],
        'SD25s',report['dynamics']['25000000']['sampled_return_sd_ticks'],
        'spread',report['market']['time_weighted_book']['spread_ticks']['mean'],flush=True)
    return report


def profile():
    m=load_manifest(ROOT);old=load_manifest(Path('logs/round2'))
    reports={}
    for label,path in [('round3',m['development']),('round2',old['development'])]:
        reports[label]=profile_one(path,label)
        write_json(Path('results/round3_development_profiles.json'),reports)


def screen(workers):
    m=load_manifest(ROOT)
    report=batch(m['candidates'],m['development'],ROOT/'development',
        (m['development_cutoff_us'],),workers,
        scope='Seven frozen sources, round3 PUBLIC first60% only. Source selection predates observed round3 performance. Later40% remains unreplayed.')
    report['round3_manifest_sha256']=digest(ROOT/'manifest.json')
    write_json(Path('results/round3_initial_screen.json'),report)


def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=('prepare','profile','screen'));p.add_argument('--workers',type=int,default=2)
    args=p.parse_args()
    if args.command=='prepare':intake()
    elif args.command=='profile':profile()
    else:screen(args.workers)


if __name__=='__main__':main()
