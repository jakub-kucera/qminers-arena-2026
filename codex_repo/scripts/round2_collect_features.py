"""Collect causal public features on development only, with no user orders."""
from pathlib import Path
import json
import numpy as np
from simulator import main as cli
from simulator.simulator import ExchangeSimulator, SimulationConfig
from scripts.benchmark import digest
from scripts.round2_workbench import load_manifest, write_json


def main():
    manifest = load_manifest(Path('logs/round2_local_intake'))
    root = Path('logs/round2_nonlinear');root.mkdir(exist_ok=True)
    path = Path('strategies/round2/round2_strict100.py')
    strategy = cli.load_strategy_from_file(path)
    strategy._learn = lambda *_: None
    strategy._quote = lambda *_: None
    strategy._hedge = lambda *_: None
    original = strategy.on_order_book_change
    rows, markets = [], []
    def observe(snapshot,trades):
        original(snapshot,trades)
        if strategy._observations and strategy._observations[-1][0] == snapshot.timestamp_us:
            row=strategy._observations[-1]
            if not rows or row[0]!=rows[-1][0]:rows.append((row[0],row[1],*row[2]))
        bid=next((o.price for o in snapshot.bids if o.owner=='market'),None)
        ask=next((o.price for o in snapshot.asks if o.owner=='market'),None)
        if bid is not None and ask is not None and bid<ask:
            markets.append((snapshot.timestamp_us,(bid+ask)/2,ask-bid))
    strategy.on_order_book_change=observe
    config=SimulationConfig(max_position=cli.MAX_POSITION,max_potential_position=cli.MAX_POTENTIAL_POSITION,
        position_breach_penalty_per_second=cli.POSITION_BREACH_PENALTY_PER_SECOND,
        order_accept_delay_ms=cli.ORDER_ACCEPT_DELAY_MS,public_depth=20)
    result=ExchangeSimulator(strategy,config).run(Path(manifest['development']))
    assert result.fills==0 and result.pnl==0
    a=np.array(rows);m=np.array(markets)
    np.savez_compressed(root/'public_features.npz',observations=a,market=m)
    report=dict(rows=len(a),market_events=len(m),source_sha256=digest(path),
                data_sha256=manifest['development_sha256'],scope='Public development first 60% only; no orders.',
                features=29,own_flow_features=[23,27],
                note='Own-fill features are zero here and excluded from nonlinear fitting/export.')
    write_json(root/'features.json',report)
    print(json.dumps(report))


if __name__=='__main__':main()
