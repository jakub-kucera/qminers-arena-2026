"""A tape's statistical structure, for comparing rounds (8 Nov, round 4; data/arena/round4/stats.md).

One replay of the tape through tape_book's Book (the starter's matching, no user orders) keeps every event's time, kind
(G insert, F insert, cancel), side, lots, price, traded lots, its distance from its own touch before it, and the touch
after it; every 0.1 s it snapshots the depth of the best five prices a side. The arrays are cached (--cache) and shared
with forecast_gaps. The report, on the 0.1-s grid of the mid (the last mid at or before each point):

- **Regimes**: 10-s blocks' realised variance of 0.1-s mid changes, a two-state Gaussian mixture on its log (EM):
  each state's share of time, its runs (in seconds) and its 1-s sd; plus the share of seconds at 5+ ticks/s of mid path.
- **Jumps**: a mid move of J+ ticks within 0.2 s (J = 3, 5, 10, 20), detections within 1 s merged; the size (the mid
  0.7 s after the last detection minus 0.3 s before the first), how far it runs on (the signed move from the jump's end to
  +1/5/30/60 s, the mean maximum excursion its way within 30 s and when), and whether the next jump repeats its sign.
- **Autocorrelation** of non-overlapping mid changes at 0.1, 0.4, 1, 5, 30 and 60 s (lag one), the variance ratio
  against 1 s, and the same 1-s and 5-s autocorrelations away from jumps (10 s either side excluded) and in each regime.
- **Drift or momentum**: the net move's t-statistic against the 1-s sd (a constant push shows as a large t with small
  autocorrelations; clustered momentum as positive autocorrelation with t near 0); the mean signed 60-s move of each
  1,000-s segment.
- **Order flow**: the F (IOC) rate, requested and traded sizes, P(side = previous side), the autocorrelation of 1-s
  signed traded lots at lags 1, 2, 5 and 10 s, and the mid's move after a second's net flow.
- **Spread and depth**: the spread's shares, the touch and the next four prices' depth.

    uv run python -m experiments.day.tape_stats TAPE [--cache R.npz] [--json R.json]
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from array import array
from pathlib import Path

import numpy as np

from experiments.day.tape_book import Book

VERSION = 1
GRID = 0.1  # seconds
LEVELS = 5
KIND_G, KIND_F, KIND_X = 0, 1, 2


def replay(path: Path) -> dict:
    book = Book()
    t, kind, side, lots, price, traded, off = (array("d"), array("b"), array("b"), array("l"), array("l"), array("l"),
                                               array("d"))
    bb, ba, qb, qa = array("l"), array("l"), array("l"), array("l")
    gt, gdepth = array("d"), array("l")  # grid snapshots: time, then LEVELS bid and LEVELS ask lots
    next_grid = GRID
    fills: list = []
    with open(path, newline="") as fh:
        reader = csv.reader(fh)
        next(reader)
        for row in reader:
            now = float(row[0])
            while now >= next_grid:
                b0, a0 = book.best
                gt.append(next_grid)
                for k in range(LEVELS):
                    gdepth.append(book.vol[0].get(b0 - k, 0) if b0 is not None else 0)
                for k in range(LEVELS):
                    gdepth.append(book.vol[1].get(a0 + k, 0) if a0 is not None else 0)
                next_grid = round(next_grid + GRID, 6)
            b0, a0 = book.best
            if row[1] == "Insert":
                s = 0 if row[3] == "B" else 1
                p, q = int(row[5]), int(row[4])
                ioc = row[6] != "G"
                own = b0 if s == 0 else a0
                d = (own - p if s == 0 else p - own) if own is not None else math.nan
                fills.clear()
                tr = book.insert(int(row[2]), s, p, q, ioc, fills)
                kind.append(KIND_F if ioc else KIND_G)
                side.append(s)
                lots.append(q)
                price.append(p)
                traded.append(tr)
                off.append(d)
            else:
                found = book.cancel(int(row[2]))
                if found is None:
                    kind.append(KIND_X)
                    side.append(-1)
                    lots.append(0)
                    price.append(0)
                    traded.append(0)
                    off.append(math.nan)
                else:
                    s, p, q = found
                    own = b0 if s == 0 else a0
                    kind.append(KIND_X)
                    side.append(s)
                    lots.append(q)
                    price.append(p)
                    traded.append(0)
                    off.append((own - p if s == 0 else p - own) if own is not None else math.nan)
            t.append(now)
            b1, a1 = book.best
            bb.append(b1 if b1 is not None else -1)
            ba.append(a1 if a1 is not None else -1)
            qb.append(book.vol[0].get(b1, 0) if b1 is not None else 0)
            qa.append(book.vol[1].get(a1, 0) if a1 is not None else 0)
    out = {k: np.frombuffer(v, dtype=np.float64 if v.typecode == "d" else (np.int8 if v.typecode == "b" else np.int64))
           for k, v in dict(t=t, kind=kind, side=side, lots=lots, price=price, traded=traded, off=off, bb=bb, ba=ba,
                            qb=qb, qa=qa, gt=gt).items()}
    out["gdepth"] = np.frombuffer(gdepth, dtype=np.int64).reshape(-1, 2 * LEVELS)
    return out


def load(path: Path, cache: Path | None) -> dict:
    stat = path.stat()
    key = f"{VERSION}|{path.resolve()}|{stat.st_size}|{int(stat.st_mtime)}"
    if cache is not None and cache.exists():
        z = np.load(cache, allow_pickle=False)
        if str(z["key"]) == key:
            return {k: z[k] for k in z.files if k != "key"}
    data = replay(path)
    if cache is not None:
        np.savez(cache, key=np.array(key), **data)
    return data


def mid_events(d: dict) -> np.ndarray:
    valid = (d["bb"] >= 0) & (d["ba"] >= 0)
    mid = np.where(valid, (d["bb"] + d["ba"]) / 2.0, np.nan)
    # carry the last valid mid forward
    idx = np.where(valid, np.arange(len(mid)), 0)
    np.maximum.accumulate(idx, out=idx)
    return mid[idx]


def on_grid(times: np.ndarray, values: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """The last value at or before each grid time (the first value before the first event)."""
    i = np.searchsorted(times, grid, side="right") - 1
    return values[np.clip(i, 0, len(values) - 1)]


def grid_of(d: dict) -> tuple[np.ndarray, np.ndarray]:
    t_end = float(d["t"][-1])
    grid = np.arange(1, int(t_end / GRID) + 1) * GRID
    return grid, on_grid(d["t"], mid_events(d), grid)


def gmm2(x: np.ndarray, iters: int = 200) -> tuple[np.ndarray, dict]:
    """A two-state 1-D Gaussian mixture by EM; returns each point's state (1 = the higher mean) and the fit."""
    lo, hi = np.quantile(x, [0.25, 0.75])
    mu, sd, w = np.array([lo, hi]), np.array([x.std(), x.std()]) / 2, np.array([0.5, 0.5])
    for _ in range(iters):
        dens = w / (sd * math.sqrt(2 * math.pi)) * np.exp(-0.5 * ((x[:, None] - mu) / sd) ** 2)
        r = dens / dens.sum(1, keepdims=True)
        n = r.sum(0)
        w, mu = n / len(x), (r * x[:, None]).sum(0) / n
        sd = np.sqrt((r * (x[:, None] - mu) ** 2).sum(0) / n) + 1e-9
    order = np.argsort(mu)
    state = (r[:, order[1]] > 0.5).astype(int)
    return state, {"mean": mu[order].tolist(), "sd": sd[order].tolist(), "weight": w[order].tolist()}


