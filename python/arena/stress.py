"""Reruns a bot on perturbed copies of each day, to see what a regime change costs it.

    uv run python -m arena.stress python/bots/template.py 1                        # P3 round 1, every perturbation
    uv run python -m arena.stress python/bots/template.py 1 2 --data p4 --only shift_up,shift_down
    uv run python -m arena.stress python/bots/template.py 1 --size 2 --resting --set PARAMS.KELP.stop_loss=2000
    uv run python -m arena.stress python/bots/template.py 1 2 3 --data p4 --engine rust              # the same, on rust/ (bots with a Rust twin)

The Arena's private run may not look like the download: Qminers' 2024 final switched regime, and
a fixed anchor or a level set from the download breaks when the price moves away for good
(references/wiki/concepts/harder-rounds.md, B1). Each perturbation moves a product's whole book,
its market trades and its mark by the same offset at a tick, so the book's shape and the trades'
place in it are kept; only the price path changes. Sizes are in the product's median spread `s`
over the day, times `--size`, and every offset is a whole number of the product's ticks:

    vol2         every tick's distance from the day's first wall mid is doubled, so every move of the
                 price and its volatility double; the book keeps its shape, so the spread doesn't widen
                 with it, and the market is tighter relative to its moves
    trend_up     a steady drift adding up to 10 s over the day (trend_down: down)
    shift_up     the price moves 5 s at the middle of the day and stays (shift_down: down)
    spike_up     the price moves 5 s at the middle of the day and comes back 100 ticks later
    no_wall      for the middle fifth of the day the largest level on each side is gone

`permute(day, seed, block)` is a different kind of copy, for arena.grid's permutation test: the
day's own ticks in a shuffled order, in runs of `block` ticks, each shifted so the price continues
by the move it had in the real day. Each tick's book, its trades' place in it, the products'
ticks together and the day's net move are kept; anything that depends on the order of ticks
longer than a run (mean reversion, trends, a level the price returns to, a signal that leads the
price) is gone.

It prints each product's PnL on the plain day and under each perturbation, summed over the days,
its largest intraday drawdown on a plain day (what a loss stop must leave room for), and its worst
single (day, perturbation). The template's loss stop and regime guard are judged by that last
column (`stop_loss` in python/bots/template.py: no product should lose much more than its stop).
"""

from __future__ import annotations

import argparse
import math
import os
import random
import statistics
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

from arena import report, rust
from arena.botfile import OverrideError
from arena.cli import add_common_arguments, add_engine_argument, add_rival_argument, participants, run_with_rivals, setup
from arena.formats import FORMATS
from arena.model import Book, Day, Tick

PERTURBATIONS = ("vol2", "trend_up", "trend_down", "shift_up", "shift_down", "spike_up", "spike_down", "no_wall")
SPIKE_TICKS = 100


def perturb(day: Day, name: str, size: float = 1.0) -> Day:
    """A copy of the day with one perturbation applied to every product."""
    if name not in PERTURBATIONS:
        raise ValueError(f"unknown perturbation {name!r}: choose from {', '.join(PERTURBATIONS)}")
    n = len(day.ticks)
    if name == "no_wall":
        start, end = int(0.4 * n), int(0.6 * n)
        ticks = [
            replace(t, books={p: _without_walls(b) for p, b in t.books.items()}) if start <= k < end else t
            for k, t in enumerate(day.ticks)
        ]
        return replace(day, name=f"{day.name}/{name}", ticks=ticks)
    offsets = {product: _offsets(day, product, name, size) for product in day.products}
    ticks = [_shifted(t, {p: offsets[p][k] for p in day.products}) for k, t in enumerate(day.ticks)]
    return replace(day, name=f"{day.name}/{name}", ticks=ticks)


