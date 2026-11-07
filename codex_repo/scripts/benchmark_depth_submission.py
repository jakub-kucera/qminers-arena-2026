"""Measure the exact exported file with the unmodified competition engine."""
import argparse
import json
from pathlib import Path
import time

from scripts.benchmark import digest
from scripts.check_submission import check
from scripts.perf_check import peak_rss_bytes
from simulator.main import load_strategy_from_file
from simulator.simulator import ExchangeSimulator, SimulationConfig


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--strategy', type=Path, required=True)
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError(a.output)
    assert not check(a.strategy), check(a.strategy)
    config = SimulationConfig(max_position=100, max_potential_position=1000,
                              position_breach_penalty_per_second=10000,
                              order_accept_delay_ms=5, public_depth=20)
    engine = ExchangeSimulator(load_strategy_from_file(a.strategy), config)
    cpu, wall = time.process_time(), time.perf_counter()
    result = engine.run(a.data)
    report = {'result': result.model_dump(mode='json'),
              'cpu_seconds': time.process_time()-cpu,
              'wall_seconds': time.perf_counter()-wall,
              'peak_working_set_bytes': peak_rss_bytes(),
              'source_bytes': a.strategy.stat().st_size,
              'source_sha256': digest(a.strategy), 'data_sha256': digest(a.data),
              'engine_sha256': digest('simulator/simulator.py'),
              'config': config.model_dump(mode='json')}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
