"""How two or more bots' PnL curves move together on one tape: per pair, the correlation of their PnL changes over
1 / 10 / 60 / 500-s steps, and each one's total, from the `pnl.csv` an Arena simulator or `arena-sim --log-dir` run
writes (elapsed_s, pnl, one row a second). A strategy uncorrelated with the base is worth a combination test even
below it. Standard library plus numpy.

    uv run python -m experiments.day.pnl_corr BASE/pnl.csv OTHER/pnl.csv [MORE/pnl.csv ...] [--names L8,S1,...]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

STEPS = (1, 10, 60, 500)


def load(path: Path) -> np.ndarray:
    return np.loadtxt(path, delimiter=",", skiprows=1)[:, 1]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pnl", type=Path, nargs="+")
    ap.add_argument("--names", help="comma-separated labels, in order (default: each file's folder)")
    a = ap.parse_args(argv)
    names = a.names.split(",") if a.names else [p.parent.name for p in a.pnl]
    curves = [load(p) for p in a.pnl]
    n = min(len(c) for c in curves)
    curves = [c[:n] for c in curves]
    for name, c in zip(names, curves):
        print(f"{name:>24} total {c[-1]:>12,.0f}")
    print(f"{'pair':>40} " + " ".join(f"{f'corr {s}s':>10}" for s in STEPS))
    for i in range(len(curves)):
        for j in range(i + 1, len(curves)):
            row = []
            for s in STEPS:
                x, y = np.diff(curves[i][::s]), np.diff(curves[j][::s])
                row.append(f"{np.corrcoef(x, y)[0, 1]:>10.3f}" if len(x) > 2 and x.std() > 0 and y.std() > 0 else f"{'-':>10}")
            print(f"{names[i] + ' ~ ' + names[j]:>40} " + " ".join(row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
