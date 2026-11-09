"""How good the ridge maker's forecast is: the realised mid move after a prediction of a given size.

    RIDGE_PRED_LOG=pred.csv rust/target/release/arena-sim --backtest TAPE.csv --strategy ridge_maker \
        --params '{...C12's...}' --no-logs
    uv run python -m experiments.taker.forecast_quality pred.csv

The log (ridge_maker.rs, `RIDGE_PRED_LOG`) has a line per book event once the model has its labels: time (us),
mid, prediction, skew, spread, inventory. For each event whose |prediction - skew| falls in a bin, the mid's move
400 ms and 1 s later signed by the prediction (the mid at the last event at or before t + h), by spread: the
events, the share of the time spent there, the episodes (runs of such events with gaps under 100 ms), the mean
move, the move less half the spread (what an IOC at the far touch keeps if marked at the mid), and the share
of moves the prediction's way. Standard library only.
"""

from __future__ import annotations

import argparse
import bisect
import math

BINS = [0.5, 0.75, 1.0, 1.25, 1.5, 2.01]
HORIZONS = (400_000, 1_000_000)


def load(path: str) -> list[list[float]]:
    cols: list[list[float]] = [[] for _ in range(6)]
    with open(path) as f:
        for line in f:
            for c, v in zip(cols, line.split(",")):
                c.append(float(v))
    return cols


def corr(x: list[float], y: list[float]) -> float:
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    return sxy / math.sqrt(sxx * syy)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("log")
    args = parser.parse_args()
    t, mid, pred, skew, spread, _ = load(args.log)
    n = len(t)
    total = t[-1] - t[0]
    future = {}
    for h in HORIZONS:
        future[h] = [bisect.bisect_right(t, x + h) - 1 for x in t]
    print(f"{args.log}: {n:,} events over {total / 1e6:,.0f} s")
    for h in HORIZONS:
        idx = [i for i in range(n) if t[i] + h <= t[-1]]
        move = [mid[future[h][i]] - mid[i] for i in idx]
        print(f"  h = {h / 1e3:.0f} ms: corr(prediction, move) = {corr([pred[i] for i in idx], move):.3f}")
    signal = [p - s for p, s in zip(pred, skew)]
    print(f"  {'|pred-skew|':>11} {'spread':>6} {'events':>9} {'time %':>6} {'episodes':>8} {'move 0.4s':>9} {'move 1s':>7}"
          f" {'half spr':>8} {'net 0.4s':>8} {'net 1s':>6} {'hit 0.4s':>8}")
    for name, keep in (("all", lambda s: True), ("1", lambda s: s == 1), ("2+", lambda s: s >= 2)):
        for lo, hi in zip(BINS[:-1], BINS[1:]):
            sel = [i for i in range(n) if lo <= abs(signal[i]) < hi and keep(spread[i])]
            if not sel:
                continue
            time = sum((t[i + 1] - t[i]) if i + 1 < n else 0 for i in sel)
            episodes = 1 + sum(1 for a, b in zip(sel, sel[1:]) if t[b] - t[a] > 100_000)
            moves = []
            for h in HORIZONS:
                ok = [i for i in sel if t[i] + h <= t[-1]]
                mv = [math.copysign(1, signal[i]) * (mid[future[h][i]] - mid[i]) for i in ok]
                moves.append((sum(mv) / len(mv), sum(1 for m in mv if m > 0) / len(mv)))
            half = sum(spread[i] for i in sel) / len(sel) / 2
            print(f"  {lo:>5.2f}-{hi:<5.2f} {name:>6} {len(sel):>9,} {100 * time / total:>6.2f} {episodes:>8,}"
                  f" {moves[0][0]:>9.3f} {moves[1][0]:>7.3f} {half:>8.2f} {moves[0][0] - half:>8.3f}"
                  f" {moves[1][0] - half:>6.3f} {moves[0][1]:>8.2f}")


if __name__ == "__main__":
    main()
