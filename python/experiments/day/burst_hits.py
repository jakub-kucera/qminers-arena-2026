"""Whether a burst over the 100-lot limit can pay: how often a strong forecast is followed by a big move its way.

    RIDGE_PRED_LOG=pred.csv rust/target/release/arena-sim --backtest TAPE.csv --strategy ridge_maker \
        --params '{...L9's...}' --no-logs
    uv run python -m experiments.day.burst_hits pred.csv [--min-move 5] [--gap-ms 1000]

The log is ridge_maker.rs's `RIDGE_PRED_LOG` (a line per book event once the model has its labels: time (us), mid,
prediction, skew, spread, inventory), as in `forecast_quality`. The signal is prediction - skew (what the forecast
take and the burst read). For each threshold, the onsets (an event with |signal| >= the threshold whose previous
such event, either sign, was more than --gap-ms before: a burst's trigger with BURST_GAP_MS) and every event at
or over it: the mid's move 0.5, 1 and 2 s later signed by the signal (the mid at the last event at or before
t + h), its mean, the share at least --min-move ticks its way and against it, and, for onsets, the best move its
way within the window (the most favourable mid in (t, t + h]) and the share of those at --min-move or more.
The break-even line: the penalty is 10,000 a second while |position| > 100, whatever the excess, so X lots over
the limit held h seconds need 10,000 h / X ticks a lot before the crossing costs. Standard library only.
"""

from __future__ import annotations

import argparse
import bisect
import math

THRESHOLDS = (0.75, 1.0, 1.5, 1.9)
HORIZONS = (500_000, 1_000_000, 2_000_000)
PENALTY_PER_S = 10_000.0


def load(path: str) -> list[list[float]]:
    cols: list[list[float]] = [[] for _ in range(6)]
    with open(path) as f:
        for line in f:
            for c, v in zip(cols, line.split(",")):
                c.append(float(v))
    return cols


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("log")
    parser.add_argument("--min-move", type=float, default=5.0, help="ticks (default 5)")
    parser.add_argument("--gap-ms", type=float, default=1000.0, help="between onsets (default 1000)")
    parser.add_argument("--jump-ms", type=float, default=500.0, help="the jumps' look-back (default 500)")
    args = parser.parse_args()
    t, mid, pred, skew, spread, _ = load(args.log)
    n = len(t)
    total = t[-1] - t[0]
    signal = [p - s for p, s in zip(pred, skew)]
    future = {h: [bisect.bisect_right(t, x + h) - 1 for x in t] for h in HORIZONS}
    print(f"{args.log}: {n:,} events over {total / 1e6:,.0f} s; a big move is {args.min_move:g}+ ticks")
    head = "".join(f" | {h / 1e6:g}s: mean  {'>=+M':>5} {'<=-M':>5}" for h in HORIZONS)
    for label in ("onsets", "events"):
        print(f"\n  {label}: {'|sig|>=':>7} {'n':>8} {'time %':>6} {'spr':>4}{head}"
              + ("".join(f" | best {h / 1e6:g}s: mean {'>=M':>5}" for h in HORIZONS) if label == "onsets" else ""))
        for th in THRESHOLDS:
            over = [i for i in range(n) if abs(signal[i]) >= th]
            if not over:
                print(f"  {'':>7} {th:>7.2f} {0:>8}")
                continue
            if label == "onsets":
                sel, last = [], -math.inf
                for i in over:
                    if t[i] - last > args.gap_ms * 1000:
                        sel.append(i)
                    last = t[i]
            else:
                sel = over
            time = sum((t[i + 1] - t[i]) for i in over if i + 1 < n)
            cells = ""
            for h in HORIZONS:
                ok = [i for i in sel if t[i] + h <= t[-1]]
                mv = [math.copysign(1, signal[i]) * (mid[future[h][i]] - mid[i]) for i in ok]
                if not mv:
                    cells += f" | {'':>8} {'':>5} {'':>5}"
                    continue
                up = sum(1 for m in mv if m >= args.min_move) / len(mv)
                dn = sum(1 for m in mv if m <= -args.min_move) / len(mv)
                cells += f" | {sum(mv) / len(mv):>+10.2f} {100 * up:>4.0f}% {100 * dn:>4.0f}%"
            if label == "onsets":
                for h in HORIZONS:
                    best = []
                    for i in sel:
                        if t[i] + h > t[-1]:
                            continue
                        s = math.copysign(1, signal[i])
                        best.append(max(s * (mid[j] - mid[i]) for j in range(i, future[h][i] + 1)))
                    if best:
                        hit = sum(1 for b in best if b >= args.min_move) / len(best)
                        cells += f" | {sum(best) / len(best):>+12.2f} {100 * hit:>4.0f}%"
            spr = sum(spread[i] for i in sel) / len(sel)
            print(f"  {'':>7} {th:>7.2f} {len(sel):>8,} {100 * time / total:>6.2f} {spr:>4.1f}{cells}")
    # Jumps: the mid moved J+ ticks over the last --jump-ms; does it go on (a momentum burst's trigger)?
    w = args.jump_ms * 1000
    back = [bisect.bisect_left(t, x - w) for x in t]
    print(f"\n  jumps (the mid {args.jump_ms:g} ms before at least J ticks away; onsets {args.gap_ms:g} ms apart), the move on its way,"
          " all / the forecast agreeing at |sig| >= 1:")
    print(f"  {'J':>4} {'who':>6} {'n':>6}" + "".join(f" | {h / 1e6:g}s: mean {'>=+M':>5} {'<=-M':>5}" for h in HORIZONS + (5_000_000,)))
    fut5 = [bisect.bisect_right(t, x + 5_000_000) - 1 for x in t]
    for jump in (5, 10, 15, 20, 30):
        onsets, last = [], -math.inf
        for i in range(n):
            d = mid[i] - mid[back[i]]
            if abs(d) >= jump:
                if t[i] - last > args.gap_ms * 1000:
                    onsets.append((i, 1 if d > 0 else -1))
                last = t[i]
        for who, keep in (("all", lambda i, s: True), ("agree", lambda i, s: s * signal[i] >= 1.0)):
            sel = [(i, s) for i, s in onsets if keep(i, s)]
            cells = ""
            for h, fut in list(future.items()) + [(5_000_000, fut5)]:
                mv = [s * (mid[fut[i]] - mid[i]) for i, s in sel if t[i] + h <= t[-1]]
                if not mv:
                    cells += f" | {'':>9} {'':>5} {'':>5}"
                    continue
                up = sum(1 for m in mv if m >= args.min_move) / len(mv)
                dn = sum(1 for m in mv if m <= -args.min_move) / len(mv)
                cells += f" | {sum(mv) / len(mv):>+9.2f} {100 * up:>4.0f}% {100 * dn:>4.0f}%"
            print(f"  {jump:>4} {who:>6} {len(sel):>6,}{cells}")
    print("\n  break-even ticks a lot over the limit (10,000/s, before crossing costs):")
    for x in (100, 300, 700, 900):
        print(f"    {x:>4} lots over: " + "  ".join(f"{h / 1e3:.0f} ms {PENALTY_PER_S * h / 1e6 / x:>5.1f}" for h in (200_000, 500_000, 1_000_000, 2_000_000)))


if __name__ == "__main__":
    main()
