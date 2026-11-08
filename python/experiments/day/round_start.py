"""The first look at a round's data in one command: the tape's profile, every prepared candidate run, the next grids.

usage (from the repo root):
  uv run python -m experiments.day.round_start DATA.csv[.gz] [--jobs N] [--out DIR] [--candidates runner,M1,...]

1. **Profile.** The tape replayed once through the Arena's own `ExchangeSimulator` (exact matching), with a recorder in
   place of the public feed: rows, the Time span, events a second; the spread's time-weighted distribution in ticks,
   the depth at the touch and within 5 ticks (median lots, sampled each second), aggressive orders a second and their
   size, the share of time the book is one-sided or empty; and the key numbers: the mid's mean and median move in the
   aggressor's direction 1, 5, 30 and 60 s after an aggressive order (from the mid just after it; `impact` is that
   mid against the one before), split by size at the median, and the same after a move of the mid of at most one
   tick. Positive is momentum (follow the trade), negative is reversion (fade it).
2. **Candidates.** Each prepared bot at its file's defaults on the same data in a process pool (arena.qgrid.run_one),
   with the session's length set from the data (`SESSION_S`, the template's `SESSION_US`): one ranked table of PnL,
   the first 75% / last 25%, max drawdown, fills, volume, |inv| q99.7, the breach penalty and the run time, projected
   to an 8.8M-row round (flagged above ~4 minutes here: the sandbox's 15 minutes on a CPU maybe 2-3x slower).
3. **Next grids** for the top two, as `arena.qgrid` command lines with `--holdout 0.25` (axes from IDEAS.md's family
   rows; `MIN_FLOW`'s values from the profile's trade sizes).

`--out DIR` writes report.txt (all of the above), profile.csv, markouts.csv and candidates.csv.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import json
import os
import statistics
import sys
import tempfile
import time
from array import array
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from arena import qgrid
from experiments.day.family_rust import FAMILY as RIDGE_FAMILY

ROOT = Path(__file__).resolve().parents[3]
HORIZONS_S = (1, 5, 30, 60)
REAL_ROWS = 8_800_000  # a real round's tape (STARTER.md / simulator.iter_backtest's docstring)
FLAG_S = 240  # projected seconds here above which the sandbox's 15 minutes is at risk
FAMILIES = ROOT / "python" / "bots" / "qminers" / "families"
CANDIDATE_DIR = ROOT / "python" / "bots" / "qminers" / "candidates"
TEMPLATE = ROOT / "python" / "bots" / "qminers" / "template.py"
MOMENTUM_PARAMS = {"fair": "mid", "make_inside": 1, "make_edge": 2, "take_edge": 2.5, "make_size": 0, "limit": 100,
                   "lin_momentum": 2, "lin_window": 20, "clear_edge": -1, "flatten_from": 970000}
A0_PARAMS = {"limit": 50, "fair": "mid", "take_edge": 2, "make_edge": 1, "make_inside": 1, "make_size": 5, "flatten_from": 970000}
# name: (bot file, the session global, extra overrides)
CANDIDATES = {
    "runner": (FAMILIES / "momentum_runner.py", "SESSION_S", {}),
    "taker": (FAMILIES / "momentum_taker.py", "SESSION_S", {}),
    "fade": (FAMILIES / "run_fade.py", "SESSION_S", {}),
    "mmaker": (FAMILIES / "momentum_maker.py", "SESSION_S", {}),
    "pmaker": (FAMILIES / "protected_maker.py", "SESSION_S", {}),
    "M1": (CANDIDATE_DIR / "r0_M1_runner.py", "SESSION_S", {}),
    "F1": (CANDIDATE_DIR / "r0_F1_fallback.py", "SESSION_S", {}),
    "tmpl_mom": (TEMPLATE, "SESSION_US", {"PARAMS.ASSET": MOMENTUM_PARAMS}),
    "A0": (TEMPLATE, "SESSION_US", {"PARAMS.ASSET": A0_PARAMS}),
    # Round 1's makers (7 Nov): their files never wind down (SESSION_S 1e9), whatever the private tape's length, so no session is set
    # Round 3's files (data/arena/round3/HANDOVER.md): R3-F5 the final (+888,195 on validation), R3-F3 (+883,559), R3-F4
    # (F3 with the filter's impact chosen online), R3-B1 (F3 without the filter, +733,790: the filter's value on the new tape)
    "R3_F5": (CANDIDATE_DIR / "r3_F5_jump_bar.py", None, {}),
    "R3_F3": (CANDIDATE_DIR / "r3_F3_latent_filter_b1.py", None, {}),
    "R3_F4": (CANDIDATE_DIR / "r3_F4_filter_bank.py", None, {}),
    "R3_B1": (CANDIDATE_DIR / "r3_B1_huber_quote_switch.py", None, {}),
    # Round 2's winners on the server's validation tape (data/arena/round2/HANDOVER.md, "Round 2 results, marked"):
    # the forecast takers first (R2-L3 the final, +804,018), then the composite, the big-order follower, the maker
    "R2_L8": (CANDIDATE_DIR / "r2_L8_quote_switch.py", None, {}),
    "R2_L3": (CANDIDATE_DIR / "r2_L3_taker_pure.py", None, {}),
    "R2_L1": (CANDIDATE_DIR / "r2_L1_taker_liquidity.py", None, {}),
    "R2_H1": (CANDIDATE_DIR / "r2_H1_flow_bias.py", None, {}),
    "R2_T2": (CANDIDATE_DIR / "r2_T2_take_only_safe.py", None, {}),
    "R2_M4": (CANDIDATE_DIR / "r2_M4_flow_window.py", None, {}),
    "R2_V2": (CANDIDATE_DIR / "r2_V2_vol_exposure_dz18.py", None, {}),
    # Round 1's learned makers (the online ridge line; R1-C11 the uploaded final)
    "R1_C11": (CANDIDATE_DIR / "r1_C11_codex_v5_29feat.py", None, {}),
    "R1_C5": (CANDIDATE_DIR / "r1_C5_long_horizon.py", None, {}),
    "R1_C1": (CANDIDATE_DIR / "r1_C1_codex_ridge.py", None, {}),
    "R1_F8": (CANDIDATE_DIR / "r1_F8_take_join.py", None, {}),
    "R1_F7": (CANDIDATE_DIR / "r1_F7_signal.py", None, {}),
    "R1_F6b": (CANDIDATE_DIR / "r1_F6b_alloc.py", None, {}),
    "R1_F6": (CANDIDATE_DIR / "r1_F6_two_levels.py", None, {}),
    "R1_F5": (CANDIDATE_DIR / "r1_F5_shrink_react.py", None, {}),
    "R1_F3": (CANDIDATE_DIR / "r1_F3_full_room.py", None, {}),
    "M2": (CANDIDATE_DIR / "r0_M2_runner_safe.py", "SESSION_S", {}),
}
# The shrink-maker family's grids run on the Rust port (arena.qsim_rust, byte-identical, ~0.5 s a run on 4.4M rows)
RUST_GRIDS = {"R1_F6", "R1_F5", "R1_F3", "R1_F7", "R1_F6b"}
RUST_FAMILY = {"R1_F7": "signal_maker.py", "R1_F6b": "alloc_maker.py"}  # the rest: shrink_maker.py
# The ridge line's grids run on ridge_maker, the Rust twin of R1-C1 whose knobs reproduce R1-C5 (and C1b, C3, C4, C7)
RIDGE_C5 = ("--set POSITION_LIMIT=1000 --set EXPOSURE=100 --set CANCEL_FREE=1.0 --set HEDGE=1"
            " --set MODEL_MEMORY_US=100000000000 --set HORIZON_US=400000 --set DEAD_ZONE=0.18")
RUST_RIDGE = {"R1_C11": RIDGE_C5 + " --set QUOTEFEAT=1 --set FLOWGRP=2 --set FLOWGRP_CAP=1", "R1_C5": RIDGE_C5, "R1_C1": ""}
# R2-V2 (the speed-scaled maker) in ridge_maker: R2-E2's sets with EXPOSURE 100 and the VOL_REF exposure
# Round 3's files in ridge_maker (byte for byte; experiments.day.family_rust's lines)
RUST_RIDGE.update({"R3_F5": RIDGE_FAMILY["F5"], "R3_F3": RIDGE_FAMILY["F3"], "R3_F4": RIDGE_FAMILY["F4"], "R3_B1": RIDGE_FAMILY["B1"]})
RUST_RIDGE["R2_V2"] = ("--set POSITION_LIMIT=1000 --set CANCEL_FREE=1.0 --set HEDGE=1 --set MODEL_MEMORY_US=100000000000"
                       " --set HORIZON_US=400000 --set QUOTEFEAT=1 --set FLOWGRP=2 --set FLOWGRP_CAP=20 --set FLOWGRP_US=1000000"
                       " --set FT_SZ=200 --set FT_GAP_MS=50 --set SKEW_K=0.025 --set FT_EDGE=0.25 --set QUOTE_SIZE=200"
                       " --set DEAD_ZONE=0.18 --set KEEP_LOTS=20 --set KEEP_TH=0.3 --set EXPOSURE=100 --set VOL_REF=2.5"
                       " --set VOL_EXP=2 --set VOL_US=5000000 --set VOL_MIN=10 --set VOL_MAX=100 --set VOL_NOHEDGE=1")


# ---------------------------------------------------------------------------- profile


def data_span_us(path: Path) -> tuple[int, int]:
    """The first and last row's Time in µs, read from the file's head and tail only."""
    with path.open("rb") as f:
        f.readline()
        first = f.readline()
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - 4096))
        tail = [line for line in f.read().splitlines() if line.strip()]
    def ts(line: bytes) -> int:
        return int(round(float(line.split(b",", 1)[0]) * 1_000_000))
    return ts(first), ts(tail[-1])


def profile(data: str) -> dict:
    """Replays the tape through the competition's simulator with a recorder for a feed: the numbers `format_profile` prints."""
    from simulator.simulator import ExchangeSimulator
    from simulator.strategy import BaseStrategy

    rec = {"events": 0, "first": None, "last": 0, "dt": {}, "touch": [], "depth5": [], "prints": 0, "volume": 0}
    mid_t, mid_v = array("q"), array("d")
    tr_t, tr_s, tr_q, tr_m0, tr_pre = array("q"), array("b"), array("l"), array("d"), array("d")
    mv_t, mv_s, mv_m0, mv_trade = array("q"), array("b"), array("d"), array("b")
    state = {"mid": None, "key": None, "last_ts": None, "next_sample": None}

    class Recorder(ExchangeSimulator):
        def _emit_public_snapshot(self) -> None:
            book, ts = self.book, self.current_ts_us
            bp, ap = book._bid_prices, book._ask_prices
            bid = bp[-1] if bp else None
            ask = ap[0] if ap else None
            rec["events"] += 1
            if rec["first"] is None:
                rec["first"] = ts
                state["next_sample"] = ts
            rec["last"] = ts
            last_ts = state["last_ts"]
            if last_ts is not None and ts > last_ts:
                rec["dt"][state["key"]] = rec["dt"].get(state["key"], 0) + ts - last_ts
            state["last_ts"] = ts
            if bid is not None and ask is not None:
                spread = ask - bid
                key = spread if spread < 3 else 3
                mid = (bid + ask) / 2
            else:
                key = "empty" if bid is None and ask is None else "one-sided"
                mid = state["mid"]
            state["key"] = key
            pre = state["mid"]
            trades = self._trades
            if trades:
                self._trades = []
                qty = 0
                for trade in trades:
                    qty += trade.quantity
                rec["prints"] += len(trades)
                rec["volume"] += qty
                if pre is not None and mid is not None:
                    tr_t.append(ts)
                    tr_s.append(1 if trades[0].book_side == "ask" else -1)
                    tr_q.append(qty)
                    tr_m0.append(mid)
                    tr_pre.append(pre)
            if mid is not None and mid != pre:
                mid_t.append(ts)
                mid_v.append(mid)
                if bid is not None and ask is not None and pre is not None and abs(mid - pre) <= 1:
                    mv_t.append(ts)
                    mv_s.append(1 if mid > pre else -1)
                    mv_m0.append(mid)
                    mv_trade.append(1 if trades else 0)
                state["mid"] = mid
            if ts >= state["next_sample"] and bid is not None and ask is not None:
                state["next_sample"] = ts + 1_000_000
                touch = deep = 0  # lots, both sides added (halved below: a side's)
                for prices, levels, best, step in ((bp, book._bids, bid, -1), (ap, book._asks, ask, 1)):
                    for i in (range(len(prices) - 1, -1, -1) if step < 0 else range(len(prices))):
                        price = prices[i]
                        if abs(price - best) > 4:
                            break
                        lots = sum(o.remaining_quantity for o in levels[price].queue)
                        deep += lots
                        if price == best:
                            touch += lots
                rec["touch"].append(touch / 2)
                rec["depth5"].append(deep / 2)

    started = time.perf_counter()
    Recorder(strategy=BaseStrategy(), config=qgrid.config()).run(Path(data))
    replay_s = time.perf_counter() - started

    end = rec["last"]
    sizes = sorted(tr_q)
    median_size = sizes[len(sizes) // 2] if sizes else 0

    def markouts(times, signs, base, keep=None) -> dict:
        out = {}
        for h in HORIZONS_S:
            moves = []
            for i in range(len(times)):
                if keep is not None and not keep(i):
                    continue
                target = times[i] + h * 1_000_000
                if target > end:
                    continue
                j = bisect.bisect_right(mid_t, target) - 1
                moves.append(signs[i] * (mid_v[j] - base[i]))
            out[h] = (statistics.fmean(moves), statistics.median(moves), len(moves)) if moves else (None, None, 0)
        return out

    def impact(keep=None):
        moves = [tr_s[i] * (tr_m0[i] - tr_pre[i]) for i in range(len(tr_t)) if keep is None or keep(i)]
        return (statistics.fmean(moves), statistics.median(moves), len(moves)) if moves else (None, None, 0)

    rows = {
        "trade (all)": (impact(), markouts(tr_t, tr_s, tr_m0)),
        f"trade <= {median_size} lots": (impact(lambda i: tr_q[i] <= median_size),
                                        markouts(tr_t, tr_s, tr_m0, lambda i: tr_q[i] <= median_size)),
        f"trade > {median_size} lots": (impact(lambda i: tr_q[i] > median_size),
                                       markouts(tr_t, tr_s, tr_m0, lambda i: tr_q[i] > median_size)),
        "1-tick mid move": (None, markouts(mv_t, mv_s, mv_m0)),
        "1-tick move, no trade": (None, markouts(mv_t, mv_s, mv_m0, lambda i: not mv_trade[i])),
    }
    total = sum(rec["dt"].values()) or 1

    def pct(q):
        return sizes[min(len(sizes) - 1, int(q * len(sizes)))] if sizes else 0

    return {
        "rows": rec["events"], "first_s": (rec["first"] or 0) / 1e6, "last_s": end / 1e6,
        "length_s": (end - (rec["first"] or 0)) / 1e6, "replay_s": replay_s,
        "spread_share": {str(k): v / total for k, v in rec["dt"].items()},
        "touch_median": statistics.median(rec["touch"]) if rec["touch"] else None,
        "depth5_median": statistics.median(rec["depth5"]) if rec["depth5"] else None,
        "aggressive": len(sizes), "prints": rec["prints"], "volume": rec["volume"],
        "size_median": median_size, "size_p90": pct(0.9), "size_mean": statistics.fmean(sizes) if sizes else None,
        "mid_changes": len(mid_t), "moves_1tick": len(mv_t),
        "markouts": {name: {"impact": imp, **{f"{h}s": v for h, v in m.items()}} for name, (imp, m) in rows.items()},
    }


def _f(x, digits=2) -> str:
    return "-" if x is None else f"{x:+.{digits}f}"


def format_profile(p: dict) -> str:
    length = p["length_s"] or 1
    share = p["spread_share"]
    lines = [
        f"== profile ({p['rows']:,} rows replayed in {p['replay_s']:.1f} s)",
        f"time     {p['first_s']:.3f} .. {p['last_s']:.3f} s, length {p['length_s']:,.1f} s ({p['length_s'] / 3600:.2f} h), "
        f"{p['rows'] / length:,.1f} events/s, {p['mid_changes'] / length:,.2f} mid changes/s",
        "spread   time share " + ", ".join(f"{label} {share.get(key, 0):.1%}" for key, label in
                                           (("1", "1 tick"), ("2", "2 ticks"), ("3", "3+ ticks"), ("one-sided", "one-sided"), ("empty", "empty"))),
        f"depth    median lots a side at the touch {p['touch_median']}, within 5 ticks {p['depth5_median']} (sampled each second)",
        f"trades   {p['aggressive'] / length:.3f} aggressive orders/s ({p['aggressive']:,}; {p['prints']:,} prints, "
        f"{p['volume'] / length:.2f} lots/s); size median {p['size_median']}, p90 {p['size_p90']}, mean {_f(p['size_mean'], 1).lstrip('+')}",
        "markout  the mid's move in ticks in the event's direction (mean / median; + momentum, - reversion), from the mid just after it",
    ]
    header = f"  {'after':<24}{'n':>8}  {'impact':>13}" + "".join(f"{f'{h} s':>15}" for h in HORIZONS_S)
    lines.append(header)
    for name, m in p["markouts"].items():
        imp = m["impact"]
        n = m["1s"][2]
        cells = [f"{_f(imp[0])} / {_f(imp[1], 1)}" if imp and imp[2] else "-"]
        cells += [f"{_f(m[f'{h}s'][0])} / {_f(m[f'{h}s'][1], 1)}" if m[f"{h}s"][2] else "-" for h in HORIZONS_S]
        lines.append(f"  {name:<24}{n:>8,}  {cells[0]:>13}" + "".join(f"{c:>15}" for c in cells[1:]))
    lines.append(verdict(p))
    return "\n".join(lines)


def verdict(p: dict) -> str:
    """One line: which family the markouts point to (a following trader pays about the spread on a round trip)."""
    m = p["markouts"]["trade (all)"]
    five, thirty = m["5s"][0], m["30s"][0]
    share = p["spread_share"]
    spread = sum(int(k) * v for k, v in share.items() if k in ("1", "2", "3")) / max(1e-9, sum(v for k, v in share.items() if k in ("1", "2", "3")))
    if five is None:
        return "verdict  no aggressive trades with a mid 5 s later: make markets (A0, F1, pmaker) and look at the tape by hand"
    if five > spread:
        peak = "keeps going" if thirty is not None and thirty >= five else "gives part back by 30 s (try fade too)"
        return f"verdict  MOMENTUM: +{five:.2f} ticks at 5 s against a mean spread of ~{spread:.1f}; the move {peak}: push the runner / taker"
    if five < -0.25:
        return f"verdict  REVERSION: {five:.2f} ticks at 5 s: fade the trade (run_fade with a short DELAY_MS) and make markets"
    return f"verdict  WEAK ({five:+.2f} ticks at 5 s, mean spread ~{spread:.1f}): following pays no spread; make markets (A0, pmaker, F1)"


# ---------------------------------------------------------------------------- candidates


def timed_run(bot: str, overrides: dict, data: str) -> tuple[qgrid.Run, float]:
    started = time.perf_counter()
    run = qgrid.run_one(bot, overrides, data)
    return run, time.perf_counter() - started


def candidate_overrides(name: str, length_us: int) -> dict:
    _, session, extra = CANDIDATES[name]
    if session is None:
        return dict(extra)
    value = max(1, -(-length_us // 1_000_000)) if session == "SESSION_S" else max(1, length_us)
    return {**extra, session: value}


def rank(results: dict, rows: int) -> list[dict]:
    table = []
    for name, (run, seconds) in results.items():
        first, last = qgrid.split_at(run.curve, 0.25)
        projected = seconds * REAL_ROWS / max(1, rows)
        table.append({"candidate": name, "bot": str(CANDIDATES[name][0].relative_to(ROOT)), "pnl": run.pnl, "first75": first,
                      "last25": last, "max_dd": qgrid.max_drawdown([v for _, v in run.curve]), "fills": run.fills,
                      "volume": run.traded_volume, "inv_q997": run.inventory_q997, "breach": run.breach_penalty,
                      "rejected": run.rejected, "run_s": seconds, "proj_s": projected, "slow": projected > FLAG_S, "error": run.error})
    table.sort(key=lambda r: (r["error"] is not None, -r["pnl"]))
    return table


def format_table(table: list[dict], rows: int) -> str:
    header = ["#", "candidate", "pnl", "first 75%", "last 25%", "max dd", "fills", "volume", "|inv| q997", "breach", "rej",
              "run s", f"s @{REAL_ROWS / 1e6:.1f}M", ""]
    out = []
    for i, r in enumerate(table, 1):
        if r["error"]:
            out.append([str(i), r["candidate"]] + [""] * (len(header) - 3) + [f"! {r['error']}"])
            continue
        flags = ("SLOW " if r["slow"] else "") + ("BREACH" if r["breach"] > 0 else "")
        out.append([str(i), r["candidate"], f"{r['pnl']:,.0f}", f"{r['first75']:,.0f}", f"{r['last25']:,.0f}", f"{r['max_dd']:,.0f}",
                    f"{r['fills']:,}", f"{r['volume']:,}", str(r["inv_q997"]), f"{r['breach']:,.0f}", str(r["rejected"]),
                    f"{r['run_s']:.1f}", f"{r['proj_s']:,.0f}", flags.strip()])
    widths = [max(len(c[i]) for c in [header, *out]) for i in range(len(header))]
    lines = [f"== candidates (each at its file's defaults, the session set to the data's length; {rows:,} rows)"]
    lines += ["  ".join(c.ljust(w) if i == 1 else c.rjust(w) for i, (c, w) in enumerate(zip(cells, widths))).rstrip() for cells in [header, *out]]
    lines.append(f"run s: wall time in the pool (contention inflates it); s @{REAL_ROWS / 1e6:.1f}M: projected to a real round's rows; "
                 f"SLOW: over {FLAG_S} s here, at risk in the sandbox's 15 minutes on a 2-3x slower CPU")
    return "\n".join(lines)


def flow_values(p: dict | None) -> str:
    if not p or not p["size_median"]:
        return "1,2,5,10"
    med, p90 = p["size_median"], p["size_p90"]
    return ",".join(str(v) for v in sorted({1, med, p90, 2 * p90}))


def next_grids(table: list[dict], p: dict | None, data: Path, length_us: int, jobs: int) -> str:
    flow = flow_values(p)
    axes = {
        "runner": [f"--grid MIN_FLOW={flow} --grid TRAIL_TICKS=2,3,5 --grid MAX_POS=50,100 --set FLOW_ENTRY=1",
                   "--grid MOVE_TICKS=0,2,4 --grid LOOKBACK=5,20 --grid FLOW_ENTRY=0,1 --grid TRAIL_TICKS=3,5"],
        "taker": [f"--grid MIN_FLOW={flow} --grid SIZE=20,40 --grid HOLD_MS=2000,4000,6000 --grid MAX_POS=50,90 --grid WINDOW_MS=0,1000"],
        "fade": [f"--grid DELAY_MS=1000,2000,4000,6000 --grid RUN_TICKS=2,4,8 --grid HOLD_MS=4000,10000 --grid MIN_FLOW={flow}"],
        "mmaker": [f"--grid WINDOW_MS=500,2000 --grid SIGNAL_MS=1000,3000,6000 --grid IMPROVE=0,1 --grid MIN_FLOW={flow}"],
        "pmaker": ["--grid PULL_MS=0,500,2000,6000 --grid OFFSET=-1,0,1 --grid QUOTE=5,10 --grid PULL_SIDE=0,1"],
        "F1": ["--grid QUOTE=2,5,10 --grid SKEW=10,20,40"],
        "tmpl_mom": ["--grid PARAMS.ASSET.take_edge=1.5,2.5,3.5 --grid PARAMS.ASSET.lin_window=10,20,40 --grid PARAMS.ASSET.lin_momentum=1,2,3"],
        "A0": ["--grid PARAMS.ASSET.make_edge=0,1,2 --grid PARAMS.ASSET.make_size=2,5,10 --grid PARAMS.ASSET.take_edge=1,2,3"],
    }
    axes["M1"] = axes["runner"]
    axes["M2"] = axes["runner"] + ["--grid MAX_SPREAD=1,2,3 --grid FLOW_WINDOW_MS=0,500,2000 --grid MAX_POS=30,100"]
    shrink = ["--grid LEVELS=1,2 --grid KEEP_DEPTH=1,2 --grid SIZE_TOUCH=65,100,200 --grid SIZE_DEEP=50,80 --grid DEPLETE_LOTS=0,70,100,150 --grid DEPL_FRAC=0.06,0.12 --grid REACT_CANCEL=0,1"]
    for name in ("R1_F6", "R1_F5", "R1_F3"):
        axes[name] = shrink
    axes["R1_F6b"] = ["--grid ALLOC_K=-0.75,-0.5,-0.25,0 --grid SIZE_TOUCH=65,100,115 --grid DEPLETE_LOTS=70,100"]
    ridge = ["--grid HORIZON_US=100000,250000,400000,600000 --grid DEAD_ZONE=0.1,0.14,0.18,0.22,0.26 --grid INSIDE_TH=0.2,0.3,0.4"]
    for name in RUST_RIDGE:
        axes[name] = ridge
    # the round-2 takers: their forecast settings are class constants (edit the file to change them); the module knobs here
    # round 3's: the filter's impact scale (x2 won on round 2's tape, x3 on round 3's), the take bar and F5's jump rule
    for name in ("R3_F5", "R3_F3"):
        axes[name] = ["--grid FILTER_IMPACT=2,2.5,3 --grid FT_EDGE=0.15,0.2,0.25 --grid FT_JUMP=0,3"]
    axes["R3_F4"] = ["--grid FILTER_IMP2=0,1.5,2 --grid FT_EDGE=0.15,0.25"]
    axes["R3_B1"] = ["--grid QS_RATE=1.5,2.5,3.5 --grid FT_EDGE=0.15,0.25"]
    axes["R2_L8"] = ["--grid QS_RATE=1.5,2.5,3.5 --grid TAKE_MAXSPREAD=1,2"]
    for name in ("R2_L3", "R2_L1", "R2_T2"):
        axes[name] = ["--grid TAKE_MAXSPREAD=1,2"]
    axes["R2_H1"] = ["--grid BIAS_AGREE=0.15,0.3,0.45 --grid FLOW_MS=125,250 --grid MIN_LOTS=500,575"]
    axes["R2_M4"] = ["--grid FLOW_MS=100,125,150 --grid MIN_LOTS=500,575,650"]
    axes["R1_F8"] = ["--grid TAKE_LOTS=0,30,60 --grid TAKE_OWN=400,800 --grid JOIN_OWN=0,400 --grid ALLOC_K=-0.5,0"]
    axes["R1_F7"] = ["--grid MOM_JOIN=0,1 --grid MOM_LOTS=200,400,800 --grid MOM_MS=20,50,200 --grid DYING_DEEP=0,80 --grid DEPL_FRAC=0.06,0.12"]
    lines = ["== next grids (the top two by PnL)"]
    chosen, seen = [], set()
    for r in table:  # the top two with different axes (M1 is the runner at its defaults)
        key = tuple(axes[r["candidate"]])
        if not r["error"] and key not in seen and len(chosen) < 2:
            chosen.append(r)
            seen.add(key)
    for r in chosen:
        name = r["candidate"]
        sets = " ".join(f"--set '{k}={json.dumps(v) if isinstance(v, dict) else v}'" for k, v in candidate_overrides(name, length_us).items())
        for grid in axes[name]:
            if name in RUST_RIDGE:  # ridge_maker: its knobs reproduce R1-C1, R1-C5 and R1-C11 byte for byte
                lines.append(f"uv run python -m arena.qsim_rust ridge_maker {data} {RUST_RIDGE[name]} {grid} --holdout 0.25 --threads {jobs} --sort holdout")
            elif name == "R1_F8":  # take_maker, R1-F8's twin
                lines.append(f"uv run python -m arena.qsim_rust {r['bot']} {data} {grid} --holdout 0.25 --threads {jobs} --sort holdout")
            elif name in RUST_GRIDS:  # the Rust port of the shrink maker, the same results ~70x faster
                family = RUST_FAMILY.get(name, "shrink_maker.py")
                lines.append(f"uv run python -m arena.qsim_rust python/bots/qminers/families/{family} {data} --set SESSION_S=1000000000 {grid} --holdout 0.25 --threads {jobs} --sort holdout")
            else:
                lines.append(f"uv run python -m arena.qgrid {r['bot']} {data} {sets} {grid} --holdout 0.25 --jobs {jobs} --sort holdout")
    return "\n".join(lines)


# ---------------------------------------------------------------------------- CLI


def write_outputs(out: Path, report: str, p: dict | None, table: list[dict]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.txt").write_text(report + "\n", encoding="utf-8")
    if p:
        with (out / "profile.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["metric", "value"])
            for k, v in p.items():
                if k == "markouts":
                    continue
                if isinstance(v, dict):
                    for kk, vv in v.items():
                        w.writerow([f"{k}:{kk}", vv])
                else:
                    w.writerow([k, v])
        with (out / "markouts.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["after", "horizon", "mean_ticks", "median_ticks", "n"])
            for name, m in p["markouts"].items():
                for h, v in m.items():
                    if v:
                        w.writerow([name, h, *v])
    if table:
        with (out / "candidates.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(table[0]))
            w.writeheader()
            w.writerows(table)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="experiments.day.round_start", description=__doc__.split("\n\n")[0])
    parser.add_argument("data", type=Path, help="the round's backtest CSV in the starter's format (.csv or .csv.gz)")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--out", type=Path, help="write report.txt, profile.csv, markouts.csv, candidates.csv here")
    parser.add_argument("--candidates", default=",".join(CANDIDATES),
                        help=f"comma-separated, of {','.join(CANDIDATES)} (default all; empty: the profile only)")
    parser.add_argument("--no-profile", action="store_true", help="skip the profile (the candidates only)")
    args = parser.parse_args(argv)
    if not args.data.exists():
        parser.error(f"no such data file: {args.data}")
    args.names = [n for n in args.candidates.split(",") if n]
    unknown = [n for n in args.names if n not in CANDIDATES]
    if unknown:
        parser.error(f"unknown candidates {unknown}; choose from {list(CANDIDATES)}")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="round_start_") as scratch:
        plain = qgrid.plain_csv([args.data], Path(scratch))[0]
        first_us, last_us = data_span_us(plain)
        length_us = last_us - first_us
        tasks = {name: (str(CANDIDATES[name][0]), candidate_overrides(name, length_us), str(plain)) for name in args.names}
        print(f"{args.data}: {length_us / 1e6:,.1f} s of tape; profile + {len(tasks)} candidates on {args.jobs} jobs", file=sys.stderr)
        p, results = None, {}
        if args.jobs <= 1:
            p = None if args.no_profile else profile(str(plain))
            results = {name: timed_run(*task) for name, task in tasks.items()}
        else:
            with ProcessPoolExecutor(max_workers=args.jobs) as pool:
                fp = None if args.no_profile else pool.submit(profile, str(plain))
                futures = {name: pool.submit(timed_run, *task) for name, task in tasks.items()}
                if fp is not None:
                    p = fp.result()
                    print(format_profile(p), flush=True)
                results = {name: f.result() for name, f in futures.items()}
    parts = []
    if p:
        parts.append(format_profile(p))
        if args.jobs <= 1:
            print(parts[-1], flush=True)
    rows = p["rows"] if p else sum(1 for _ in qgrid_lines(args.data))
    table = rank(results, rows)
    if table:
        parts += ["", format_table(table, rows), "", next_grids(table, p, args.data, length_us, args.jobs)]
        print("\n".join(parts[-4:]))
    parts.append(f"\ndone in {time.perf_counter() - started:.1f} s")
    print(parts[-1].strip())
    if args.out:
        write_outputs(args.out, "\n".join(parts), p, table)
        print(f"wrote {args.out}/report.txt, profile.csv, markouts.csv, candidates.csv")
    return 0


def qgrid_lines(path: Path):
    """The data rows (for the run-time projection when the profile is skipped)."""
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt") as f:
        next(f, None)
        yield from f


if __name__ == "__main__":
    sys.exit(main())
