"""Adverse selection of our maker fills against the market lots left at our price level when we were filled (7 Nov).

usage (from the repo root):
  uv run python -m experiments.maker.fill_depletion LOG_DIR [--horizon 1]

LOG_DIR is a full-logs `exchange-simulator` run (or a portal results folder). For each of our maker fills (trades.csv)
it takes the market's lots still resting at that side and price once every book delta up to the fill's timestamp is
applied (book_deltas.csv, the market's orders only: the lots behind us, since the ones ahead were taken first), the lots there just before the fill's timestamp (the
queue a depletion guard sees), and the size of the aggressive order that filled us (its lots over all its trades). It prints, per bin of each, the lots
filled, the edge at the fill against the mid and the mid's move our way after HORIZON seconds (negative: picked
off), lot-weighted: a depletion guard's threshold read off the data, not a grid. Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

from experiments.rounds.run_review import mid_at


def collect(log_dir: Path):
    """Our maker fills as [t, price, qty, we_buy, taker_order_id], and each taker order's total lots."""
    fills, taker_lots = [], defaultdict(int)
    with (log_dir / "trades.csv").open() as f:
        for row in csv.DictReader(f):
            q = int(row["quantity"])
            taker_lots[row["taker_order_id"]] += q
            if row["maker_owner"] == "user" and row["taker_owner"] != "user":
                fills.append([int(row["timestamp_us"]), int(row["price"]), q, row["taker_side"] == "A", row["taker_order_id"]])
    return fills, taker_lots


def replay(log_dir: Path, fills: list) -> tuple[list[int], list[float], list[int], list[int]]:
    """The market's mids (times, values) and, for each fill, the market lots at its side and price after the fill and
    just before its timestamp (the queue a depletion guard sees, at best)."""
    levels = {"B": {}, "A": {}}
    times, values, left, before = [], [], [0] * len(fills), [0] * len(fills)
    order = sorted(range(len(fills)), key=lambda i: fills[i][0])
    k = j = 0
    with (log_dir / "book_deltas.csv").open() as f:
        for row in csv.DictReader(f):
            t = int(row["timestamp_us"])
            while j < len(order) and fills[order[j]][0] <= t:
                fill = fills[order[j]]
                before[order[j]] = levels["B" if fill[3] else "A"].get(fill[1], 0)
                j += 1
            while k < len(order) and fills[order[k]][0] < t:
                fill = fills[order[k]]
                left[order[k]] = levels["B" if fill[3] else "A"].get(fill[1], 0)
                k += 1
            if row["owner"] != "market":
                continue
            side, price = levels[row["side"]], int(row["price"])
            side[price] = side.get(price, 0) + int(row["qty_diff"])
            if side[price] <= 0:
                del side[price]
            if levels["B"] and levels["A"]:
                mid = (max(levels["B"]) + min(levels["A"])) / 2
                if times and times[-1] == t:
                    values[-1] = mid
                else:
                    times.append(t)
                    values.append(mid)
    while k < len(order):
        fill = fills[order[k]]
        left[order[k]] = levels["B" if fill[3] else "A"].get(fill[1], 0)
        k += 1
    return times, values, left, before


def table(title: str, keys: list[int], bins: list[int], fills: list, times, values, horizon_us: int) -> list[str]:
    lines = [title]
    for lo, hi in zip(bins, bins[1:]):
        lots = edge = move = 0.0
        n = 0
        for key, (t, p, q, buy, _) in zip(keys, fills):
            if not lo <= key < hi:
                continue
            now, later = mid_at(times, values, t), mid_at(times, values, t + horizon_us)
            if now is None or later is None:
                continue
            n += 1
            lots += q
            edge += q * ((now - p) if buy else (p - now))
            move += q * ((later - now) if buy else (now - later))
        if lots:
            lines.append(f"  [{lo},{hi}): fills {n:7,}  lots {lots:10,.0f}  edge {edge / lots:+.3f}  move {move / lots:+.3f}"
                         f"  net {(edge + move) / lots:+.3f} ticks a lot")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m experiments.maker.fill_depletion", description=__doc__.split("\n")[0])
    parser.add_argument("log_dir", type=Path)
    parser.add_argument("--horizon", type=float, default=1.0, help="seconds after each fill (default 1)")
    args = parser.parse_args(argv)
    fills, taker_lots = collect(args.log_dir)
    times, values, left, before = replay(args.log_dir, fills)
    h = int(args.horizon * 1_000_000)
    bins = [0, 1, 25, 50, 100, 200, 400, 800, 10**9]
    out = table(f"{args.log_dir}: {len(fills):,} maker fills; by the market lots left at our level after the fill "
                f"(edge at the fill, the mid's move our way after {args.horizon:g} s):", left, bins, fills, times, values, h)
    out += table("by the market lots at our level just before the fill's timestamp (what a depletion guard can see):",
                 before, bins, fills, times, values, h)
    out += table("by the aggressive order's total lots:", [taker_lots[f[4]] for f in fills], [0, 10, 25, 60, 100, 200, 400, 10**9],
                 fills, times, values, h)
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