def permute(day: Day, seed: int, block: int = 1) -> Day:
    """A copy of the day made of its own ticks in a shuffled order, in runs of `block` ticks.

    Each tick keeps its book, its trades and its mark, and the move of its wall bid (the largest
    bid level, as Book.wall_mid picks it) from the tick before it in the real day. In the copy it
    is shifted so that its wall bid continues from the previous copied tick's by that move: the
    wall bid is on the tick grid, so the shift is exact. Inside a run the copy is the real day,
    moved by a constant; only the joins between runs are new. The shuffle is the same for every
    product, so their ticks stay together, timestamps stay in order, and each product's wall bid
    ends where the real day's does (and starts at most one real move from where it did)."""
    n = len(day.ticks)
    runs = [list(range(k, min(k + block, n))) for k in range(0, n, block)]
    random.Random(seed).shuffle(runs)
    order = [k for run in runs for k in run]
    offsets = {}
    for product in day.products:
        walls = _forward_fill([max(b.bids, key=lambda level: level[1])[0] if (b := t.books.get(product)) and b.bids else None
                               for t in day.ticks])
        first = next((w for w in walls if w is not None), None)
        if first is None:
            offsets[product] = [0] * n
            continue
        walls = [first if w is None else w for w in walls]
        moves = [0] + [walls[k] - walls[k - 1] for k in range(1, n)]
        level, out = walls[0], []  # the level before the first tick (whose own move is 0)
        for k in order:
            level += moves[k]
            out.append(level - walls[k])
        offsets[product] = out
    ticks = []
    for j, k in enumerate(order):
        moved = _shifted(day.ticks[k], {p: offsets[p][j] for p in day.products})
        stamp = day.ticks[j].timestamp
        trades = {p: [replace(t, timestamp=stamp) for t in ts] for p, ts in moved.trades.items()}
        ticks.append(replace(moved, timestamp=stamp, trades=trades))
    return replace(day, name=f"{day.name}/permuted{seed}", ticks=ticks)


def _offsets(day: Day, product: str, name: str, size: float) -> list[int]:
    n = len(day.ticks)
    walls = _forward_fill([t.books[product].wall_mid if product in t.books else None for t in day.ticks])
    spreads = [b.asks[0][0] - b.bids[0][0] for t in day.ticks if (b := t.books.get(product)) and b.bids and b.asks]
    s = max(statistics.median(spreads), 1) if spreads else 1
    tick = _tick(day, product)
    sign = -1 if name.endswith("_down") else 1
    half = n // 2

    def on_grid(x: float) -> int:  # offsets move prices by whole ticks, so the book stays on its grid
        return round(x / tick) * tick

    if name == "vol2":
        first = next((w for w in walls if w is not None), None)
        return [0 if w is None or first is None else on_grid(size * (w - first)) for w in walls]
    if name.startswith("trend"):
        return [on_grid(sign * 10 * s * size * k / max(n - 1, 1)) for k in range(n)]
    if name.startswith("shift"):
        return [on_grid(sign * 5 * s * size) if k >= half else 0 for k in range(n)]
    return [on_grid(sign * 5 * s * size) if half <= k < half + SPIKE_TICKS else 0 for k in range(n)]  # spike


def _tick(day: Day, product: str) -> int:
    """The product's price increment in the data's units: the gcd of the gaps between its prices.

    1 in Prosperity's data; more where a format keeps prices in a unit finer than the tick (the
    drill format's cents, with ALPHA's tick of 5)."""
    prices = sorted({int(price) for t in day.ticks for b in [t.books.get(product)] if b for price, _ in b.bids + b.asks})
    return math.gcd(*(b - a for a, b in zip(prices, prices[1:]))) or 1


def _forward_fill(values):
    out, last = [], None
    for value in values:
        last = value if value is not None else last
        out.append(last)
    return out


def _shifted(tick: Tick, offsets: dict[str, int]) -> Tick:
    if not any(offsets.values()):
        return tick
    books = {
        p: Book(tuple((price + offsets.get(p, 0), v) for price, v in b.bids), tuple((price + offsets.get(p, 0), v) for price, v in b.asks))
        for p, b in tick.books.items()
    }
    trades = {p: [replace(t, price=t.price + offsets.get(p, 0)) for t in ts] for p, ts in tick.trades.items()}
    marks = {p: m + offsets.get(p, 0) for p, m in tick.marks.items()}
    return replace(tick, books=books, trades=trades, marks=marks)


def _without_walls(book: Book) -> Book:
    def drop_largest(levels):
        if len(levels) < 2:
            return levels
        largest = max(range(len(levels)), key=lambda i: levels[i][1])
        return levels[:largest] + levels[largest + 1 :]

    return Book(drop_largest(book.bids), drop_largest(book.asks))


# ---------------------------------------------------------------------------- running


_WORKER: dict = {}


def _init(format_name, data_arg, day_specs, bot, overrides, rivals, config, requote):
    fmt = FORMATS[format_name]
    days = fmt.load_days(fmt.resolve_data_dir(data_arg), day_specs)
    _WORKER.update(fmt=fmt, days=days, bot=bot, overrides=overrides, rivals=rivals, config=config, requote=requote)


def _run(task: tuple[int, str | None, float]) -> tuple[str, str | None, dict[str, float], int, dict[str, float], str]:
    k, name, size = task
    w = _WORKER
    day = w["days"][k] if name is None else perturb(w["days"][k], name, size)
    result = run_with_rivals(w["fmt"], day, w["bot"], w["overrides"], w["rivals"], w["config"], requote=w["requote"])[0]
    pnl = {p: series[-1] for p, series in result.pnl.items() if series}
    first = result.errors[0][1].strip().splitlines()[-1] if result.errors else ""
    return w["days"][k].name, name, pnl, len(result.errors), {p: report.max_drawdown(series) for p, series in result.pnl.items()}, first


