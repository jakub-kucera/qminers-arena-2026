"""arena.qgrid on the Rust port of the Arena's exchange simulator (rust/arena_sim/, rust/README.md "arena_sim").

    uv run python -m arena.qsim_rust fallback_maker data/round1.csv [DATA2.csv ...] --grid QUOTE=2,5,10 \
        --grid LIMIT=30,50,80 [--set SKEW=15] [--threads 4] [--holdout 0.25] [--sort pnl|holdout|nbhd] \
        [--top 15] [--out results/qsim.csv]

The same table as arena.qgrid (its format_table, split, drawdown and neighbourhood code), the runs made by
`arena-sim batch` on threads instead of the Python simulator in processes: the same numbers to the bit
(python/tests/test_arena_rust.py), 50-100 times faster. Only strategies with a Rust version run, named or given
by their Python file (STRATEGIES); the grid's keys are the Python file's module globals (QUOTE, LIMIT, ...),
plus any Rust-only knob the strategy's .rs file documents.

Standard library only; arena.qgrid is imported for its table, not its simulator.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from arena import qgrid
from arena.botfile import parse_override
from arena.grid import Axis, parse_axis

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "rust" / "Cargo.toml"
BINARY = ROOT / "rust" / "target" / "release" / "arena-sim"

# Each Rust strategy and the Python file it copies.
STRATEGIES = {
    "trend_follower": "strategies/trend_follower.py",
    "fallback_maker": "python/bots/qminers/candidates/r0_F1_fallback.py",
    "room_maker": "python/bots/qminers/families/room_maker.py",
    "shrink_maker": "python/bots/qminers/families/shrink_maker.py",  # room_maker.rs, with DEPL_FRAC, REACT_CANCEL, MOM_LOTS
    "alloc_maker": "python/bots/qminers/families/alloc_maker.py",  # room_maker.rs at R1-F6's defaults, with ALLOC_K ... ADV_SCOPE
    "signal_maker": "python/bots/qminers/families/signal_maker.py",  # room_maker.rs at R1-F6's defaults, with MOM_SIZE ... SKEW_TRIM
    "take_maker": "python/bots/qminers/candidates/r1_F8_take_join.py",  # room_maker.rs at R1-F8's defaults, with TAKE_LOTS ... TAKE_MS, JOIN_*, ANY_CLEAR
    "probe": "python/tests/fixtures/qsim_probe.py",
}


def build() -> Path:
    """Builds arena-sim (cargo skips it when nothing changed) and returns the binary."""
    if shutil.which("cargo") is None:
        raise RuntimeError("arena_sim needs cargo (brew install rust), see rust/README.md")
    subprocess.run(["cargo", "build", "--release", "--quiet", "-p", "arena_sim", "--manifest-path", str(MANIFEST)], check=True)
    return BINARY


def strategy_name(text: str) -> str:
    """A Rust strategy's name, from its name or its Python file's path."""
    if text in STRATEGIES:
        return text
    path = Path(text).resolve()
    for name, file in STRATEGIES.items():
        if path == (ROOT / file).resolve():
            return name
    raise ValueError(f"no Rust version of {text!r}: one of {', '.join(STRATEGIES)} or their files ({', '.join(STRATEGIES.values())})")


def run_batch(strategy: str, params: list[dict], data: list[Path], threads: int = 1, public_depth: int = 20) -> list[list[dict]]:
    """Every parameter set on every plain-CSV file: result[task][file] is arena-sim's JSON for that run
    (result.json's fields, `rejected`, `cancel_rejected`, `curve` as [[ts_us, pnl], ...], `seconds`), or
    {"error": ...}."""
    for p in params:
        for key in p:
            if "." in key:
                raise ValueError(f"{key}: a Rust strategy's parameters are flat names (QUOTE, LIMIT), not paths")
    with tempfile.TemporaryDirectory(prefix="qsim_rust_") as scratch:
        tasks = Path(scratch) / "tasks.jsonl"
        tasks.write_text("".join(json.dumps(p) + "\n" for p in params))
        command = [str(BINARY), "batch", "--strategy", strategy, "--tasks", str(tasks), "--threads", str(threads),
                   "--public-depth", str(public_depth)]
        for path in data:
            command += ["--backtest", str(path)]
        out = subprocess.run(command, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"arena-sim batch failed: {out.stderr.strip()}")
    rows = [json.loads(line) for line in out.stdout.splitlines() if line.strip()]
    result = [[{} for _ in data] for _ in params]
    for row in rows:
        result[row["task"]][row["file"]] = row
    return result


def to_run(row: dict) -> qgrid.Run:
    if row.get("error"):
        return qgrid.Run(error=row["error"])
    return qgrid.Run(pnl=row["pnl"], breach_penalty=row["breach_penalty"], fills=row["fills"], traded_volume=row["traded_volume"],
                     inventory_q997=row["abs_inventory_q997"], pnl_se=row["pnl_se"], rejected=row["rejected"],
                     cancel_rejected=row["cancel_rejected"], curve=[(ts, pnl) for ts, pnl in row["curve"]])


def run_grid(strategy: str, data: list[Path], axes: list[Axis], base: dict, threads: int, holdout: float) -> tuple[qgrid.Cell, list[qgrid.Cell]]:
    """arena.qgrid.run_grid with the runs in Rust: the baseline and every cell, with their measures."""
    cells = [(None, ())] + qgrid.cells_of(axes)
    params = []
    for _, values in cells:
        overrides = dict(base)
        overrides.update({axis.target: value for axis, value in zip(axes, values)})
        params.append(overrides)
    runs = run_batch(strategy, params, data, threads)
    done = [qgrid.Cell(index, values, [to_run(row) for row in runs[i]]) for i, (index, values) in enumerate(cells)]
    for cell in done:
        cell.in_pnl, cell.out_pnl = qgrid.split_pnl(cell.runs, holdout)
        cell.drawdown = qgrid.max_drawdown(qgrid.chained(cell.runs))
    grid = done[1:]
    by_index = {cell.index: cell for cell in grid}
    shape = tuple(len(axis.values) for axis in axes)
    for cell in grid:
        cell.nbhd = qgrid.neighborhood_mean(by_index, cell.index, shape)
    return done[0], grid


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="arena.qsim_rust", description="arena.qgrid on the Rust exchange simulator.")
    parser.add_argument("strategy", help=f"a Rust strategy ({', '.join(STRATEGIES)}) or the Python file it copies")
    parser.add_argument("data", type=Path, nargs="+", help="backtest CSVs in the starter's format (.csv or .csv.gz)")
    parser.add_argument("--grid", action="append", default=[], type=parse_axis, help="NAME=V1,V2,... or NAME=START..STOP[..STEP]")
    parser.add_argument("--set", action="append", default=[], type=parse_override, dest="overrides", help="NAME=VALUE for every run")
    parser.add_argument("--threads", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    parser.add_argument("--holdout", type=float, default=0.25, help="the last share of each file's time held out (default 0.25)")
    parser.add_argument("--sort", choices=qgrid.SORTS, default="pnl")
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--out", type=Path, help="one CSV row per cell (and the baseline)")
    args = parser.parse_args(argv)
    if not 0 <= args.holdout < 1:
        parser.error("--holdout takes a share in [0, 1)")
    try:
        args.strategy = strategy_name(args.strategy)
    except ValueError as exc:
        parser.error(str(exc))
    for path in args.data:
        if not path.exists():
            parser.error(f"no such data file: {path}")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    build()
    with tempfile.TemporaryDirectory(prefix="qsim_rust_") as scratch:
        files = qgrid.plain_csv(args.data, Path(scratch))
        n = (1 + len(qgrid.cells_of(args.grid))) * len(files)
        print(f"{n} runs ({len(qgrid.cells_of(args.grid))} cells + baseline, {len(files)} files) on {args.threads} threads (Rust)", file=sys.stderr)
        start = time.perf_counter()
        baseline, grid = run_grid(args.strategy, files, args.grid, dict(args.overrides), args.threads, args.holdout)
        print(f"done in {time.perf_counter() - start:.2f} s", file=sys.stderr)
    print(qgrid.format_table(args.grid, args.data, baseline, grid, args.sort, args.top, args.holdout))
    if args.out:
        qgrid.write_csv(args.out, args.grid, args.data, baseline, grid)
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
