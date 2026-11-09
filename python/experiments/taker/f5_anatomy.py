"""Where a forecast taker (R3-F5) earns and loses on a tape, against the market mid (8 Nov, round 4).

Input: a full-logs run of the Arena simulator (`exchange-simulator --strategy FILE --backtest TAPE --log-dir DIR`, no
--no-logs: trades.csv, book_deltas.csv, pnl.csv, result.json); optionally the Rust twin's RIDGE_PRED_LOG of the same
bot on the same tape with RIDGE_PRED_EXTRA set (time_us, mid, prediction, skew, spread, inventory, filter gap, speed),
used only for its speed column.

The mid is the market's own book (book_deltas rows owned by `market`, our orders left out). Each fill is marked against
the mid just before it (the last book state with an earlier timestamp); the position is built from the fills by time.
Then, exactly, cash + position * last mid = sum of the fills' edges (q * (mid before - price): the spread paid on takes,
earned on passive fills) + sum of position * each mid change (the position's moves). The simulator's PnL differs by
the final position times (its book-walking mark - the last mid), printed.

Every contribution (an edge at its fill's time, a move at its mid change) is then binned by time:
- **regime**: 60-s blocks of the realised variance of 1-s mid changes, split at the median (calm / volatile);
- **speed**: the pred log's speed column on a 1-s grid, terciles over seconds;
- **jumps**: onsets of a 3+ tick mid move within 0.2 s (detections within 1 s merged); each contribution goes to
  [0,1) or [1,10) s after the last onset, else [-3,0) before the next, else [10,30) after, else away;
- **first 1,000 s**: mid PnL and the simulator's PnL per 1,000-s block.
Takes (we are the taker) by the market spread just before: lots, the spread paid a lot, the 1-s and 5-s markout.
Holding: episodes from flat (or a sign flip) to flat (or the next flip); each episode's PnL (a flip fill's edge split by
the lots closing and opening); PnL by holding time; whipsaws: episodes ended by a flip within 1 / 2 s of starting.

    uv run python -m experiments.taker.f5_anatomy LOGDIR [--pred PREDLOG] [--json OUT.json]
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

US = 1_000_000


def market_mid(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The market's touch from book_deltas.csv: (time_us, mid, spread) at each timestamp where the touch changed."""
    vol = ({}, {})  # 0 bids, 1 asks: price -> lots
    best = [None, None]
    ts, mids, spreads = [], [], []
    last = (None, None)
    cur_t = None

    def flush(t):
        nonlocal last
        b, a = best
        if (b, a) != last and b is not None and a is not None:
            ts.append(t)
            mids.append((b + a) / 2)
            spreads.append(a - b)
            last = (b, a)

    with path.open() as f:
        r = csv.reader(f)
        next(r)
        for t, side, price, owner, dq in r:
            if owner != "market":
                continue
            t = int(t)
            if t != cur_t:
                if cur_t is not None:
                    flush(cur_t)
                cur_t = t
            s = 0 if side == "B" else 1
            p = int(price)
            v = vol[s]
            nv = v.get(p, 0) + int(dq)
            if nv > 0:
                v[p] = nv
                if best[s] is None or (p > best[s] if s == 0 else p < best[s]):
                    best[s] = p
            else:
                v.pop(p, None)
                if p == best[s]:
                    best[s] = (max(v) if s == 0 else min(v)) if v else None
    if cur_t is not None:
        flush(cur_t)
    return np.array(ts, dtype=np.int64), np.array(mids), np.array(spreads, dtype=np.int64)


