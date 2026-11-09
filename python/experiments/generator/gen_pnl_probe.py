"""Test PnL-to-price inversion against a public full-logs run before using hidden PnL.

The server gives elapsed_s,pnl, not inventory or cash. A PnL change also includes
fills, spread/depth marking and penalties; its sign is not the market move's sign.
This probe reconstructs the exact accounting from a public run's own trades and
market book deltas, then tests dPnL/100 and the stronger oracle dPnL/I_start against
the actual market mid change. Oracle inventory is evaluation data, never an input
available from a hidden pnl.csv. Final mark_price is a liquidation VWAP, not a mid.

Existing full logs suffice; otherwise first run:
    uv run exchange-simulator --strategy python/bots/qminers/candidates/round3/r3_F1_latent_filter.py \
        --backtest data/arena/round3/round3_public.csv --log-dir logs/r3_F1_full
    uv run python -m experiments.generator.gen_pnl_probe logs/r3_F1_full --out data/arena/gen/pnl_probe_r3.json

Add --curves RESULTS_DIR... to measure the same PnL-derived volatility proxies on
hidden runs. These are labelled proxies; no signed price path is fabricated.

No bot run is started by this command. A failed exact-accounting check aborts the
probe instead of silently treating misaligned samples as evidence against recovery.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

import numpy as np


def balances(trades: Path, sample_us: np.ndarray, limit: int, penalty_rate: float):
    """Cash/inventory immediately before each sample (the final row after events)."""
    times, changes, costs, last_times, last_prices = [], [], [], [], []
    with trades.open() as fh:
        for r in csv.DictReader(fh):
            t, price, lots = int(r["timestamp_us"]), int(r["price"]), int(r["quantity"])
            last_times.append(t)
            last_prices.append(price)
            sign = 1 if r["taker_side"] == "B" else -1
            if r["taker_owner"] == "user":
                dq = sign * lots
            elif r["maker_owner"] == "user":
                dq = -sign * lots
            else:
                continue
            times.append(t)
            changes.append(dq)
            costs.append(-dq * price)
    t = np.asarray(times, dtype=np.int64)
    q, cash = np.r_[0, np.cumsum(changes)], np.r_[0., np.cumsum(costs)]
    idx = np.searchsorted(t, sample_us, side="left")
    if len(sample_us):
        idx[-1] = np.searchsorted(t, sample_us[-1], side="right")
    notional = np.r_[0, np.cumsum(np.abs(changes))]
    # q[i] is in force between t[i-1] and t[i]. Multiple same-time fills
    # contribute zero duration, as in the exchange's breach integral.
    if len(t):
        penalty_cum = np.r_[0., np.cumsum(np.diff(t) / 1e6 * (np.abs(q[1:-1]) > limit) * penalty_rate)]
        penalty = np.zeros(len(sample_us))
        active = idx > 0
        j = idx[active] - 1
        penalty[active] = penalty_cum[j] + (sample_us[active] - t[j]) / 1e6 * (np.abs(q[idx[active]]) > limit) * penalty_rate
    else:
        penalty = np.zeros(len(sample_us))
    last_idx = np.searchsorted(last_times, sample_us, side="left")
    if len(sample_us):
        last_idx[-1] = np.searchsorted(last_times, sample_us[-1], side="right")
    last = np.r_[0., last_prices][last_idx]
    return {"inventory": q[idx], "cash": cash[idx], "penalty": penalty,
            "lots": notional[idx], "last_price": last}


def liquidation(levels, position: int, last: float) -> float:
    if not position:
        return 0.0
    side = levels[0 if position > 0 else 1]
    left, value = abs(position), 0.0
    for price in sorted(side, reverse=position > 0):
        take = min(left, side[price])
        value += take * price
        left -= take
        last = price
        if not left:
            break
    value += left * last
    return value if position > 0 else -value


def book_samples(path: Path, sample_us: np.ndarray, inventory, last_price):
    levels = [{}, {}]
    mid, marked = np.full(len(sample_us), np.nan), np.zeros(len(sample_us))
    i = 0

    def sample():
        if levels[0] and levels[1]:
            mid[i] = (max(levels[0]) + min(levels[1])) / 2
        marked[i] = liquidation(levels, int(inventory[i]), float(last_price[i]))

    with path.open() as fh:
        next(fh)
        for row in fh:
            t, side, price, owner, delta = row.strip().split(",")
            t = int(t)
            while i < len(sample_us) and (sample_us[i] < t or sample_us[i] == t and i < len(sample_us) - 1):
                sample()
                i += 1
            if owner != "market":
                continue
            book = levels[0 if side == "B" else 1]
            p = int(price)
            q = book.get(p, 0) + int(delta)
            if q < 0:
                raise ValueError(f"negative market depth at {t}, {side}, {p}")
            if q:
                book[p] = q
            else:
                book.pop(p, None)
    while i < len(sample_us):
        sample()
        i += 1
    return mid, marked


def comparison(estimate, truth, mask=None) -> dict:
    mask = np.isfinite(estimate) & np.isfinite(truth) & (True if mask is None else mask)
    x, y = estimate[mask], truth[mask]
    if not len(x):
        return {"n": 0}
    corr = float(np.corrcoef(x, y)[0, 1]) if len(x) > 1 and x.std() and y.std() else None
    return {"n": len(x), "correlation": corr, "rmse": float(np.sqrt(np.mean((x - y) ** 2))),
            "bias": float(np.mean(x - y)), "estimate_sd": float(x.std()), "truth_sd": float(y.std())}


def curve_proxy(path: Path, exposure: float = 100.) -> dict:
    """Available from a server PnL file alone; deliberately not called market RV."""
    path = path / "pnl.csv" if path.is_dir() else path
    curve = np.loadtxt(path, delimiter=",", skiprows=1, ndmin=2)
    dt = np.diff(curve[:, 0])
    if not len(dt) or np.any(dt <= 0) or not np.isfinite(curve).all():
        raise ValueError(f"invalid PnL curve: {path}")
    valid = abs(dt - 1) < 1e-6
    increments = np.diff(curve[:, 1]) / exposure
    v = increments[valid]
    if not len(v):
        raise ValueError(f"no complete one-second intervals: {path}")
    blocks = []
    for lo in range(0, int(curve[-1, 0]) - 59, 60):
        m = valid & (curve[:-1, 0] >= lo) & (curve[1:, 0] <= lo + 60)
        if m.sum() == 60:
            blocks.append({"start_s": lo, "mean_squared_dpnl_over_exposure": float(np.mean(increments[m] ** 2)),
                           "pnl_gain": float(increments[m].sum() * exposure)})
    return {"source": str(path), "exposure_assumption": exposure, "seconds": float(curve[-1, 0]),
            "complete_1s_intervals": len(v), "pnl": float(curve[-1, 1]),
            "rms_dpnl_over_exposure": float(np.sqrt(np.mean(v ** 2))),
            "abs_dpnl_over_exposure_p99": float(np.quantile(abs(v), .99)),
            "abs_proxy_5plus_per_1000s": float(np.mean(abs(v) >= 5) * 1000),
            "abs_proxy_20plus_per_1000s": float(np.mean(abs(v) >= 20) * 1000), "blocks_60s": blocks}


def probe(run: Path) -> dict:
    metadata = json.loads((run / "metadata.json").read_text())
    result = json.loads((run / "result.json").read_text())
    curve = np.loadtxt(run / "pnl.csv", delimiter=",", skiprows=1, ndmin=2)
    with (run / "events.csv").open() as fh:
        first_us = int(next(csv.DictReader(fh))["timestamp_us"])
    times = first_us + np.rint(curve[:, 0] * 1e6).astype(np.int64)
    if len(times) < 3 or np.any(np.diff(times) <= 0):
        raise ValueError("probe needs at least three increasing PnL samples")
    ledger = balances(run / "trades.csv", times, int(metadata.get("position_limit", 100)),
                      float(metadata.get("position_breach_penalty_per_second", 10_000)))
    mid, marked = book_samples(run / "book_deltas.csv", times, ledger["inventory"], ledger["last_price"])
    reproduced = ledger["cash"] + marked - ledger["penalty"]
    error = float(np.max(abs(reproduced - curve[:, 1])))
    if error > 1e-6 or abs(reproduced[-1] - result["pnl"]) > 1e-6:
        raise ValueError(f"accounting mismatch {error:g}; verify run logs, start time and sampling before interpreting the probe")
    dp, dm = np.diff(curve[:, 1]), np.diff(mid)
    whole_second = abs(np.diff(times) - 1_000_000) <= 1
    pos = ledger["inventory"][:-1]
    oracle = np.divide(dp, pos, out=np.full(len(dp), np.nan), where=pos != 0)
    large_pos = whole_second & (abs(pos) >= 95)
    unchanged = np.diff(ledger["lots"]) == 0
    rv = []
    for width in (60, 300, 1000):
        truth, estimated = [], []
        for lo in range(0, len(dp) - width + 1, width):
            valid = whole_second[lo:lo + width] & np.isfinite(dm[lo:lo + width])
            if valid.sum() < .9 * width:
                continue
            truth.append(float(np.mean(dm[lo:lo + width][valid] ** 2)))
            estimated.append(float(np.mean((dp[lo:lo + width][valid] / 100) ** 2)))
        rv.append({"block_s": width, **comparison(np.array(estimated), np.array(truth))})
    return {"run": str(run), "tape": metadata["data_file"], "accounting_max_error": error,
            "pnl": float(curve[-1, 1]), "end_mid": float(mid[-1]) if np.isfinite(mid[-1]) else None,
            "result_mark_price": result["mark_price"], "large_start_position_share": float(large_pos.mean()),
            "naive_signed_dpnl_over_100": comparison(dp / 100, dm, whole_second),
            "absolute_dpnl_over_100": comparison(abs(dp) / 100, abs(dm), whole_second),
            "oracle_signed_inventory": comparison(oracle, dm, large_pos),
            "oracle_no_fills": comparison(oracle, dm, large_pos & unchanged), "variance_proxy_by_block": rv,
            "pnl_only_proxy": curve_proxy(run),
            "interpretation": "PnL/100 is a testable volatility proxy, not an identified signed mid path. Oracle inventory is unavailable from hidden PnL-only logs; intrasecond fills and liquidation marking remain nuisance terms."}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("runs", type=Path, nargs="*")
    parser.add_argument("--curves", type=Path, nargs="+", default=[], help="also profile PnL-only result folders or CSVs")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.runs and not args.curves:
        parser.error("give public full-log runs and/or --curves PnL-only runs")
    reports = {"public_checks": [probe(path) for path in args.runs],
               "pnl_only_proxies": [curve_proxy(path) for path in args.curves]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(reports, indent=2, allow_nan=False) + "\n")
    for r in reports["public_checks"]:
        print(f"{r['run']}: accounting error {r['accounting_max_error']:g}; signed corr "
              f"{r['naive_signed_dpnl_over_100']['correlation']:.3f}; absolute corr "
              f"{r['absolute_dpnl_over_100']['correlation']:.3f}")
    for r in reports["pnl_only_proxies"]:
        print(f"{r['source']}: RMS PnL/100 proxy {r['rms_dpnl_over_exposure']:.3f}; "
              f"20+ proxy steps/1000s {r['abs_proxy_20plus_per_1000s']:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
