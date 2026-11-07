"""Fine-grained no-trade price-shock diagnostics; never strategy inputs."""
from pathlib import Path
from scripts.compare_market_dynamics import DynamicsProbe
from scripts.round2_workbench import load_manifest,write_json
from simulator.simulator import ExchangeSimulator,SimulationConfig


def main():
    m=load_manifest(Path('logs/round2_local_intake'))
    probe=DynamicsProbe(period_us=1000000)
    result=ExchangeSimulator(probe,SimulationConfig(public_depth=20)).run(Path(m['data']))
    assert result.pnl==0 and result.traded_volume==0
    report=probe.report();report['data_sha256']=m['data_sha256']
    report['limitations']=['Full consumed public tape; no-trade market reconstruction.',
        'One-second samples can omit shorter transients; not unseen validation.']
    prices=report['price_samples'];windows={}
    for steps in (1,2,5,25,100):
        pairs=[(prices[i-steps],prices[i]) for i in range(steps,len(prices))
               if prices[i-steps][1] is not None and prices[i][1] is not None]
        start,end=max(pairs,key=lambda pair:pair[0][1]-pair[1][1])
        windows[str(steps)]=dict(start_us=start[0],end_us=end[0],start_mid=start[1],end_mid=end[1],drop_ticks=start[1]-end[1])
    report['largest_drop_windows']=windows
    write_json(Path('logs/round2_main_sync/market_dynamics_1s.json'),report)
    print(windows,flush=True)


if __name__=='__main__':main()