def runs(state: np.ndarray, value: int) -> np.ndarray:
    """Lengths of runs of `value` in a 0/1 sequence."""
    s = np.concatenate([[0], (state == value).astype(int), [0]])
    edges = np.flatnonzero(np.diff(s))
    return edges[1::2] - edges[::2]


def regimes(grid_mid: np.ndarray, block_s: float = 10.0) -> tuple[np.ndarray, dict]:
    """10-s blocks' realised variance of 0.1-s changes, a two-state mixture on its log; the state per grid point."""
    per = int(round(block_s / GRID))
    dm = np.diff(grid_mid, prepend=grid_mid[0])
    nb = len(dm) // per
    rv = (dm[: nb * per] ** 2).reshape(nb, per).sum(1)
    state, fit = gmm2(np.log(rv + 0.25))
    out = {"block_s": block_s, "blocks": int(nb), "fit_log_rv": fit}
    m1 = grid_mid[:: int(1 / GRID)]
    d1 = np.diff(m1)
    sec_state = np.repeat(state, int(block_s))
    sec_state = np.concatenate([sec_state, np.full(max(len(d1) - len(sec_state), 0), state[-1])])[: len(d1)]
    for v, name in ((0, "calm"), (1, "volatile")):
        r = runs(state, v) * block_s
        sel = d1[sec_state == v]
        out[name] = {"share": float((state == v).mean()), "runs": int(len(r)), "mean_run_s": float(r.mean()) if len(r) else 0,
                     "median_run_s": float(np.median(r)) if len(r) else 0, "max_run_s": float(r.max()) if len(r) else 0,
                     "sd_1s": float(sel.std()) if len(sel) else math.nan}
    grid_state = np.repeat(state, per)
    grid_state = np.concatenate([grid_state, np.full(len(grid_mid) - len(grid_state), state[-1])])
    return grid_state, out


