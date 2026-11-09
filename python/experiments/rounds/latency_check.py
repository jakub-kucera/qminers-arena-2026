"""A bot's PnL on the Arena's simulator at slower order paths than the rules' 5 ms (`order_accept_delay_ms`), every
other setting the rules' (simulator.main's constants): how much of a taker's edge is speed.

    uv run python -m experiments.rounds.latency_check BOT.py DATA.csv [--delays 5,10,20,50] [--jobs 3]
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path


def run(job: tuple[str, str, int]) -> tuple[int, float, int, int, float]:
    bot, data, delay = job
    from arena.botfile import BotFile
    from arena.qgrid import strategy_class
    from simulator.main import MAX_POSITION, MAX_POTENTIAL_POSITION, POSITION_BREACH_PENALTY_PER_SECOND
    from simulator.simulator import ExchangeSimulator, SimulationConfig

    config = SimulationConfig(max_position=MAX_POSITION, max_potential_position=MAX_POTENTIAL_POSITION,
                              position_breach_penalty_per_second=POSITION_BREACH_PENALTY_PER_SECOND,
                              order_accept_delay_ms=delay)
    module = BotFile(Path(bot), {}, {}).load()
    result = ExchangeSimulator(strategy=strategy_class(module)(), config=config).run(Path(data))
    return delay, result.pnl, result.fills, result.traded_volume, result.breach_penalty


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("bot")
    parser.add_argument("data")
    parser.add_argument("--delays", default="5,10,20,50")
    parser.add_argument("--jobs", type=int, default=3)
    args = parser.parse_args()
    jobs = [(args.bot, args.data, int(d)) for d in args.delays.split(",")]
    with ProcessPoolExecutor(args.jobs) as pool:
        for delay, pnl, fills, volume, breach in pool.map(run, jobs):
            print(f"delay {delay:3} ms  pnl {pnl:12,.2f}  fills {fills:6,}  volume {volume:9,}  breach {breach:,.0f}")


if __name__ == "__main__":
    main()
