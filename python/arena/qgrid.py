"""Grid search on the Arena's own exchange simulator (`third_party/qminers-starter/simulator/`, the organisers' starter, third_party/qminers-starter/README.md).

    uv run python -m arena.qgrid BOT DATA.csv [DATA2.csv ...] --grid PARAMS.ASSET.make_edge=0,1,2 \
        --grid PARAMS.ASSET.make_size=5,10 [--set PATH=VALUE ...] [--jobs N] [--holdout 0.25] \
        [--sort pnl|holdout|nbhd] [--out results/qgrid.csv] [--top 15]

Every cell of the grid (and the bot as is, the baseline) runs on every data file, one fresh strategy
instance and simulator per run, at the rules' settings (simulator.main's constants), in a process pool.
The bot is loaded with arena.botfile.BotFile, so `--set` and the grid's values override its globals
(`--set 'PARAMS.ASSET={"fair": "mid"}'` creates the asset's entry the grid's PARAMS.ASSET.* keys go into).

The one module under python/arena besides analysis.py that imports a third-party package: the
competition's `simulator` (pydantic), which is what this tool exists to run.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import os
import shutil
import statistics
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from itertools import product
from pathlib import Path

from arena.botfile import BotFile, parse_override
from arena.grid import Axis, parse_axis

SORTS = ("pnl", "holdout", "nbhd")


@dataclass
class Run:
    """One bot setting on one data file."""

    pnl: float = 0.0
    breach_penalty: float = 0.0
    fills: int = 0
    traded_volume: int = 0
    inventory_q997: int = 0
    pnl_se: float | None = None
    rejected: int = 0  # orders the exchange refused (the position cap of MAX_POTENTIAL_POSITION)
    cancel_rejected: int = 0  # cancels and modifies that found no order (it had filled first)
    curve: list[tuple[int, float]] = field(default_factory=list)
    error: str | None = None


@dataclass
class Cell:
    """One grid cell (or the baseline) over every data file."""

    index: tuple[int, ...] | None  # None: the baseline
    values: tuple
    runs: list[Run]
    in_pnl: float = 0.0
    out_pnl: float = 0.0
    drawdown: float = 0.0
    nbhd: float = 0.0

    @property
    def error(self) -> str | None:
        return next((run.error for run in self.runs if run.error), None)

    @property
    def pnl(self) -> float:
        return sum(run.pnl for run in self.runs)

    def total(self, name: str):
        return sum(getattr(run, name) for run in self.runs)

    @property
    def inventory_q997(self) -> int:
        return max((run.inventory_q997 for run in self.runs), default=0)

    @property
    def pnl_se(self) -> float | None:
        ses = [run.pnl_se for run in self.runs]
        return None if any(se is None for se in ses) else sum(se * se for se in ses) ** 0.5


# ---------------------------------------------------------------------------- running


def strategy_class(module):
    """The module's BaseStrategy subclass, the alphabetically first as simulator.main's loader picks."""
    from simulator.strategy import BaseStrategy

    for name in sorted(dir(module)):
        candidate = getattr(module, name)
        if isinstance(candidate, type) and issubclass(candidate, BaseStrategy) and candidate is not BaseStrategy:
            return candidate
    raise ValueError(f"no BaseStrategy subclass in {module.__file__}")


def config():
    from simulator.main import MAX_POSITION, MAX_POTENTIAL_POSITION, ORDER_ACCEPT_DELAY_MS, POSITION_BREACH_PENALTY_PER_SECOND
    from simulator.simulator import SimulationConfig

    return SimulationConfig(max_position=MAX_POSITION, max_potential_position=MAX_POTENTIAL_POSITION,
                            position_breach_penalty_per_second=POSITION_BREACH_PENALTY_PER_SECOND,
                            order_accept_delay_ms=ORDER_ACCEPT_DELAY_MS)


def run_one(bot: str, overrides: dict, data: str) -> Run:
    """The bot with `overrides` on one plain-CSV data file; an exception is the run's error, not the grid's."""
    from simulator.models import OrderStatus
    from simulator.simulator import ExchangeSimulator

    try:
        module = BotFile(Path(bot), {}, overrides).load()
        sim = ExchangeSimulator(strategy=strategy_class(module)(), config=config())
        counts = {"order": 0, "cancel": 0}
        notify = sim._private_notify

        def counted(event):
            if event.status == OrderStatus.REJECTED:
                # A cancel's or modify's reject names an order that is no longer resting; an order's is the cap.
                counts["cancel" if event.message and "cancel" in event.message or event.remaining_quantity else "order"] += 1
            notify(event)

        sim._private_notify = counted
        result = sim.run(Path(data))
        return Run(pnl=result.pnl, breach_penalty=result.breach_penalty, fills=result.fills, traded_volume=result.traded_volume,
                   inventory_q997=result.abs_inventory_q997, pnl_se=result.pnl_se, rejected=counts["order"],
                   cancel_rejected=counts["cancel"], curve=sim.pnl_curve(result.pnl))
    except Exception as exc:  # noqa: BLE001 - a bad cell is reported, the others still run
        return Run(error=f"{type(exc).__name__}: {exc}")


def plain_csv(paths: list[Path], scratch: Path) -> list[Path]:
    """The data files as plain CSV (their simulator reads no gzip): a .gz is unpacked into `scratch`."""
    out = []
    for i, path in enumerate(paths):
        if path.suffix == ".gz":
            target = scratch / f"{i}_{path.stem}"
            with gzip.open(path, "rb") as source, target.open("wb") as sink:
                shutil.copyfileobj(source, sink)
            out.append(target)
        else:
            out.append(path)
    return out


def cells_of(axes: list[Axis]) -> list[tuple[tuple[int, ...], tuple]]:
    ranges = [range(len(axis.values)) for axis in axes]
    return [(index, tuple(axis.values[i] for axis, i in zip(axes, index))) for index in product(*ranges)]


def run_grid(bot: Path, data: list[Path], axes: list[Axis], base: dict, jobs: int, holdout: float) -> tuple[Cell, list[Cell]]:
    """The baseline and every cell, with their time-split, drawdown and neighbourhood numbers."""
    cells = [(None, ())] + cells_of(axes)
    tasks = []
    for index, values in cells:
        overrides = dict(base)
        overrides.update({axis.target: value for axis, value in zip(axes, values)})
        tasks.extend((str(bot), overrides, str(path)) for path in data)
    if jobs <= 1:
        runs = [run_one(*task) for task in tasks]
    else:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            runs = list(pool.map(run_one, *zip(*tasks), chunksize=1))
    done = [Cell(index, values, runs[i * len(data):(i + 1) * len(data)]) for i, (index, values) in enumerate(cells)]
    for cell in done:
        cell.in_pnl, cell.out_pnl = split_pnl(cell.runs, holdout)
        cell.drawdown = max_drawdown(chained(cell.runs))
    grid = done[1:]
    by_index = {cell.index: cell for cell in grid}
    shape = tuple(len(axis.values) for axis in axes)
    for cell in grid:
        cell.nbhd = neighborhood_mean(by_index, cell.index, shape)
    return done[0], grid


# ---------------------------------------------------------------------------- measures


def split_at(curve: list[tuple[int, float]], holdout: float) -> tuple[float, float]:
    """(PnL over the first 1 - holdout of the curve's time, PnL over the last holdout share)."""
    if not curve:
        return 0.0, 0.0
    start, end = curve[0][0], curve[-1][0]
    cut = start + (1 - holdout) * (end - start)
    at_cut = curve[0][1]
    for ts, pnl in curve:
        if ts > cut:
            break
        at_cut = pnl
    return at_cut, curve[-1][1] - at_cut


def split_pnl(runs: list[Run], holdout: float) -> tuple[float, float]:
    parts = [split_at(run.curve, holdout) for run in runs]
    return sum(p[0] for p in parts), sum(p[1] for p in parts)


def chained(runs: list[Run]) -> list[float]:
    """The files' PnL curves one after another, each starting where the last ended."""
    out, offset = [], 0.0
    for run in runs:
        out.extend(offset + pnl for _, pnl in run.curve)
        offset = out[-1] if out else offset
    return out


def max_drawdown(series: list[float]) -> float:
    peak, worst = 0.0, 0.0
    for value in series:
        peak = max(peak, value)
        worst = max(worst, peak - value)
    return worst


def neighborhood_mean(cells: dict[tuple[int, ...], Cell], index: tuple[int, ...], shape: tuple[int, ...]) -> float:
    """Mean PnL of the cell and its neighbours one step along each axis, failed neighbours left out (arena.grid's rule)."""
    pnls = [cells[index].pnl]
    for axis, size in enumerate(shape):
        for step in (-1, 1):
            position = index[axis] + step
            if 0 <= position < size:
                neighbour = cells[index[:axis] + (position,) + index[axis + 1:]]
                if neighbour.error is None:
                    pnls.append(neighbour.pnl)
    return statistics.fmean(pnls)


SORT_KEYS = {"pnl": lambda c: c.pnl, "holdout": lambda c: c.out_pnl, "nbhd": lambda c: c.nbhd}


# ---------------------------------------------------------------------------- output


def _num(x) -> str:
    return "-" if x is None else f"{x:,.0f}"


def _usable(grid: list[Cell]) -> list[Cell]:
    return [cell for cell in grid if cell.error is None]


def axis_ends(axes: list[Axis], grid: list[Cell], sort: str) -> list[str]:
    """arena.grid.format_axis_ends' rule: the best cell by `sort` on the lowest or highest value of a numeric
    axis of three or more values may have its best past that end, so widen the axis."""
    usable = _usable(grid)
    if not usable:
        return []
    best = max(usable, key=SORT_KEYS[sort])
    lines = []
    for axis, value in zip(axes, best.values):
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in axis.values):
            continue
        values = sorted(set(axis.values))
        if len(values) >= 3 and value in (values[0], values[-1]):
            lines.append(f"! the best cell by {sort} has {axis.label}={value}, the axis' {'lowest' if value == values[0] else 'highest'} value: "
                         "the best may lie past it, so widen the axis unless that end is a bound the setting can't pass")
    return lines