def find_jumps(grid_mid: np.ndarray, j: float, win_s: float = 0.2, merge_s: float = 1.0) -> list[tuple[int, int, float]]:
    """(first index, last index, size) of each jump: a J+ tick move within win_s, detections within merge_s merged."""
    w = int(round(win_s / GRID))
    move = np.zeros_like(grid_mid)
    move[w:] = grid_mid[w:] - grid_mid[:-w]
    hits = np.flatnonzero(np.abs(move) >= j)
    out = []
    merge = int(round(merge_s / GRID))
    n = len(grid_mid)
    i = 0
    while i < len(hits):
        first = last = hits[i]
        sign = np.sign(move[first])
        i += 1
        while i < len(hits) and hits[i] - last <= merge and np.sign(move[hits[i]]) == sign:
            last = hits[i]
            i += 1
        a = max(first - w - int(0.3 / GRID) + 1, 0)
        b = min(last + int(0.7 / GRID), n - 1)
        out.append((first, last, float(grid_mid[b] - grid_mid[a])))
    return out


def jump_stats(grid_mid: np.ndarray, j: float) -> dict:
    jumps = find_jumps(grid_mid, j)
    n = len(grid_mid)
    if not jumps:
        return {"count": 0}
    sizes = np.array([s for _, _, s in jumps])
    signs = np.sign(sizes)
    ends = np.array([min(last + int(0.7 / GRID), n - 1) for _, last, _ in jumps])
    out = {"count": len(jumps), "per_1000s": len(jumps) / (n * GRID) * 1000,
           "abs_size_q": dict(zip(["p10", "p50", "p90", "p99", "max"],
                                  np.quantile(np.abs(sizes), [0.1, 0.5, 0.9, 0.99, 1.0]).round(2).tolist())),
           "up_share": float((sizes > 0).mean())}
    cont = {}
    for h in (1, 5, 30, 60):
        k = int(round(h / GRID))
        ok = ends + k < n
        mv = signs[ok] * (grid_mid[ends[ok] + k] - grid_mid[ends[ok]])
        cont[f"{h}s"] = {"mean": float(mv.mean()), "se": float(mv.std() / math.sqrt(max(len(mv), 1))),
                         "pos_share": float((mv > 0).mean()), "per_jump_tick": float(mv.mean() / np.abs(sizes[ok]).mean())}
    out["after_end"] = cont
    # from the first detection (causal: what a bot seeing the jump could expect next; after_end conditions on its end)
    firsts0 = np.array([f for f, _, _ in jumps])
    onset = {}
    for h in (0.4, 1, 5, 30):
        k = int(round(h / GRID))
        ok = firsts0 + k < n
        mv = signs[ok] * (grid_mid[firsts0[ok] + k] - grid_mid[firsts0[ok]])
        onset[f"{h}s"] = {"mean": float(mv.mean()), "se": float(mv.std() / math.sqrt(max(len(mv), 1))),
                          "pos_share": float((mv > 0).mean())}
    out["after_detection"] = onset
    k30 = int(round(30 / GRID))
    exc, when = [], []
    for e, s in zip(ends, signs):
        if e + k30 >= n:
            continue
        path = s * (grid_mid[e: e + k30 + 1] - grid_mid[e])
        i = int(np.argmax(path))
        exc.append(path[i])
        when.append(i * GRID)
    out["max_excursion_30s"] = {"mean": float(np.mean(exc)), "median": float(np.median(exc)),
                                "mean_time_s": float(np.mean(when)), "median_time_s": float(np.median(when))}
    firsts = np.array([f for f, _, _ in jumps])
    gaps = np.diff(firsts) * GRID
    same = signs[1:] == signs[:-1]
    out["gap_s_q"] = dict(zip(["p10", "p50", "p90"], np.quantile(gaps, [0.1, 0.5, 0.9]).round(2).tolist())) if len(gaps) else {}
    out["next_same_sign"] = float(same.mean()) if len(same) else math.nan
    out["next_same_sign_within_30s"] = float(same[gaps <= 30].mean()) if (gaps <= 30).any() else math.nan
    out["next_same_sign_after_30s"] = float(same[gaps > 30].mean()) if (gaps > 30).any() else math.nan
    return out