def _run_rust(args, s, tasks: list[tuple[int, str | None, float]]) -> list[tuple]:
    """_run for every task, as one `arena-rs batch`: Rust makes each perturbed day itself (rust/src/arena/stress.rs)."""
    with tempfile.TemporaryDirectory() as folder:
        scratch = Path(folder)
        paths = [rust.write_day(day, scratch / f"day{k}") for k, day in enumerate(s.days)]
        bots = participants(args.bot, s.overrides, s.rivals, s.requote)
        specs = [rust.bot_spec(path, o, r) for _, path, o, r in bots]
        batch = [{"day": k, "transform": None if name is None else f"{name}:{size!r}", "config": rust.config_json(s.config),
                  "bots": [[n, j] for j, (n, *_) in enumerate(bots)], "blocks": 1, "fine": 1} for k, name, size in tasks]
        found = rust.run_batch(paths, specs, batch, args.jobs or os.cpu_count() or 1, scratch)
    return [(s.days[k].name, name, r["products"], r["errors"], r["drawdowns"], r.get("first_error", "")) for (k, name, _), r in zip(tasks, found)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m arena.stress", description="Rerun a bot on perturbed days.")
    add_common_arguments(parser)
    add_rival_argument(parser)
    add_engine_argument(parser)
    parser.add_argument("--only", help=f"comma-separated perturbations (default: all of {', '.join(PERTURBATIONS)})")
    parser.add_argument("--size", type=float, default=1.0, help="scale every perturbation (default: 1)")
    parser.add_argument("--jobs", type=int, default=None, help="worker processes (default: one per CPU)")
    args = parser.parse_args(argv)
    names = args.only.split(",") if args.only else list(PERTURBATIONS)
    try:
        s = setup(args)
        s.format.load_bot(args.bot, s.overrides, strict=True)
        for name in names:
            perturb(Day("check", [], {}, []), name)
        if s.engine == "rust":
            rust.prepare(args.format, [args.bot, *s.rivals], args.allow_stale)
            rust.bot_spec(args.bot, s.overrides)
    except (ValueError, OSError, OverrideError, RuntimeError) as error:
        parser.error(str(error))

    tasks = [(k, name, args.size) for k in range(len(s.days)) for name in [None, *names]]
    if s.engine == "rust":
        runs = _run_rust(args, s, tasks)
    else:
        with ProcessPoolExecutor(args.jobs, initializer=_init, initargs=(args.format, args.data, args.days, args.bot, s.overrides, s.rivals, s.config, s.requote)) as pool:
            runs = list(pool.map(_run, tasks))

    products = sorted({p for _, _, pnl, *_ in runs for p, v in pnl.items() if v})
    columns = ["plain", *names]
    totals = {(p, c): 0.0 for p in products for c in columns}
    worst: dict[str, tuple[float, str]] = {}
    drawdown: dict[str, float] = {}
    for day, name, pnl, _, drawdowns, _ in runs:
        if name is None:
            for p, value in drawdowns.items():
                drawdown[p] = max(drawdown.get(p, 0.0), value)
        for p in products:
            if p not in pnl:  # not traded that day
                continue
            value = pnl[p]
            totals[(p, name or "plain")] += value
            if value < worst.get(p, (float("inf"), ""))[0]:
                worst[p] = (value, f"{day} {name or 'plain'}")
    width = max([len(p) for p in products] + [7])
    print(f"{len(s.days)} day(s), size {args.size:g}: PnL summed over the days\n")
    print(f"{'product':<{width}}" + "".join(f"  {c:>11}" for c in columns) + "  plain drawdown  worst day")
    for p in products:
        value, where = worst[p]
        print(f"{p:<{width}}" + "".join(f"  {totals[(p, c)]:>11,.0f}" for c in columns) + f"  {drawdown.get(p, 0):>14,.0f}  {value:,.0f} ({where})")
    print(f"{'total':<{width}}" + "".join(f"  {sum(totals[(p, c)] for p in products):>11,.0f}" for c in columns))
    errors = sum(e for _, _, _, e, *_ in runs)
    if errors:
        print(f"\n! {errors} bot errors across the runs; each run's first:")
        for day, name, _, n, _, first in runs:
            if n:  # a perturbation can push prices where the bot fails, e.g. below zero
                print(f"  {day} {name or 'plain'}: {n:,} errors, first: {first or '(no message)'}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
