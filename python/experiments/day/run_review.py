"""Review a full-logs run of the Arena's simulator (ours, or the portal's results folder): our fills against the mid.

usage (from the repo root):
  uv run python -m experiments.day.run_review LOG_DIR [--horizons 1,5,30]

LOG_DIR is an `exchange-simulator` run without --no-logs, or a submission's results folder from the portal (the same
files: they are byte-identical to a local run of the same file on the same data, 2026-11-07). From book_deltas.csv it
rebuilds the market's best bid and ask (the market's orders only, ours left out); for each of our fills in trades.csv
it gives the edge at the fill (how far inside the mid we traded, positive is good) and the mid's move over each
horizon against our side (positive: the price went our way after the fill; negative: we were picked off); from
events.csv it counts what we sent, cancelled and had refused; from pnl.csv the PnL path. Standard library only.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import statistics
import sys
from collections import Counter
from pathlib import Path


def mids(log_dir: Path) -> tuple[list[int], list[float]]:
    """The market's mid after each book change, as (timestamps in µs, mids); ours are left out."""
    levels = {"B": {}, "A": {}}
    times, values = [], []
    with (log_dir / "book_deltas.csv").open() as f:
        for row in csv.DictReader(f):
            if row["owner"] != "market":
                continue
            side, price = levels[row["side"]], int(row["price"])
            side[price] = side.get(price, 0) + int(row["qty_diff"])
            if side[price] <= 0:
                del side[price]
            if levels["B"] and levels["A"]:
                mid = (max(levels["B"]) + min(levels["A"])) / 2
                t = int(row["timestamp_us"])
                if times and times[-1] == t:
                    values[-1] = mid
                else:
                    times.append(t)
                    values.append(mid)
    return times, values


def mid_at(times: list[int], values: list[float], t: int) -> float | None:
    i = bisect.bisect_right(times, t) - 1
    return values[i] if i >= 0 else None


def review(log_dir: Path, horizons: list[float]) -> str:
    times, values = mids(log_dir)
    fills = []
    with (log_dir / "trades.csv").open() as f:
        for row in csv.DictReader(f):
            ours_maker, ours_taker = row["maker_owner"] == "user", row["taker_owner"] == "user"
            if not (ours_maker or ours_taker):
                continue
            taker_buys = row["taker_side"] == "B"
            we_buy = taker_buys if ours_taker else not taker_buys
            fills.append((int(row["timestamp_us"]), int(row["price"]), int(row["quantity"]), we_buy, "taker" if ours_taker else "maker"))
    lines = [f"{log_dir}: {len(fills)} fills of ours, {sum(q for _, _, q, _, _ in fills):,} lots"]
    for role in ("maker", "taker"):
        group = [f for f in fills if f[4] == role]
        if not group:
            continue
        lots = sum(q for _, _, q, _, _ in group)
        edge = sum(q * ((m - p) if buy else (p - m)) for t, p, q, buy, _ in group if (m := mid_at(times, values, t)) is not None) / lots
        moves = []
        for h in horizons:
            total = 0.0
            for t, p, q, buy, _ in group:
                now, later = mid_at(times, values, t), mid_at(times, values, t + int(h * 1_000_000))
                if now is not None and later is not None:
                    total += q * ((later - now) if buy else (now - later))
            moves.append(f"{h:g}s {total / lots:+.2f}")
        lines.append(f"  as {role}: {len(group)} fills, {lots:,} lots; edge at the fill {edge:+.2f} ticks a lot; the mid's move our way after: " + ", ".join(moves))
    ops = Counter()
    with (log_dir / "events.csv").open() as f:
        for row in csv.DictReader(f):
            if row["source"] == "user":
                ops[row["operation"]] += 1
    lines.append("  our events: " + ", ".join(f"{k} {v:,}" for k, v in sorted(ops.items())))
    pnl = [float(r["pnl"]) for r in csv.DictReader((log_dir / "pnl.csv").open())]
    peak, drawdown = float("-inf"), 0.0
    for value in pnl:
        peak = max(peak, value)
        drawdown = max(drawdown, peak - value)
    quarters = [pnl[min(len(pnl) - 1, (len(pnl) * k) // 4)] for k in range(1, 5)]
    lines.append(f"  PnL: end {pnl[-1]:,.0f}, at each quarter " + " / ".join(f"{q:,.0f}" for q in quarters) + f", max drawdown {drawdown:,.0f}")
    result = json.loads((log_dir / "result.json").read_text())
    lines.append(f"  result.json: pnl {result['pnl']:,.2f}, breach {result['breach_penalty']:,.2f}, |inventory| q99.7 {result['abs_inventory_q997']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m experiments.day.run_review", description=__doc__.split("\n")[0])
    parser.add_argument("log_dir", type=Path)
    parser.add_argument("--horizons", default="1,5,30", help="seconds after each fill (default 1,5,30)")
    args = parser.parse_args(argv)
    print(review(args.log_dir, [float(h) for h in args.horizons.split(",")]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
