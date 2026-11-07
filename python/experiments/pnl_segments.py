"""A run's PnL in fixed segments, from the pnl.csv that `exchange-simulator --no-logs` writes, and a candidate against a
baseline segment by segment (how many it is ahead in, the mean difference, its t and the worst segment).

    uv run python -m experiments.pnl_segments CANDIDATE/pnl.csv [BASELINE/pnl.csv] [--seconds 1000] [--count 12]
"""

from __future__ import annotations

import argparse
import csv
import math


def segments(path: str, seconds: float, count: int) -> tuple[list[float], float]:
    """The PnL gained in each of `count` segments of `seconds`, and the final PnL."""
    points = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            points[float(row["elapsed_s"])] = float(row["pnl"])
    times = sorted(points)

    def at(t: float) -> float:
        return points[max(x for x in times if x <= t)]

    out = [at(min(seconds * (i + 1), times[-1])) - at(seconds * i) for i in range(count)]
    return out, points[times[-1]]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("candidate")
    parser.add_argument("baseline", nargs="?")
    parser.add_argument("--seconds", type=float, default=1000.0)
    parser.add_argument("--count", type=int, default=12)
    args = parser.parse_args()
    a, total_a = segments(args.candidate, args.seconds, args.count)
    print("candidate", [round(x) for x in a], "total", round(total_a))
    if args.baseline:
        b, total_b = segments(args.baseline, args.seconds, args.count)
        print("baseline ", [round(x) for x in b], "total", round(total_b))
        d = [x - y for x, y in zip(a, b)]
        mean = sum(d) / len(d)
        sd = math.sqrt(sum((x - mean) ** 2 for x in d) / (len(d) - 1)) if len(d) > 1 else 0.0
        t = mean / (sd / math.sqrt(len(d))) if sd > 0 else float("nan")
        ahead = sum(1 for x in d if x > 0)
        print("difference", [round(x) for x in d])
        print(f"ahead in {ahead} of {len(d)}, mean {mean:+,.0f}, t {t:.2f}, worst {min(d):+,.0f}")


if __name__ == "__main__":
    main()