def format_table(axes: list[Axis], files: list[Path], baseline: Cell, grid: list[Cell], sort: str, top: int, holdout: float) -> str:
    multi = len(files) > 1
    split = f"{1 - holdout:.0%}|{holdout:.0%}"
    header = ["rank", *(axis.label for axis in axes), "pnl"] + ([f.name for f in files] if multi else [])
    header += [f"in {split.split('|')[0]}", f"out {split.split('|')[1]}", "nbhd", "max dd", "breach", "fills", "volume", "|inv| q997", "pnl se", "rej", "cxl rej", ""]

    def row(rank: str, cell: Cell) -> list[str]:
        shown = [str(v) for v in cell.values] if cell.index is not None else (["(as is)"] + [""] * (len(axes) - 1))[:len(axes)]
        if cell.error:
            return [rank, *shown] + [""] * (len(header) - len(axes) - 2) + [f"! {cell.error}"]
        cells = [rank, *shown, _num(cell.pnl)] + ([_num(run.pnl) for run in cell.runs] if multi else [])
        cells += [_num(cell.in_pnl), _num(cell.out_pnl), "-" if cell.index is None else _num(cell.nbhd), _num(cell.drawdown),
                  _num(cell.total("breach_penalty")), f"{cell.total('fills'):,}", f"{cell.total('traded_volume'):,}",
                  str(cell.inventory_q997), _num(cell.pnl_se), str(cell.total("rejected")), str(cell.total("cancel_rejected")),
                  "!" if cell.total("breach_penalty") > 0 or cell.total("rejected") else ""]
        return cells

    ranked = sorted(_usable(grid), key=SORT_KEYS[sort], reverse=True) + [cell for cell in grid if cell.error]
    table = [row("base", baseline)] + [row(str(rank), cell) for rank, cell in enumerate(ranked[:top], 1)]
    widths = [max(len(cells[i]) for cells in [header, *table]) for i in range(len(header))]
    lines = ["  ".join(c.rjust(w) for c, w in zip(cells, widths)).rstrip() for cells in [header, *table]]
    if len(ranked) > top:
        lines.append(f"  ... {len(ranked) - top} more (--top, or --out for all)")
    lines.append("")
    usable = _usable(grid)
    for name, key in SORT_KEYS.items():
        if usable:
            best = max(usable, key=key)
            setting = ", ".join(f"{axis.label}={v}" for axis, v in zip(axes, best.values))
            lines.append(f"best by {name:<7}  {setting}  ({_num(key(best))})")
    if usable:
        agree = len({max(usable, key=key).values for key in SORT_KEYS.values()}) == 1
        lines.append("all measures agree" if agree else "measures disagree: prefer a setting near the top on every measure over the single best pnl")
    breached = [cell for cell in [baseline, *grid] if not cell.error and cell.total("breach_penalty") > 0]
    rejecting = [cell for cell in [baseline, *grid] if not cell.error and cell.total("rejected")]
    failed = [cell for cell in [baseline, *grid] if cell.error]

    def named(cells: list[Cell]) -> str:
        shown = ["base" if c.index is None else ", ".join(f"{a.label}={v}" for a, v in zip(axes, c.values)) for c in cells[:5]]
        return " | ".join(shown) + (f" | ... {len(cells) - 5} more" if len(cells) > 5 else "")

    if breached:
        lines.append(f"! breach penalty in {len(breached)} cells (|position| over the limit costs 10,000 a second): {named(breached)}")
    if rejecting:
        lines.append(f"! rejected orders in {len(rejecting)} cells (over the potential-position cap): {named(rejecting)}")
    if failed:
        lines.append(f"! {len(failed)} cells raised: {named(failed)} (first: {failed[0].error})")
    lines.extend(axis_ends(axes, grid, sort))
    return "\n".join(lines)


