"""Where a forecast taker loses on a tape (8 Nov, round 3, R3-F3): its worst seconds and its worst takes, and what
precedes them, to find a guard rule.

Inputs: a full-logs run of the Arena simulator (`exchange-simulator --strategy FILE --backtest TAPE --log-dir DIR`,
no --no-logs: trades.csv and pnl.csv), optionally the Rust twin's RIDGE_PRED_LOG of the same bot on the same tape
(each book event's time, mid, prediction, skew, spread, inventory; byte-identical runs, so the takes line up), and
the tape with experiments.day.r3_edges' cache (the 0.1-s grid, gen_identify's regimes and jumps, the latent filter's
50-ms samples: gap and posterior sd). A second replay of the tape (tape_book) reads the market's lots at the touch a
take hits, just before it.

- **Takes**: our IOC orders (we are the taker), grouped by order: time, side, lots, average price. Markout at 1 / 5 s:
  (mid h s later - price) * side, ticks a lot and in all. Per take, just before it: the spread, the filter's gap our
  way and its sd, the forecast (prediction - skew) our way, our position our way, the seconds since the last jump
  (3+ ticks), the inserts' width over 0.5 s, the regime, and the take's lots over the market's lots at the touch.
- **Seconds**: the PnL's 1-s changes; for the worst 1% and 5% the same features at the second's start against all
  seconds, the share with a take in the second or the one before, and the part a mark-to-market of the position
  explains (position * the mid's change).
- **Tables**: the markout per lot by bins of each feature, and the counterfactual "skip the takes in this bin" (the
  bin's total 5-s markout: what a guard would have saved, path effects ignored).

    uv run python -m experiments.day.loss_anatomy RUN_DIR TAPE --cache R3.npz [--pred pred.csv] [--json OUT.json]
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

import numpy as np

from experiments.day import gen_identify as gi
from experiments.day import r3_edges as E
from experiments.day.tape_book import Book

H = (1.0, 5.0)


def r(x, n=3):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), n)


def our_takes(trades: Path) -> dict:
    """Our taker orders from trades.csv: first fill time (s), side +1 buy, lots, average price."""
    acc = {}
    with trades.open() as fh:
        for row in csv.DictReader(fh):
            if row["taker_owner"] != "user":
                continue
            oid = row["taker_order_id"]
            q, p = int(row["quantity"]), int(row["price"])
            if oid not in acc:
                acc[oid] = [int(row["timestamp_us"]) / 1e6, 1 if row["taker_side"] == "B" else -1, 0, 0.0]
            acc[oid][2] += q
            acc[oid][3] += q * p
    rows = sorted(acc.values())
    t = np.array([a[0] for a in rows])
    return {"t": t, "side": np.array([a[1] for a in rows], dtype=float), "lots": np.array([a[2] for a in rows], dtype=float),
            "price": np.array([a[3] / a[2] for a in rows])}


def touch_depth(csv_path: Path, times: np.ndarray, sides: np.ndarray) -> np.ndarray:
    """The market's lots at the touch a take at each time hits (the ask for a buy), from a replay of the tape."""
    order = np.argsort(times)
    out = np.zeros(len(times))
    book = Book()
    k = 0
    with csv_path.open() as fh:
        next(fh)
        for line in fh:
            t, op, oid, side, vol, price, life = line.rstrip("\n").split(",")
            t = float(t)
            while k < len(order) and times[order[k]] <= t:
                i = order[k]
                bb, ba = book.best
                px = ba if sides[i] > 0 else bb
                out[i] = book.depth(1 if sides[i] > 0 else 0, px) if px is not None else 0
                k += 1
            if op == "Insert":
                book.insert(oid, 0 if side == "B" else 1, int(price), int(vol), life == "F")
            else:
                book.cancel(oid)
            if k >= len(order):
                break
    return out


