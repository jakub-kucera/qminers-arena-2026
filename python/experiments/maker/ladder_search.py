"""A random search over the shrink maker's ladder (7 Nov, round 1): LEVELS 2-5 and every knob that shapes the ladder.

Draws CELLS parameter sets at random from SPACE (seeded; KEEP_DEPTH at least LEVELS, as a deep order behind KEEP_DEPTH
is cancelled at once), runs each on DATA with the Rust port of python/bots/qminers/families/shrink_maker.py
(arena.qsim_rust's `arena-sim batch`, byte for byte the Python), and writes one CSV row per cell: its knobs, in_pnl
(the first 1 - HOLDOUT of the time), out_pnl (the rest), pnl, breach_penalty, fills. Choose on in_pnl only.

    uv run python -m experiments.maker.ladder_search DATA.csv --cells 1500 --seed 1 [--keep 0.6] --out results/ladder_random.csv
    uv run python -m experiments.maker.ladder_search DATA.csv --around '{"LEVELS": 3, ...}' --out results/ladder_nbhd.csv

--around: the cell and each knob of SPACE moved one step either way on its value list (the neighbourhood), plus
--fine's extra values. Every run has SESSION_S 1e9 (the round's whole tape) and FIXED's knobs unless the cell sets them.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import tempfile
import time
from pathlib import Path

from arena import qgrid, qsim_rust

FIXED = {"SESSION_S": 1_000_000_000}
SPACE = {
    "LEVELS": [2, 3, 4, 5],
    "KEEP_DEPTH": [2, 3, 4, 5, 6],
    "SIZE_TOUCH": [20, 35, 50, 65, 80, 100, 130],
    "SIZE_DEEP": [10, 20, 35, 50, 65, 80, 110, 140],
    "SIZE_NARROW": [50, 65, 80, 100, 115, 130, 150, 200],
    "SHRINK_NARROW": [0, 1],
    "TOPUP": [0, 1, 5, 10, 20],
    "CANCEL_ALONE": [0, 1],
    "REBALANCE": [0, 1],
    "SKEW": [60, 75, 85, 95, 100],
    "SKEW_CANCEL": [0, 1],
    "BACK_POS": [50, 70, 85, 95, 1000],
    "INSIDE_POS": [50, 80, 1000],
    "INSIDE_SPREAD": [2, 3],
    "DEPLETE_LOTS": [0, 50, 100, 150, 250],
    "DEPL_FRAC": [0.0, 0.03, 0.06, 0.1, 0.2],
    "DEPLETE_SIZE": [0, 10, 30],
    "REACT_CANCEL": [0, 1],
}
F6 = {"LEVELS": 2, "KEEP_DEPTH": 2, "SIZE_TOUCH": 65, "SIZE_DEEP": 80, "SIZE_NARROW": 115, "SHRINK_NARROW": 0, "TOPUP": 1,
      "CANCEL_ALONE": 1, "REBALANCE": 0, "SKEW": 100, "SKEW_CANCEL": 1, "BACK_POS": 1000, "INSIDE_POS": 1000,
      "INSIDE_SPREAD": 2, "DEPLETE_LOTS": 100, "DEPL_FRAC": 0.06, "DEPLETE_SIZE": 0, "REACT_CANCEL": 1}


def random_cells(n: int, seed: int, keep: float = 0.0) -> list[dict]:
    """n cells, each knob drawn from SPACE (kept at R1-F6's value with probability keep)."""
    rng = random.Random(seed)
    cells = []
    for _ in range(n):
        cell = {name: F6[name] if rng.random() < keep else rng.choice(values) for name, values in SPACE.items()}
        cell["KEEP_DEPTH"] = max(cell["KEEP_DEPTH"], cell["LEVELS"])
        cells.append(cell)
    return cells


def neighbours(cell: dict, fine: dict) -> list[dict]:
    """The cell, then each knob one step either way on its value list (and --fine's values)."""
    out = [dict(cell)]
    for name, values in SPACE.items():
        options = sorted(set(values) | set(fine.get(name, [])))
        here = cell.get(name, F6[name])
        if here not in options:
            options = sorted(set(options) | {here})
        i = options.index(here)
        picks = [options[j] for j in (i - 1, i + 1) if 0 <= j < len(options)] + [v for v in fine.get(name, []) if v != here]
        for value in dict.fromkeys(picks):
            moved = dict(cell)
            moved[name] = value
            out.append(moved)
    return out


def run(cells: list[dict], data: Path, threads: int, holdout: float) -> list[dict]:
    qsim_rust.build()
    with tempfile.TemporaryDirectory(prefix="ladder_search_") as scratch:
        files = qgrid.plain_csv([data], Path(scratch))
        params = [{**FIXED, **cell} for cell in cells]
        rows = qsim_rust.run_batch("shrink_maker", params, files, threads)
    out = []
    for cell, row in zip(cells, rows):
        result = qsim_rust.to_run(row[0])
        in_pnl, out_pnl = qgrid.split_pnl([result], holdout) if not result.error else (float("nan"), float("nan"))
        out.append({**cell, "in_pnl": in_pnl, "out_pnl": out_pnl, "pnl": result.pnl, "breach_penalty": result.breach_penalty,
                    "fills": result.fills, "error": result.error or ""})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="experiments.maker.ladder_search", description=__doc__.splitlines()[0])
    parser.add_argument("data", type=Path)
    parser.add_argument("--cells", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--keep", type=float, default=0.0, help="each knob kept at R1-F6's value with this probability")
    parser.add_argument("--around", type=json.loads, help="a cell as JSON: run it and its one-step neighbourhood")
    parser.add_argument("--fine", type=json.loads, default={}, help='extra values per knob for --around, {"SIZE_DEEP": [70, 90]}')
    parser.add_argument("--threads", type=int, default=10)
    parser.add_argument("--holdout", type=float, default=0.25)
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    cells = neighbours({**F6, **args.around}, args.fine) if args.around else [dict(F6)] + random_cells(args.cells, args.seed, args.keep)
    start = time.perf_counter()
    rows = run(cells, args.data, args.threads, args.holdout)
    print(f"{len(rows)} cells in {time.perf_counter() - start:.0f} s (the first: {'the --around cell' if args.around else 'R1-F6'})",
          file=sys.stderr)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"first: in {rows[0]['in_pnl']:,.0f}  (the table shows in_pnl only: choose on it; out_pnl and pnl are in the CSV)")
    ranked = sorted(rows, key=lambda r: -r["in_pnl"] if r["in_pnl"] == r["in_pnl"] else 1e18)
    for row in ranked[:args.top]:
        knobs = " ".join(f"{k}={row[k]}" for k in SPACE if row[k] != F6[k])
        print(f"in {row['in_pnl']:>10,.0f}  pen {row['breach_penalty']:>8,.0f}  fills {row['fills']:>6}  {knobs}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
