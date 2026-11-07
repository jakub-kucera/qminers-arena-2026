"""Reproducible evaluation using the competition's CLI configuration.

Run from the repository root:
python -m scripts.benchmark --backtest data/sample.csv --compare-flow

Blocks are increments of one continuous replay, not independent restarts.
The adaptive strategy continues learning causally during all blocks.
"""

import argparse
import csv
import hashlib
import json
import platform
import time
from bisect import bisect_right
from collections import Counter
from pathlib import Path

from simulator.main import (MAX_POSITION, MAX_POTENTIAL_POSITION,
                            ORDER_ACCEPT_DELAY_MS, POSITION_BREACH_PENALTY_PER_SECOND,
                            load_strategy_from_file)
from simulator.models import OrderStatus, Side
from simulator.simulator import ExchangeSimulator, PendingUserOrder, SimulationConfig
from strategies.arena_strategy import ArenaStrategy
from strategies.guarded_strategy import GuardedStrategy
from strategies.passive_strategy import PassiveStrategy


class FlowBaseline(ArenaStrategy):
    """Fixed flow signal, using the same sizing/execution/risk layer as ArenaStrategy."""
    def __init__(self):
        super().__init__()
        self._labels = self.MIN_LABELS
        self._weights = [4.0, 0.0, 0.0]

    def _learn(self, now, mid):
        pass


class AuditedSimulator(ExchangeSimulator):
    def __init__(self, strategy, config):
        super().__init__(strategy, config)
        self.max_abs_inventory = 0
        self.max_potential_inventory = 0
        self.status_counts = Counter()

    def submit_order(self, request):
        sign = 1 if request.side == Side.BUY else -1
        outstanding = self.book.resting_user_quantity(request.side)
        outstanding += sum(p.request.quantity for p in self._pending
                           if isinstance(p, PendingUserOrder) and p.request.side == request.side)
        self.max_potential_inventory = max(self.max_potential_inventory,
            abs(self._inventory + sign * (outstanding + request.quantity)))
        return super().submit_order(request)

    def _private_notify(self, event):
        self.status_counts[event.status.value] += 1
        self.max_abs_inventory = max(self.max_abs_inventory, abs(self._inventory))
        super()._private_notify(event)
        if isinstance(self.strategy, (ArenaStrategy, GuardedStrategy, PassiveStrategy)):
            if self.strategy.inventory != self._inventory or self.strategy.cash != self._cash:
                raise AssertionError('strategy ledger differs from the matching engine')
            if abs(self._inventory) > self.strategy.POSITION_LIMIT:
                raise AssertionError('strategy inventory limit breached')


def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def evaluate(strategy, data, destination, block_seconds, engine_class=AuditedSimulator):
    config = SimulationConfig(
        max_position=MAX_POSITION, max_potential_position=MAX_POTENTIAL_POSITION,
        position_breach_penalty_per_second=POSITION_BREACH_PENALTY_PER_SECOND,
        order_accept_delay_ms=ORDER_ACCEPT_DELAY_MS, public_depth=20,
    )
    engine = engine_class(strategy, config)
    started = time.perf_counter()
    result = engine.run(data)
    seconds = time.perf_counter() - started
    points = engine.pnl_curve(result.pnl)
    start = points[0][0]
    times = [(t - start)/1_000_000 for t, _ in points]
    peak = drawdown = 0.0
    for _, value in points:
        peak = max(peak, value)
        drawdown = max(drawdown, peak-value)
    blocks = []
    previous_pnl = points[0][1]
    previous_end = 0.0
    boundary = float(block_seconds)
    while previous_end < times[-1]:
        end = min(boundary, times[-1])
        pnl = points[bisect_right(times, end)-1][1]
        blocks.append({'start_s':previous_end, 'end_s':end, 'pnl_increment':pnl-previous_pnl})
        previous_end, previous_pnl = end, pnl
        boundary += block_seconds
    summary = {
        'result':result.model_dump(mode='json'), 'runtime_seconds':seconds,
        'max_abs_inventory':engine.max_abs_inventory,
        'max_potential_inventory_at_submission':engine.max_potential_inventory,
        'max_drawdown_1s':drawdown, 'submissions':engine._user_order_seq,
        'order_status_counts':dict(engine.status_counts), 'blocks':blocks,
        'config':config.model_dump(mode='json'),
    }
    if hasattr(engine, 'boundary_pnl'):
        summary['boundary_pnl'] = engine.boundary_pnl
    destination.mkdir(parents=True, exist_ok=True)
    (destination/'result.json').write_text(json.dumps(result.model_dump(mode='json'),indent=2)+'\n')
    (destination/'evaluation.json').write_text(json.dumps(summary,indent=2)+'\n')
    with (destination/'pnl.csv').open('w',newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['elapsed_s','pnl'])
        writer.writerows(zip(times, [v for _,v in points]))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backtest',type=Path,required=True)
    parser.add_argument('--strategy',type=Path,action='append')
    parser.add_argument('--compare-flow',action='store_true')
    parser.add_argument('--output',type=Path,default=Path('logs/benchmark'))
    parser.add_argument('--block-seconds',type=int,default=900)
    args = parser.parse_args()
    if args.block_seconds <= 0:
        parser.error('--block-seconds must be positive')
    paths = args.strategy or [Path('strategies/template_strategy.py'), Path('strategies/trend_follower.py'), Path('strategies/arena_strategy.py')]
    candidates = [(p.stem, load_strategy_from_file(p), p) for p in paths]
    if args.compare_flow:
        candidates.append(('flow_baseline',FlowBaseline(),Path('strategies/arena_strategy.py')))
    if len({name for name, _, _ in candidates}) != len(candidates):
        parser.error('strategy file stems must be unique')
    summaries = {}
    for name, strategy, path in candidates:
        summary = evaluate(strategy,args.backtest,args.output/name,args.block_seconds)
        summary['strategy_file'] = str(path)
        summary['strategy_sha256'] = digest(path)
        summaries[name] = summary
        result = summary['result']
        print(f'{name}: pnl={result["pnl"]:.2f}, penalty={result["breach_penalty"]:.2f}, '
              f'max_inventory={summary["max_abs_inventory"]}, drawdown={summary["max_drawdown_1s"]:.2f}, '
              f'blocks={[round(b["pnl_increment"],2) for b in summary["blocks"]]}')
    manifest = {
        'python':platform.python_version(), 'backtest':str(args.backtest.resolve()),
        'backtest_sha256':digest(args.backtest), 'benchmark_sha256':digest(__file__),
        'engine_sha256':digest('simulator/simulator.py'), 'models_sha256':digest('simulator/models.py'),
        'cli_sha256':digest('simulator/main.py'), 'base_strategy_sha256':digest('simulator/strategy.py'),
        'block_seconds':args.block_seconds, 'strategies':summaries,
    }
    (args.output/'comparison.json').write_text(json.dumps(manifest,indent=2)+'\n')


if __name__ == '__main__':
    main()