def bins_table(x: np.ndarray, edges, mk1: np.ndarray, mk5: np.ndarray, lots: np.ndarray) -> list:
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (x >= lo) & (x < hi) & ~np.isnan(x)
        if not m.any():
            continue
        out.append({"bin": f"[{lo:g},{hi:g})", "takes": int(m.sum()), "lots": int(lots[m].sum()),
                    "mk1_per_lot": r(mk1[m].sum() / lots[m].sum()), "mk5_per_lot": r(mk5[m].sum() / lots[m].sum()),
                    "mk5_total": r(mk5[m].sum(), 0)})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run", type=Path)
    ap.add_argument("tape", type=Path)
    ap.add_argument("--cache", type=Path, required=True)
    ap.add_argument("--pred", type=Path)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    cx = E.Ctx(a.tape, a.cache)
    tp = cx.tp
    tk = our_takes(a.run / "trades.csv")
    t, sd_, lots, price = tk["t"], tk["side"], tk["lots"], tk["price"]
    pre = t - 0.006  # the book the bot saw: the order went out 5 ms before its fill
    mk = {}
    for h in H:
        mk[h] = np.nan_to_num((cx.mid_at(t + h) - price) * sd_ * lots)  # an invalid book's NaN mid counts 0
    rows = cx.rows
    k = np.clip(np.searchsorted(rows[:, 0], pre) - 1, 0, len(rows) - 1)
    feats = {"spread": tp.at(tp.spread_g, pre), "gap_our_way": rows[k, 2] * sd_, "filter_sd": rows[k, 3]}
    since = pre - np.r_[-1e9, cx.t0][np.searchsorted(cx.t0, pre)]
    feats["since_jump_s"] = np.minimum(since, 999.0)
    eb, _ = gi.win_mean(tp.pb, tp.tb, pre - 0.5, pre)
    ea, _ = gi.win_mean(tp.pa, tp.ta, pre - 0.5, pre)
    feats["insert_width"] = ea - eb
    feats["volatile"] = cx.regime_at(pre).astype(float)
    if a.pred is not None:
        pr = np.loadtxt(a.pred, delimiter=",")
        pt = pr[:, 0] / 1e6
        j = np.clip(np.searchsorted(pt, pre, "right") - 1, 0, len(pt) - 1)
        feats["forecast_our_way"] = (pr[j, 2] - pr[j, 3]) * sd_
        feats["position_our_way_before"] = pr[j, 5] * sd_
    depth = touch_depth(a.tape, pre, sd_)
    feats["lots_over_touch"] = lots / np.maximum(depth, 1)
    feats["lots"] = lots
    n = len(t)
    res = {"takes": n, "lots": int(lots.sum()), "mk1_per_lot": r(mk[1.0].sum() / lots.sum()), "mk5_per_lot": r(mk[5.0].sum() / lots.sum()),
           "mk1_total": r(mk[1.0].sum(), 0), "mk5_total": r(mk[5.0].sum(), 0)}
    per_lot5 = mk[5.0] / lots
    worst = {}
    for q in (0.01, 0.05):
        cut = np.quantile(mk[5.0], q)
        w = mk[5.0] <= cut
        cutl = np.quantile(per_lot5, q)
        wl = per_lot5 <= cutl
        worst[f"worst_{q:g}_by_total"] = {"takes": int(w.sum()), "mk5_total": r(mk[5.0][w].sum(), 0),
                                          **{f: r(np.nanmean(v[w])) for f, v in feats.items()}}
        worst[f"worst_{q:g}_by_per_lot"] = {"takes": int(wl.sum()), "mk5_total": r(mk[5.0][wl].sum(), 0),
                                            **{f: r(np.nanmean(v[wl])) for f, v in feats.items()}}
    worst["all"] = {f: r(np.nanmean(v)) for f, v in feats.items()}
    res["worst_takes"] = worst
    edges = {"spread": [1, 2, 3, 99], "gap_our_way": [-99, -1, 0, 0.5, 1, 2, 3, 99], "filter_sd": [0, 0.3, 0.5, 0.7, 1, 1.5, 99],
             "since_jump_s": [0, 1, 3, 10, 30, 100, 1000], "insert_width": [-99, 2, 3, 4, 5, 6, 99], "volatile": [-1, 0, 1, 2],
             "forecast_our_way": [0, 0.8, 1, 1.5, 2, 3, 99], "position_our_way_before": [-200, -50, 0, 1, 50, 200],
             "lots_over_touch": [0, 0.25, 0.5, 1, 2, 4, 1e9], "lots": [0, 10, 30, 60, 100, 1000]}
    res["by_feature"] = {f: bins_table(feats[f], edges[f], mk[1.0], mk[5.0], lots) for f in feats if f in edges}
    # seconds
    pnl = np.loadtxt(a.run / "pnl.csv", delimiter=",", skiprows=1)
    d = np.diff(pnl[:, 1])
    s0 = pnl[:-1, 0]
    take_sec = np.zeros(len(d), bool)
    ti = np.floor(t).astype(int)
    take_sec[np.clip(ti, 0, len(d) - 1)] = True
    take_recent = take_sec | np.r_[False, take_sec[:-1]]
    sf = {"spread": tp.at(tp.spread_g, s0 + 0.001), "abs_gap": np.abs(rows[np.clip(np.searchsorted(rows[:, 0], s0) - 1, 0, len(rows) - 1), 2]),
          "filter_sd": rows[np.clip(np.searchsorted(rows[:, 0], s0) - 1, 0, len(rows) - 1), 3],
          "since_jump_s": np.minimum(s0 - np.r_[-1e9, cx.t0][np.searchsorted(cx.t0, s0)], 999.0),
          "volatile": cx.regime_at(s0 + 0.5).astype(float), "take_in_this_or_last_s": take_recent.astype(float)}
    eb, _ = gi.win_mean(tp.pb, tp.tb, s0 - 0.5, s0)
    ea, _ = gi.win_mean(tp.pa, tp.ta, s0 - 0.5, s0)
    sf["insert_width"] = ea - eb
    dm = cx.mid_at(s0 + 1) - cx.mid_at(s0)
    if a.pred is not None:
        j = np.clip(np.searchsorted(pt, s0, "right") - 1, 0, len(pt) - 1)
        inv = pr[j, 5]
        sf["abs_position"] = np.abs(inv)
        mtm = inv * dm
    secs = {"seconds": int(len(d)), "pnl": r(d.sum(), 0)}
    for q in (0.01, 0.05):
        cut = np.quantile(d, q)
        w = d <= cut
        row = {"seconds": int(w.sum()), "pnl": r(d[w].sum(), 0), "share_of_total": r(d[w].sum() / d.sum(), 3),
               **{f: r(np.nanmean(v[w])) for f, v in sf.items()}, "abs_mid_move_1s": r(np.nanmean(np.abs(dm[w])))}
        if a.pred is not None:
            row["mark_to_market_part"] = r(np.nansum(mtm[w]) / d[w].sum(), 3)
        secs[f"worst_{q:g}"] = row
    secs["all"] = {**{f: r(np.nanmean(v)) for f, v in sf.items()}, "abs_mid_move_1s": r(np.nanmean(np.abs(dm)))}
    if a.pred is not None:
        secs["all"]["mark_to_market_part"] = r(np.nansum(mtm) / d.sum(), 3)
    res["worst_seconds"] = secs
    if a.pred is not None:
        # the position's mark-to-market over the next 1 / 5 s by the state at the second's start: a state where it
        # loses on average is one to hold less in
        dm5 = cx.mid_at(s0 + 5) - cx.mid_at(s0)
        m1, m5 = np.nan_to_num(inv * dm), np.nan_to_num(inv * dm5)
        sedges = {"insert_width": [-99, 2, 3, 4, 5, 6, 99], "spread": [1, 2, 3, 99], "since_jump_s": [0, 1, 3, 10, 30, 100, 1000],
                  "filter_sd": [0, 0.3, 0.5, 0.7, 1, 99], "abs_gap": [0, 0.5, 1, 2, 99], "volatile": [-1, 0, 1, 2]}
        mt = {}
        for f, ed in sedges.items():
            x = sf[f]
            rows_ = []
            for lo, hi in zip(ed[:-1], ed[1:]):
                m = (x >= lo) & (x < hi)
                if m.any():
                    rows_.append({"bin": f"[{lo:g},{hi:g})", "seconds": int(m.sum()), "mtm_1s_mean": r(m1[m].mean(), 1),
                                  "mtm_5s_mean": r(m5[m].mean(), 1), "pnl_1s_mean": r(d[m].mean(), 1)})
            mt[f] = rows_
        # the filter's gap and the forecast at the second's start, signed by the position
        gs = rows[np.clip(np.searchsorted(rows[:, 0], s0) - 1, 0, len(rows) - 1), 2]
        fc = pr[j, 2] - pr[j, 3]
        for name, x in (("gap_with_position", gs * np.sign(inv)), ("forecast_with_position", fc * np.sign(inv))):
            rows_ = []
            for lo, hi in zip([-99, -1, -0.3, 0, 0.3, 1], [-1, -0.3, 0, 0.3, 1, 99]):
                m = (x >= lo) & (x < hi) & (inv != 0)
                if m.any():
                    rows_.append({"bin": f"[{lo:g},{hi:g})", "seconds": int(m.sum()), "mtm_1s_mean": r(m1[m].mean(), 1),
                                  "mtm_5s_mean": r(m5[m].mean(), 1), "pnl_1s_mean": r(d[m].mean(), 1)})
            mt[name] = rows_
        res["position_mtm_by_state"] = mt
    gi.show(res)
    if a.json:
        a.json.write_text(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
