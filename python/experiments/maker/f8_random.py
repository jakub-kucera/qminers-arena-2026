"""A seeded random search over R1-F8's knobs on the Arena's own simulator (7 Nov, round 1): the plateau check.

Draws CELLS parameter sets from SPACE (each knob kept at R1-F8's value with probability KEEP), runs each with arena.qgrid's
run_one in a process pool, and writes one CSV row per cell with in_pnl (the first 1 - HOLDOUT of the time), out_pnl, pnl,
fills and breach_penalty. Choose on in_pnl only, and only a cell whose one-knob neighbours in the table are also good.

    uv run python -m experiments.maker.f8_random data/arena/round1/round1.csv --cells 200 --seed 1 --keep 0.5 --jobs 12 --out logs/f8_random.csv
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from arena import qgrid

BOT = "python/bots/qminers/candidates/round1/r1_F8_take_join.py"
SPACE = {
    "TAKE_LOTS": [40, 60, 80, 100],
    "TAKE_DEPLETE": [100, 150, 200],
    "TAKE_OWN": [400, 800, 1200],
    "TAKE_MS": [100, 250, 500],
    "ALLOC_K": [-0.25, -0.5, -0.75],
    "JOIN_OWN": [200, 300, 400, 600],
    "MOM_MS": [25, 50, 100],
    "MOM_LOTS": [300, 400, 600],
    "SIZE_NARROW": [90, 100, 115, 130],
    "SIZE_DEEP": [60, 80, 100],
    "SIZE_TOUCH": [50, 65, 80],
    "DEPL_FRAC": [0.08, 0.12, 0.16],
    "DYING_DEEP": [60, 80, 100],
    "DEPLETE_LOTS": [70, 100, 130],
}
F8 = {"TAKE_LOTS": 60, "TAKE_DEPLETE": 150, "TAKE_OWN": 800, "TAKE_MS": 250, "ALLOC_K": -0.5, "JOIN_OWN": 400, "MOM_MS": 50,
      "MOM_LOTS": 400, "SIZE_NARROW": 115, "SIZE_DEEP": 80, "SIZE_TOUCH": 65, "DEPL_FRAC": 0.12, "DYING_DEEP": 80, "DEPLETE_LOTS": 100}


def random_cells(n: int, seed: int, keep: float) -> list[dict]:
    rng = random.Random(seed)
    return [{k: (F8[k] if rng.random() < keep else rng.choice(v)) for k, v in SPACE.items()} for _ in range(n)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="experiments.maker.f8_random", description=__doc__.splitlines()[0])
    parser.add_argument("data", type=Path)
    parser.add_argument("--cells", type=int, default=200)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--keep", type=float, default=0.5)
    parser.add_argument("--jobs", type=int, default=12)
    parser.add_argument("--holdout", type=float, default=0.25)
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    cells = [dict(F8)] + random_cells(args.cells, args.seed, args.keep)
    start = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        runs = list(pool.map(qgrid.run_one, [BOT] * len(cells), cells, [str(args.data)] * len(cells), chunksize=1))
    rows = []
    for cell, run in zip(cells, runs):
        in_pnl, out_pnl = qgrid.split_pnl([run], args.holdout) if not run.error else (float("nan"), float("nan"))
        rows.append({**cell, "in_pnl": in_pnl, "out_pnl": out_pnl, "pnl": run.pnl, "breach_penalty": run.breach_penalty,
                     "fills": run.fills, "error": run.error or ""})
    print(f"{len(rows)} cells in {time.perf_counter() - start:.0f} s (the first: R1-F8)", file=sys.stderr)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"R1-F8: in {rows[0]['in_pnl']:,.0f}  (choose on in_pnl; out_pnl and pnl are in the CSV)")
    ranked = sorted(rows, key=lambda r: -r["in_pnl"] if r["in_pnl"] == r["in_pnl"] else 1e18)
    for row in ranked[:args.top]:
        knobs = " ".join(f"{k}={row[k]}" for k in SPACE if row[k] != F8[k])
        print(f"in {row['in_pnl']:>10,.0f}  out {row['out_pnl']:>9,.0f}  pen {row['breach_penalty']:>6,.0f}  {knobs}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