CSV_COLUMNS = ["pnl", "in_pnl", "out_pnl", "nbhd", "max_drawdown", "breach_penalty", "fills", "traded_volume",
               "abs_inventory_q997", "pnl_se", "rejected", "cancel_rejected", "error"]


def write_csv(path: Path, axes: list[Axis], files: list[Path], baseline: Cell, grid: list[Cell]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["cell", *(axis.target for axis in axes), *CSV_COLUMNS, *(f"pnl:{file.name}" for file in files)])
        for cell in [baseline, *grid]:
            numbers = [cell.pnl, cell.in_pnl, cell.out_pnl, "" if cell.index is None else cell.nbhd, cell.drawdown,
                       cell.total("breach_penalty"), cell.total("fills"), cell.total("traded_volume"), cell.inventory_q997,
                       "" if cell.pnl_se is None else cell.pnl_se, cell.total("rejected"), cell.total("cancel_rejected"), cell.error or ""]
            values = [""] * len(axes) if cell.index is None else list(cell.values)
            writer.writerow(["baseline" if cell.index is None else "grid", *values, *numbers, *(run.pnl for run in cell.runs)])


# ---------------------------------------------------------------------------- CLI


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="arena.qgrid", description="Grid search on the Arena's exchange simulator.")
    parser.add_argument("bot", type=Path, help="a bot file with a BaseStrategy subclass (python/bots/qminers/template.py)")
    parser.add_argument("data", type=Path, nargs="+", help="backtest CSVs in the starter's format (.csv or .csv.gz)")
    parser.add_argument("--grid", action="append", default=[], type=parse_axis, help="PATH=V1,V2,... or PATH=START..STOP[..STEP]")
    parser.add_argument("--set", action="append", default=[], type=parse_override, dest="overrides",
                        help="PATH=VALUE for every run, the baseline's too, applied before the grid's "
                             "(--set 'PARAMS.ASSET={\"fair\": \"mid\"}' creates the asset's entry)")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--holdout", type=float, default=0.25, help="the last share of each file's time held out (default 0.25)")
    parser.add_argument("--sort", choices=SORTS, default="pnl")
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--out", type=Path, help="one CSV row per cell (and the baseline)")
    args = parser.parse_args(argv)
    if not 0 <= args.holdout < 1:
        parser.error("--holdout takes a share in [0, 1)")
    for path in args.data:
        if not path.exists():
            parser.error(f"no such data file: {path}")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    base = dict(args.overrides)
    with tempfile.TemporaryDirectory(prefix="qgrid_") as scratch:
        files = plain_csv(args.data, Path(scratch))
        n = (1 + len(cells_of(args.grid))) * len(files)
        print(f"{n} runs ({len(cells_of(args.grid))} cells + baseline, {len(files)} files) on {args.jobs} jobs", file=sys.stderr)
        baseline, grid = run_grid(args.bot, files, args.grid, base, args.jobs, args.holdout)
    print(format_table(args.grid, args.data, baseline, grid, args.sort, args.top, args.holdout))
    if args.out:
        write_csv(args.out, args.grid, args.data, baseline, grid)
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