def our_fills(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(time_us, signed lots, price, is_take) for our fills, in file order."""
    t, q, p, take = [], [], [], []
    with path.open() as f:
        r = csv.DictReader(f)
        for row in r:
            tk, mk = row["taker_owner"], row["maker_owner"]
            if tk != "user" and mk != "user":
                continue
            sign = 1 if row["taker_side"] == "B" else -1
            if mk == "user":
                sign = -sign
            t.append(int(row["timestamp_us"]))
            q.append(sign * int(row["quantity"]))
            p.append(int(row["price"]))
            take.append(tk == "user")
    return np.array(t, dtype=np.int64), np.array(q, dtype=np.int64), np.array(p, dtype=np.int64), np.array(take)


def load_pred(path: Path) -> np.ndarray:
    raw = np.fromstring(path.read_text().replace("\n", ","), sep=",")
    return raw[: len(raw) // 8 * 8].reshape(-1, 8)


def on_grid(t: np.ndarray, x: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """x's last value at or before each grid time (NaN before the first)."""
    i = np.searchsorted(t, grid, "right") - 1
    out = np.where(i >= 0, x[np.maximum(i, 0)], np.nan)
    return out


def jump_onsets(tm: np.ndarray, mm: np.ndarray, size: float = 3.0, win_us: int = 200_000, merge_us: int = US) -> np.ndarray:
    j = np.searchsorted(tm, tm - win_us, "right") - 1
    ok = j >= 0
    move = np.zeros_like(mm)
    move[ok] = mm[ok] - mm[j[ok]]
    det = tm[np.abs(move) >= size]
    onsets = []
    lastd = None
    for t in det:
        if lastd is None or t - lastd > merge_us:
            onsets.append(t)
        lastd = t
    return np.array(onsets, dtype=np.int64)


def analyse(logdir: Path, pred: Path | None) -> dict:
    tm, mm, sm = market_mid(logdir / "book_deltas.csv")
    tf, q, p, take = our_fills(logdir / "trades.csv")
    order = np.argsort(tf, kind="stable")
    tf, q, p, take = tf[order], q[order], p[order], take[order]
    res = json.loads((logdir / "result.json").read_text())
    end_us = int(np.ceil(max(tm[-1], tf[-1]) / US)) * US

    # edges against the mid just before each fill
    ib = np.searchsorted(tm, tf, "left") - 1
    mid_b = mm[np.maximum(ib, 0)]
    spr_b = sm[np.maximum(ib, 0)]
    edge = q * (mid_b - p)
    # the position's moves: pos after all fills at or before each mid change
    cumq = np.cumsum(q)
    k = np.arange(1, len(tm))
    fi = np.searchsorted(tf, tm[k], "right") - 1
    pos_k = np.where(fi >= 0, cumq[np.maximum(fi, 0)], 0)
    move = pos_k * np.diff(mm)
    cash = float(-(q * p).sum())
    pos_end = int(cumq[-1])
    mid_pnl = cash + pos_end * mm[-1]
    out = {
        "sim_pnl": res["pnl"], "cash": cash, "sim_cash": res.get("cash"), "pos_end": pos_end, "last_mid": float(mm[-1]),
        "mid_pnl": mid_pnl, "check": float(edge.sum() + move.sum() - mid_pnl),
        "mark_diff": res["pnl"] - mid_pnl,
        "takes": {"fills": int(take.sum()), "lots": int(np.abs(q[take]).sum()), "edge": float(edge[take].sum())},
        "passive": {"fills": int((~take).sum()), "lots": int(np.abs(q[~take]).sum()), "edge": float(edge[~take].sum())},
        "moves": float(move.sum()),
    }

    # every contribution on one time axis
    ct = np.concatenate([tf, tm[k]])
    cv = np.concatenate([edge.astype(float), move.astype(float)])
    ck = np.concatenate([np.where(take, 0, 1), np.full(len(k), 2)])  # 0 take edge, 1 passive edge, 2 move

    def split(mask_list, names):
        rows = {}
        for name, m in zip(names, mask_list):
            rows[name] = {"pnl": float(cv[m].sum()), "take_edge": float(cv[m & (ck == 0)].sum()),
                          "passive_edge": float(cv[m & (ck == 1)].sum()), "moves": float(cv[m & (ck == 2)].sum())}
        return rows

    # regime: 60-s blocks of realised 1-s variance, median split
    grid = np.arange(0, end_us + 1, US)
    mg = on_grid(tm, mm, grid)
    d1 = np.diff(mg)
    d1 = np.where(np.isnan(d1), 0.0, d1)
    nb = len(d1) // 60
    rv = (d1[: nb * 60] ** 2).reshape(nb, 60).sum(1)
    med = float(np.median(rv))
    blk = np.minimum(ct // (60 * US), nb - 1)
    vol_blk = rv[blk] > med
    out["regime"] = split([~vol_blk, vol_blk], ["calm", "volatile"])
    out["regime_rv_median"] = med
    out["regime_1s_sd"] = {"calm": float(np.sqrt(rv[rv <= med].sum() / (60 * (rv <= med).sum()))),
                           "volatile": float(np.sqrt(rv[rv > med].sum() / (60 * (rv > med).sum())))}

    # speed terciles from the pred log
    if pred is not None:
        pl = load_pred(pred)
        sp = on_grid(pl[:, 0].astype(np.int64), pl[:, 7], grid[:-1])
        cut = np.nanquantile(sp, [1 / 3, 2 / 3])
        sec = np.minimum(ct // US, len(sp) - 1)
        s = sp[sec]
        masks = [np.isnan(s), s <= cut[0], (s > cut[0]) & (s <= cut[1]), s > cut[1]]
        out["speed_cuts"] = [float(c) for c in cut]
        out["speed"] = split(masks, ["none", "slow", "mid", "fast"])

    # jumps
    on = jump_onsets(tm, mm)
    out["jumps"] = {"onsets": int(len(on))}
    ia = np.searchsorted(on, ct, "right") - 1
    after = np.where(ia >= 0, ct - on[np.maximum(ia, 0)], 10**15)
    inx = np.searchsorted(on, ct, "right")
    before = np.where(inx < len(on), on[np.minimum(inx, len(on) - 1)] - ct, 10**15)
    w01 = after < US
    w110 = ~w01 & (after < 10 * US)
    wm3 = ~w01 & ~w110 & (before <= 3 * US)
    w1030 = ~w01 & ~w110 & ~wm3 & (after < 30 * US)
    away = ~(w01 | w110 | wm3 | w1030)
    out["jump_windows"] = split([wm3, w01, w110, w1030, away], ["[-3,0)", "[0,1)", "[1,10)", "[10,30)", "away"])
    # time share of each window, on a 10-ms grid
    g = np.arange(0, end_us, 10_000)
    ia = np.searchsorted(on, g, "right") - 1
    ga = np.where(ia >= 0, g - on[np.maximum(ia, 0)], 10**15)
    inx = np.searchsorted(on, g, "right")
    gb = np.where(inx < len(on), on[np.minimum(inx, len(on) - 1)] - g, 10**15)
    a01 = ga < US
    a110 = ~a01 & (ga < 10 * US)
    am3 = ~a01 & ~a110 & (gb <= 3 * US)
    a1030 = ~a01 & ~a110 & ~am3 & (ga < 30 * US)
    for name, m in zip(["[-3,0)", "[0,1)", "[1,10)", "[10,30)", "away"],
                       [am3, a01, a110, a1030, ~(a01 | a110 | am3 | a1030)]):
        out["jump_windows"][name]["time_share"] = float(m.mean())
    tot = float(cv.sum())
    out["jump_share_m3_p10"] = float((cv[wm3 | w01 | w110]).sum() / tot)
    # each onset's direction (the detected 0.2-s move) and our position just before it: with, against or flat;
    # the PnL in [0,1) and [1,10) s after it, by that alignment
    jd = np.sign(mm[np.searchsorted(tm, on, "left")] - mm[np.maximum(np.searchsorted(tm, on - 200_000, "right") - 1, 0)])
    # the position 0.2 s before the detection (when the detected move began): by the detection the takes have already
    # turned most positions the jump's way
    pj = np.searchsorted(tf, on - 200_000, "left") - 1
    pos_on = np.where(pj >= 0, cumq[np.maximum(pj, 0)], 0)
    align = np.sign(pos_on * jd)
    pj0 = np.searchsorted(tf, on, "left") - 1
    out["jump_with_at_detection"] = int((np.sign(np.where(pj0 >= 0, cumq[np.maximum(pj0, 0)], 0) * jd) > 0).sum())
    ia = np.searchsorted(on, ct, "right") - 1
    r01 = np.zeros(len(on))
    r110 = np.zeros(len(on))
    np.add.at(r01, ia[w01], cv[w01])
    np.add.at(r110, ia[w110], cv[w110])
    out["jump_alignment"] = {}
    for name, a in (("with", 1), ("against", -1), ("flat", 0)):
        m = align == a
        out["jump_alignment"][name] = {"n": int(m.sum()), "mean_abs_pos": float(np.abs(pos_on[m]).mean()) if m.any() else 0.0,
                                       "pnl_0_1": float(r01[m].sum()), "pnl_1_10": float(r110[m].sum())}

    # takes by the spread just before
    tk = take
    fut = {}
    for h in (1, 5):
        j = np.searchsorted(tm, tf + h * US, "right") - 1
        fut[h] = mm[np.maximum(j, 0)]
    rows = {}
    for name, m in [("1", spr_b == 1), ("2", spr_b == 2), ("3-4", (spr_b >= 3) & (spr_b <= 4)), ("5+", spr_b >= 5)]:
        m = m & tk
        lots = int(np.abs(q[m]).sum())
        rows[name] = {"fills": int(m.sum()), "lots": lots,
                      "paid_per_lot": float(-edge[m].sum() / lots) if lots else 0.0,
                      "mark1": float((q[m] * (fut[1][m] - p[m])).sum()),
                      "mark5": float((q[m] * (fut[5][m] - p[m])).sum())}
    out["takes_by_spread"] = rows

    # holding episodes
    pos_after = cumq
    pos_before = np.concatenate([[0], cumq[:-1]])
    ep_after = np.full(len(q), -1)
    starts, ends, end_flip = [], [], []
    ep_edge = []
    cur = -1
    for i in range(len(q)):
        pb, pa = pos_before[i], pos_after[i]
        e = float(edge[i])
        if pb == 0 and pa != 0:  # opens
            cur = len(starts)
            starts.append(tf[i]); ends.append(None); end_flip.append(False); ep_edge.append(e)
        elif pb != 0 and pa == 0:  # closes
            ep_edge[cur] += e
            ends[cur] = tf[i]
            cur = -1
        elif pb != 0 and np.sign(pb) != np.sign(pa):  # flips
            frac = abs(pb) / abs(q[i])
            ep_edge[cur] += e * frac
            ends[cur] = tf[i]
            end_flip[cur] = True
            cur = len(starts)
            starts.append(tf[i]); ends.append(None); end_flip.append(False); ep_edge.append(e * (1 - frac))
        elif pb != 0:
            ep_edge[cur] += e
        ep_after[i] = cur
    ends = [end_us if x is None else x for x in ends]
    starts_a, ends_a = np.array(starts), np.array(ends)
    ep_move = np.zeros(len(starts))
    epk = np.where(fi >= 0, ep_after[np.maximum(fi, 0)], -1)
    okm = epk >= 0
    np.add.at(ep_move, epk[okm], move[okm])
    ep_pnl = np.array(ep_edge) + ep_move
    dur = (ends_a - starts_a) / US
    bins = [0, 1, 2, 5, 10, 30, 60, 300, 1e9]
    hold = {}
    for lo, hi in zip(bins[:-1], bins[1:]):
        m = (dur >= lo) & (dur < hi)
        hold[f"{lo:g}-{hi:g}s" if hi < 1e9 else f"{lo:g}s+"] = {"n": int(m.sum()), "pnl": float(ep_pnl[m].sum()),
                                                                  "time": float(dur[m].sum())}
    flip = np.array(end_flip)
    out["holding"] = {"episodes": int(len(dur)), "q": [float(x) for x in np.quantile(dur, [0.1, 0.5, 0.9, 0.99])],
                      "time_weighted_median": float(np.sort(dur)[np.searchsorted(np.cumsum(np.sort(dur)), dur.sum() / 2)]),
                      "bins": hold, "check": float(ep_pnl.sum())}
    out["whipsaw"] = {}
    for s in (1, 2):
        m = flip & (dur < s)
        out["whipsaw"][f"<{s}s"] = {"n": int(m.sum()), "pnl": float(ep_pnl[m].sum()),
                                    "mean": float(ep_pnl[m].mean()) if m.any() else 0.0}
    out["share_at_limit"] = None
    # time at |pos| == 100 (the limit), on the 10-ms grid
    pg = np.searchsorted(tf, g, "right") - 1
    posg = np.where(pg >= 0, cumq[np.maximum(pg, 0)], 0)
    out["share_at_limit"] = float((np.abs(posg) >= 100).mean())
    out["share_flat"] = float((posg == 0).mean())

    # per 1,000-s block: mid PnL and the simulator's
    blocks = {}
    simp = np.loadtxt(logdir / "pnl.csv", delimiter=",", skiprows=1)
    for b0 in range(0, int(end_us // US), 1000):
        m = (ct >= b0 * US) & (ct < (b0 + 1000) * US)
        s0 = np.interp(b0, simp[:, 0], simp[:, 1])
        s1 = np.interp(b0 + 1000, simp[:, 0], simp[:, 1])
        blocks[f"{b0}-{b0 + 1000}"] = {"mid": float(cv[m].sum()), "sim": float(s1 - s0),
                                       "takes": int(((tf >= b0 * US) & (tf < (b0 + 1000) * US) & take).sum())}
    out["blocks"] = blocks
    return out


def fmt(x: float) -> str:
    return f"{x:,.0f}"


def report(o: dict) -> None:
    print(f"simulator PnL {fmt(o['sim_pnl'])}; mid PnL {fmt(o['mid_pnl'])} (cash {fmt(o['cash'])}, sim cash "
          f"{o['sim_cash']}, final position {o['pos_end']} at mid {o['last_mid']}); mark difference {fmt(o['mark_diff'])}; "
          f"identity residual {o['check']:.3f}")
    t, pz = o["takes"], o["passive"]
    print(f"takes: {t['fills']:,} fills, {t['lots']:,} lots, edge {fmt(t['edge'])} ({t['edge'] / t['lots']:.3f} a lot)")
    print(f"passive: {pz['fills']:,} fills, {pz['lots']:,} lots, edge {fmt(pz['edge'])} "
          f"({pz['edge'] / max(pz['lots'], 1):.3f} a lot)")
    print(f"position moves {fmt(o['moves'])}; time at |pos| 100 {o['share_at_limit']:.1%}, flat {o['share_flat']:.1%}")

    def table(title, rows, extra=None):
        print(f"\n{title}")
        print(f"{'':10s} {'pnl':>11s} {'take edge':>11s} {'passive':>9s} {'moves':>11s}" + ("  time" if extra else ""))
        for name, r in rows.items():
            line = f"{name:10s} {fmt(r['pnl']):>11s} {fmt(r['take_edge']):>11s} {fmt(r['passive_edge']):>9s} {fmt(r['moves']):>11s}"
            if extra and extra in r:
                line += f"  {r[extra]:.1%}"
            print(line)

    sd = o["regime_1s_sd"]
    table(f"regime (60-s blocks, median split of RV; 1-s sd calm {sd['calm']:.2f}, volatile {sd['volatile']:.2f})",
          o["regime"])
    if "speed" in o:
        table(f"speed terciles (cuts {o['speed_cuts'][0]:.3g}, {o['speed_cuts'][1]:.3g})", o["speed"])
    table(f"around jumps ({o['jumps']['onsets']} onsets of 3+ ticks in 0.2 s); share of PnL in [-3,10) s "
          f"{o['jump_share_m3_p10']:.1%}", o["jump_windows"], "time_share")
    print(f"our position 0.2 s before the detection against the jump's direction (with it at the detection: "
          f"{o['jump_with_at_detection']}): onsets, mean |pos|, PnL [0,1) s, PnL [1,10) s")
    for name, r in o["jump_alignment"].items():
        print(f"  {name:8s} {r['n']:5d} {r['mean_abs_pos']:6.1f} {fmt(r['pnl_0_1']):>10s} {fmt(r['pnl_1_10']):>10s}")
    print("\ntakes by the spread just before")
    print(f"{'spread':7s} {'fills':>7s} {'lots':>8s} {'paid/lot':>8s} {'mark 1s':>10s} {'mark 5s':>10s}")
    for name, r in o["takes_by_spread"].items():
        print(f"{name:7s} {r['fills']:7,d} {r['lots']:8,d} {r['paid_per_lot']:8.3f} {fmt(r['mark1']):>10s} {fmt(r['mark5']):>10s}")
    h = o["holding"]
    print(f"\nholding: {h['episodes']:,} episodes; duration q10/50/90/99 "
          + "/".join(f"{x:.2f}" for x in h["q"]) + f" s; time-weighted median {h['time_weighted_median']:.1f} s; "
          f"episode PnL sum {fmt(h['check'])}")
    for name, r in h["bins"].items():
        print(f"  {name:9s} n {r['n']:6,d}  pnl {fmt(r['pnl']):>10s}  time {r['time']:8,.0f} s")
    for name, r in o["whipsaw"].items():
        print(f"whipsaw (flip ended) {name}: n {r['n']:,}, pnl {fmt(r['pnl'])}, mean {r['mean']:.1f}")
    print("\nper 1,000 s: mid PnL / simulator PnL / takes")
    for name, r in o["blocks"].items():
        print(f"  {name:10s} {fmt(r['mid']):>10s} {fmt(r['sim']):>10s} {r['takes']:6,d}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("logdir", type=Path)
    ap.add_argument("--pred", type=Path, help="the Rust twin's RIDGE_PRED_LOG (with RIDGE_PRED_EXTRA) of the same run")
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    o = analyse(a.logdir, a.pred)
    report(o)
    if a.json:
        a.json.write_text(json.dumps(o, indent=1))


if __name__ == "__main__":
    main()