def acf_at(grid_mid: np.ndarray, h: float, mask: np.ndarray | None = None) -> tuple[float, int]:
    k = int(round(h / GRID))
    m = grid_mid[::k]
    d = np.diff(m)
    a, b = d[:-1], d[1:]
    if mask is not None:
        mk = mask[::k][1:]
        keep = mk[:-1] & mk[1:]
        a, b = a[keep[: len(a)]], b[keep[: len(b)]]
    if len(a) < 10 or a.std() == 0 or b.std() == 0:
        return math.nan, len(a)
    return float(np.corrcoef(a, b)[0, 1]), len(a)


def structure(d: dict) -> dict:
    grid, gm = grid_of(d)
    rep: dict = {"seconds": float(grid[-1])}
    m1 = gm[:: int(1 / GRID)]
    d1 = np.diff(m1)
    rep["mid"] = {"sd_1s": float(d1.std()), "net": float(gm[-1] - gm[0]), "range": float(gm.max() - gm.min()),
                  "drift_t": float((gm[-1] - gm[0]) / (d1.std() * math.sqrt(len(d1))))}
    # path speed: |mid change| summed per second over every event
    me = mid_events(d)
    dme = np.nan_to_num(np.abs(np.diff(me, prepend=me[0])))
    sec = d["t"].astype(np.int64)
    speed = np.bincount(sec, weights=dme, minlength=int(grid[-1]) + 1)[: int(grid[-1])]
    rep["speed"] = {"mean": float(speed.mean()), "share_5plus": float((speed >= 5).mean()),
                    "q": dict(zip(["p10", "p50", "p90"], np.quantile(speed, [0.1, 0.5, 0.9]).round(2).tolist()))}
    gstate, rep["regimes"] = regimes(gm)
    rep["jumps"] = {str(j): jump_stats(gm, j) for j in (3, 5, 10, 20)}
    # autocorrelation and variance ratio
    var1 = d1.var()
    rep["acf"] = {}
    for h in (0.1, 0.4, 1, 5, 30, 60):
        k = int(round(h / GRID))
        dh = np.diff(gm[::k])
        rep["acf"][str(h)] = {"acf1": acf_at(gm, h)[0], "vr_vs_1s": float(dh.var() / (h * var1))}
    # away from jumps (5-tick jumps, 10 s either side) and by regime
    jumps5 = find_jumps(gm, 5)
    away = np.ones(len(gm), bool)
    pad = int(10 / GRID)
    for f, l, _ in jumps5:
        away[max(f - pad, 0): l + pad] = False
    rep["acf_away_from_jumps"] = {"share_of_time": float(away.mean())}
    for h in (1, 5, 30):
        rep["acf_away_from_jumps"][str(h)] = acf_at(gm, h, away)[0]
    for v, name in ((0, "calm"), (1, "volatile")):
        rep["acf_" + name] = {str(h): acf_at(gm, h, gstate == v)[0] for h in (1, 5, 30)}
    # momentum: next h-s move against the last L-s move (overlapping, 1-s steps), slope in ticks per tick
    mom = {}
    for lb, h in ((1, 1), (5, 5), (30, 30), (60, 60), (300, 300), (5, 30), (30, 5)):
        L, H = int(lb), int(h)
        past = m1[L:-H] - m1[:-H - L] if H else None
        fut = m1[L + H:] - m1[L:-H]
        n = min(len(past), len(fut))
        past, fut = past[:n], fut[:n]
        mom[f"{lb}s->{h}s"] = {"slope": float(np.dot(past, fut) / np.dot(past, past)), "corr": float(np.corrcoef(past, fut)[0, 1])}
    rep["momentum"] = mom
    seg = int(1000 / GRID)
    rep["net_per_1000s"] = [float(gm[min((i + 1) * seg, len(gm) - 1)] - gm[i * seg]) for i in range(len(gm) // seg)]
    # order flow
    F = d["kind"] == KIND_F
    sgn = np.where(d["side"] == 0, 1, -1)
    ft, fs, fq, ftr = d["t"][F], sgn[F], d["lots"][F], d["traded"][F]
    flow = {"count": int(F.sum()), "rate_per_s": float(F.sum() / grid[-1]),
            "requested_q": dict(zip(["p10", "p50", "p90", "p99"], np.quantile(fq, [0.1, 0.5, 0.9, 0.99]).round(1).tolist())),
            "traded_q": dict(zip(["p10", "p50", "p90", "p99"], np.quantile(ftr, [0.1, 0.5, 0.9, 0.99]).round(1).tolist())),
            "zero_traded_share": float((ftr == 0).mean()), "buy_share": float((fs > 0).mean()),
            "same_side_as_previous": float((fs[1:] == fs[:-1]).mean())}
    top = np.sort(fq)[-max(int(0.05 * len(fq)), 2):]
    flow["hill_tail_top5pct"] = float(1 / np.mean(np.log(top / top[0])[1:])) if top[0] > 0 else math.nan
    nsec = int(grid[-1])
    net1 = np.bincount(ft.astype(np.int64), weights=fs * ftr, minlength=nsec + 1)[:nsec]
    flow["signed_lots_1s_acf"] = {str(l): float(np.corrcoef(net1[:-l], net1[l:])[0, 1]) for l in (1, 2, 5, 10, 30)}
    fut1 = np.diff(m1)[1: nsec]
    n = min(len(net1) - 1, len(fut1))
    nx = net1[:n]
    fut5 = m1[6: 6 + n] - m1[1: 1 + n] if len(m1) > n + 6 else None
    flow["next_mid_per_100_lots"] = {"1s": float(np.dot(nx, fut1[:n]) / np.dot(nx, nx) * 100),
                                     "corr_1s": float(np.corrcoef(nx, fut1[:n])[0, 1])}
    if fut5 is not None:
        flow["next_mid_per_100_lots"]["5s"] = float(np.dot(nx, fut5) / np.dot(nx, nx) * 100)
        flow["next_mid_per_100_lots"]["corr_5s"] = float(np.corrcoef(nx, fut5)[0, 1])
    rep["flow"] = flow
    # cancels and G inserts
    G, X = d["kind"] == KIND_G, (d["kind"] == KIND_X) & (d["side"] >= 0)
    rep["orders"] = {"G_rate_per_s": float(G.sum() / grid[-1]), "cancel_rate_per_s": float(X.sum() / grid[-1]),
                     "G_size_q": dict(zip(["p10", "p50", "p90"], np.quantile(d["lots"][G], [0.1, 0.5, 0.9]).tolist())),
                     "G_inside_or_at_touch_share": float((d["off"][G] <= 0).mean()),
                     "G_off_touch_q": dict(zip(["p10", "p50", "p90"], np.nanquantile(d["off"][G], [0.1, 0.5, 0.9]).tolist()))}
    # spread and depth on the grid
    sp = on_grid(d["t"], (d["ba"] - d["bb"]).astype(float), grid)
    vals, cnt = np.unique(np.clip(sp, 0, 6), return_counts=True)
    rep["spread"] = {"mean": float(sp.mean()), "shares": {str(int(v)) + ("+" if v == 6 else ""): float(c / len(sp))
                                                          for v, c in zip(vals, cnt)}}
    gd = d["gdepth"].astype(float)
    rep["depth"] = {f"level{k + 1}_median": float(np.median((gd[:, k] + gd[:, LEVELS + k]) / 2)) for k in range(LEVELS)}
    rep["depth"]["touch_q10"] = float(np.quantile(np.minimum(gd[:, 0], gd[:, LEVELS]), 0.1))
    rep["depth"]["touch_median_min_side"] = float(np.median(np.minimum(gd[:, 0], gd[:, LEVELS])))
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("tape", type=Path)
    ap.add_argument("--cache", type=Path)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    d = load(a.tape, a.cache)
    rep = structure(d)
    rep["source"] = str(a.tape)
    text = json.dumps(rep, indent=1)
    print(text)
    if a.json:
        a.json.write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
