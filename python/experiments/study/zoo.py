"""Scores every bot in python/bots/zoo/ against the template.

usage (from the repo root): uv run python -m experiments.study.zoo [--jobs N] [--local] [--engine rust]

Each zoo bot, and the template, on P3 round 1 (all three days, the data SPEC.md describes):
  - alone, per tick, under --match-trades all and worse;
  - in one market with the template (`--vs`, per tick, all): the zoo bot's PnL and the template's;
  - inside arena.sim's market (its presets, seeds 0-2, default mode), where orders move the price.
Then the whole field at once: the template and the zoo bots in one market on P3 round 1. The field
leaves out the bots from local models (those with a `.json` from python/bots/zoo/local.py) unless --local:
no team will code with them, and their disasters would make the template's field PnL flatter it.
Errors, limit breaches and the bot's slowest tick are listed too. Results go into IDEAS.md
("The LLM zoo"); python/bots/zoo/README.md says how to add bots from other providers.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from arena import rust, sim
from arena.cli import add_engine_argument, backtest, backtest_days
from arena.engine import EngineConfig, TradeMatching
from arena.formats import prosperity

ZOO = Path("python/bots/zoo")
TEMPLATE = Path("python/bots/template.py")
SEEDS = (0, 1, 2)
ENGINE = ["python"]  # set in each worker by _init (--engine)


def _init(engine: str) -> None:
    ENGINE[0] = engine


def zoo_bots() -> list[Path]:
    return sorted(p for p in ZOO.rglob("*.py") if p.name not in {"bundle.py", "local.py"})


def is_local(path: Path) -> bool:
    return path.with_suffix(".json").exists()


def label(path: Path) -> str:
    return "template" if path == TEMPLATE else f"{path.parent.name}/{path.stem}"


def run(day, paths_by_name: list[tuple[str, Path]], config: EngineConfig = EngineConfig()):
    """The bots in one market, on the engine --engine chose (each with its file's own settings)."""
    return backtest(day, [(name, path, {}, False) for name, path in paths_by_name], config, ENGINE[0], fields=("pnl", "errors", "breaches"))


def in_sim(path: Path) -> float:
    """The bot's PnL inside arena.sim's market over SEEDS."""
    spec = sim.preset_market()
    if ENGINE[0] == "rust":
        return sum(row["bots"]["bot"]["pnl"] for row in rust.run_sim(spec, SEEDS[0], len(SEEDS), [("bot", path, {}, False)]))
    return sum(total(sim.run(spec, seed, [("bot", prosperity.load_bot(path, {}, strict=False))]).results[0]) for seed in SEEDS)


def total(result) -> float:
    return sum(series[-1] for series in result.pnl.values() if series)


def score(path: Path) -> dict:
    days = backtest_days("p3", ["1"], ENGINE[0])
    row = {"bot": label(path), "errors": 0, "breaches": 0, "slowest_ms": 0.0, "by_product": {}}
    for mode in (TradeMatching.ALL, TradeMatching.WORSE):
        pnl = 0.0
        for day in days:
            (result,) = run(day, [("bot", path)], EngineConfig(trade_matching=mode))
            pnl += total(result)
            if mode is TradeMatching.ALL:
                row["errors"] += len(result.errors)
                row["breaches"] += len(result.limit_breaches)
                row["slowest_ms"] = max(row["slowest_ms"], 1000 * max(result.step_seconds, default=0)) if ENGINE[0] == "python" else None
                for product, series in result.pnl.items():
                    row["by_product"][product] = row["by_product"].get(product, 0.0) + (series[-1] if series else 0.0)
                if result.errors and "first_error" not in row:
                    row["first_error"] = result.errors[0][1].strip().splitlines()[-1]
        row[mode.value] = pnl
    if path != TEMPLATE:
        mine = theirs = 0.0
        for day in days:
            template, bot = run(day, [("template", TEMPLATE), ("bot", path)])
            mine, theirs = mine + total(template), theirs + total(bot)
        row["vs_template"], row["template_vs"] = theirs, mine
    row["sim"] = in_sim(path)
    return row


def field(local: bool) -> dict[str, float]:
    days = backtest_days("p3", ["1"], ENGINE[0])
    paths = [TEMPLATE, *(p for p in zoo_bots() if local or not is_local(p))]
    totals = dict.fromkeys(map(label, paths), 0.0)
    for day in days:
        results = run(day, [(label(p), p) for p in paths])
        for path, result in zip(paths, results):
            totals[label(path)] += total(result)
    return totals


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m experiments.study.zoo")
    parser.add_argument("--jobs", type=int, default=None, help="worker processes (default: one per CPU)")
    parser.add_argument("--local", action="store_true", help="put the local models' bots in the field too")
    add_engine_argument(parser, "run the backtests in rust/ (the same results; the slowest-tick column is the Python bot's, so it's blank)")
    args = parser.parse_args()
    if args.engine == "rust":
        rust.require(args.allow_stale)
    paths = [TEMPLATE, *zoo_bots()]
    with ProcessPoolExecutor(args.jobs, initializer=_init, initargs=(args.engine,)) as pool:
        rows = list(pool.map(score, paths))
        crowd = pool.submit(field, args.local).result()

    print(f"P3 round 1, all three days; sim = arena.sim presets, seeds 0-2; a field of {len(crowd)}"
          f"{'' if args.local else ', without the local models'}. PnL in thousands.\n")
    print("| Bot | alone, `all` | alone, `worse` | with the template (bot / template) | in arena.sim | in the field | errors | breaches | slowest tick |")
    print("|---|---|---|---|---|---|---|---|---|")
    for row in rows:
        vs = f"{row['vs_template'] / 1000:.1f} / {row['template_vs'] / 1000:.1f}" if "vs_template" in row else "-"
        in_field = f"{crowd[row['bot']] / 1000:.1f}" if row["bot"] in crowd else "-"
        slowest = "-" if row["slowest_ms"] is None else f"{row['slowest_ms']:.1f} ms"
        print(
            f"| {row['bot']} | {row['all'] / 1000:.1f} | {row['worse'] / 1000:.1f} | {vs} | {row['sim'] / 1000:.1f}"
            f" | {in_field} | {row['errors']} | {row['breaches']} | {slowest} |"
        )
    print("\nAlone under `all`, by product (thousands):")
    for row in rows:
        products = ", ".join(f"{p} {v / 1000:.1f}" for p, v in row["by_product"].items())
        print(f"  {row['bot']}: {products}" + (f"  (first error: {row['first_error']})" if "first_error" in row else ""))


if __name__ == "__main__":
    main()
