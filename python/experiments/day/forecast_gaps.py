"""What F5's 400-ms forecast misses (8 Nov, round 4; data/arena/round4/stats.md, part 3).

The baseline is the forecast F5 actually made: the Rust prediction log (`RIDGE_PRED_LOG=<file> RIDGE_PRED_EXTRA=1 uv run
python -m arena.qsim_rust ridge_maker TAPE <F5's --set line> --threads 1`; per book event: time in us, mid, prediction,
skew, spread, inventory, the filter's gap, QS_RATE's speed). On tape_stats' 0.1-s grid (its cached replay), the target is
the tape's mid move over the next 0.4, 1 and 5 s. Each candidate signal x enters an OLS of the target on [1, forecast, x]
fitted on the first 75% of the tape; its **partial R^2** is 1 - SSE(with x) / SSE([1, forecast]) on the last 25%. Also:
the coefficient's effect in ticks per sd of x, and the **take-relevant tail**: at a one-tick spread (F5 only takes there),
the share of grid points where the forecast plus x's increment (the 0.4-s fit) crosses F5's bar (0.25 + half the spread)
differently from the forecast alone, next to the share where the forecast alone crosses it.

Candidates (all causal, from events at or before the grid point): the mid's 1/5/30-s trend; the last 3-tick jump's sign
and size decayed by its age; signed F lots over 1 and 5 s; G inserts at or inside the touch (bids minus asks) and the
mean distance behind the touch (asks minus bids) over 1 s; the G inserts' centre minus the mid over 0.5 s; near-touch
cancel lots (asks minus bids) over 0.5 and 1 s and cancel counts over 0.2 s; the filter's gap now and averaged over 1
and 5 s; the touch and the next four prices' depth imbalance; 2-ms ladder inserts (bids minus asks) over 1 s; and the
forecast times the speed, the spread and a recent jump (calibration). The calibration table: the slope of the 0.4-s
move on the forecast by speed tercile, spread, time since a jump and regime (a slope above 1 means the forecast is too
small there).

    uv run python -m experiments.day.forecast_gaps TAPE --pred PREDLOG [--cache R.npz] [--json OUT.json]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

from experiments.day.tape_stats import GRID, KIND_F, KIND_G, KIND_X, LEVELS, grid_of, load, regimes

HORIZONS = (0.4, 1.0, 5.0)
BAR = 0.25  # F5's FT_EDGE
FIT_SHARE = 0.75


def read_pred(path: Path) -> np.ndarray:
    return np.loadtxt(path, delimiter=",", dtype=np.float64)


def candidates(d: dict, grid: np.ndarray, gm: np.ndarray, pl: np.ndarray) -> tuple[dict, dict]:
    t = d["t"]
    n = len(grid)
    sgn = np.where(d["side"] == 0, 1.0, -1.0)
    kind, off, lots = d["kind"], d["off"], d["lots"].astype(float)

    def wsum(mask: np.ndarray, w: np.ndarray, k: float) -> np.ndarray:
        cs = np.concatenate([[0.0], np.cumsum(np.where(mask, w, 0.0))])
        hi = np.searchsorted(t, grid, "right")
        lo = np.searchsorted(t, grid - k, "right")
        return cs[hi] - cs[lo]

    def shift(x: np.ndarray, k: int) -> np.ndarray:
        out = np.full_like(x, np.nan)
        out[k:] = x[:-k]
        return out

    pt = pl[:, 0] / 1e6
    i = np.searchsorted(pt, grid, "right") - 1
    ok = i >= 0
    ii = np.clip(i, 0, len(pt) - 1)
    state = {"pred": np.where(ok, pl[ii, 2], np.nan), "gap": np.where(ok, pl[ii, 6], np.nan),
             "speed": np.where(ok, pl[ii, 7], np.nan)}
    sp = (d["ba"] - d["bb"]).astype(float)
    si = np.clip(np.searchsorted(t, grid, "right") - 1, 0, len(t) - 1)
    state["spread"] = sp[si]
    c: dict = {}
    for k in (1, 5, 30):
        c[f"trend_{k}s"] = gm - shift(gm, int(k / GRID))
    # the last 3-tick move within 0.2 s (every detection, unmerged: merging would look ahead to the run's end), its sign
    # and size, decayed by its age
    w = int(0.2 / GRID)
    move = np.zeros(n)
    move[w:] = gm[w:] - gm[:-w]
    has = np.abs(move) >= 3
    jsize = np.where(has, move, 0.0)
    idx = np.where(has, np.arange(n), 0)
    np.maximum.accumulate(idx, out=idx)
    seen = np.maximum.accumulate(has)
    age = np.where(seen, (np.arange(n) - idx) * GRID, 1e9)
    js = np.where(seen, jsize[idx], 0.0)
    state["jump_age"] = age
    for tau in (2, 10):
        c[f"jump_sign_decay{tau}s"] = np.sign(js) * np.exp(-age / tau)
    c["jump_size_decay5s"] = js * np.exp(-age / 5)
    F, G, X = kind == KIND_F, kind == KIND_G, (kind == KIND_X) & (d["side"] >= 0)
    for k in (1, 5):
        c[f"flow_lots_{k}s"] = wsum(F, sgn * d["traded"], k)
    c["flow_count_1s"] = wsum(F, sgn, 1)
    c["G_at_touch_1s"] = wsum(G & (off <= 0), sgn, 1)
    nb, na = wsum(G & (sgn > 0), np.ones_like(sgn), 1), wsum(G & (sgn < 0), np.ones_like(sgn), 1)
    ob, oa = wsum(G & (sgn > 0) & np.isfinite(off), np.nan_to_num(off), 1), wsum(G & (sgn < 0) & np.isfinite(off),
                                                                              np.nan_to_num(off), 1)
    c["G_offset_asym_1s"] = np.where((nb > 0) & (na > 0), oa / np.maximum(na, 1) - ob / np.maximum(nb, 1), 0.0)
    pr = d["price"].astype(float)
    nb5, na5 = wsum(G & (sgn > 0), np.ones_like(sgn), 0.5), wsum(G & (sgn < 0), np.ones_like(sgn), 0.5)
    pb5, pa5 = wsum(G & (sgn > 0), pr, 0.5), wsum(G & (sgn < 0), pr, 0.5)
    c["G_centre_minus_mid_0.5s"] = np.where((nb5 > 0) & (na5 > 0),
                                            0.5 * (pb5 / np.maximum(nb5, 1) + pa5 / np.maximum(na5, 1)) - gm, 0.0)
    near = X & (off <= 1)
    for k in (0.5, 1):
        c[f"cancel_lots_{k}s"] = wsum(near, -sgn * lots, k)
    c["cancel_count_0.2s"] = wsum(near, -sgn, 0.2)
    state["cancel_burst_0.2s"] = wsum(near, np.ones_like(sgn), 0.2)
    gap = np.nan_to_num(state["gap"])
    c["gap_now"] = gap
    cs = np.concatenate([[0.0], np.cumsum(gap)])
    for k in (1, 5):
        m = int(k / GRID)
        lo = np.maximum(np.arange(n) + 1 - m, 0)
        c[f"gap_mean_{k}s"] = (cs[np.arange(n) + 1] - cs[lo]) / (np.arange(n) + 1 - lo)
    gd = d["gdepth"][:n].astype(float)
    if len(gd) < n:
        gd = np.vstack([gd, np.repeat(gd[-1:], n - len(gd), 0)])
    b0, a0 = gd[:, 0], gd[:, LEVELS]
    c["touch_imbalance"] = (b0 - a0) / np.maximum(b0 + a0, 1)
    bb, aa = gd[:, 1:LEVELS].sum(1), gd[:, LEVELS + 1:].sum(1)
    c["depth2_5_imbalance"] = (bb - aa) / np.maximum(bb + aa, 1)
    # 2-ms ladders: a G insert 2 ms (+-50 us) after the previous G insert on its side
    lad = np.zeros(len(t), bool)
    for s in (0, 1):
        sel = np.flatnonzero(G & (d["side"] == s))
        dt = np.diff(t[sel])
        lad[sel[1:][np.abs(dt - 0.002) <= 50e-6]] = True
    c["ladder_1s"] = wsum(lad, sgn, 1)
    state["ladder_count_1s"] = wsum(lad, np.ones_like(sgn), 1)
    pred = np.nan_to_num(state["pred"])
    spd = np.nan_to_num(state["speed"])
    c["pred_x_speed"] = pred * (spd - np.nanmean(spd)) / (np.nanstd(spd) + 1e-9)
    c["pred_x_wide"] = pred * (state["spread"] > 1)
    c["pred_x_jump5s"] = pred * (age < 5)
    c["pred_x_cancel_burst"] = pred * (state["cancel_burst_0.2s"] > np.quantile(state["cancel_burst_0.2s"], 0.9))
    return c, state


def ols(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    return np.linalg.lstsq(X, y, rcond=None)[0]


def analyse(d: dict, pl: np.ndarray) -> dict:
    grid, gm = grid_of(d)
    c, st = candidates(d, grid, gm, pl)
    n = len(grid)
    pred = st["pred"]
    valid = np.isfinite(pred) & (grid >= 30)
    for v in c.values():
        valid &= np.isfinite(v)
    rep: dict = {"grid_points": int(valid.sum())}
    cut = grid[valid][int(FIT_SHARE * valid.sum())]
    fit, test = valid & (grid < cut), valid & (grid >= cut)
    one_tick = st["spread"] == 1
    need = BAR + 0.5
    base_take = np.where(np.abs(pred) > need, np.sign(pred), 0)
    rep["base_take_share_at_1tick"] = float((base_take[test & one_tick] != 0).mean())
    ys = {}
    for h in HORIZONS:
        k = int(round(h / GRID))
        y = np.full(n, np.nan)
        y[:-k] = gm[k:] - gm[:-k]
        ys[h] = y
    ok = {h: np.isfinite(ys[h]) for h in HORIZONS}
    rep["baseline"] = {}
    for h in HORIZONS:
        f, s = fit & ok[h], test & ok[h]
        X0 = np.column_stack([np.ones(n), pred])
        b0 = ols(X0[f], ys[h][f])
        r = ys[h][s] - X0[s] @ b0
        rep["baseline"][str(h)] = {"coef_pred": float(b0[1]), "test_r2": float(1 - r.var() / ys[h][s].var()),
                                   "test_corr": float(np.corrcoef(pred[s], ys[h][s])[0, 1])}
    rows = {}
    names = list(c)
    allx = np.column_stack([c[k] for k in names])
    mu, sd = allx[fit].mean(0), allx[fit].std(0) + 1e-12
    Z = (allx - mu) / sd
    for j, name in enumerate(names):
        row = {}
        for h in HORIZONS:
            f, s = fit & ok[h], test & ok[h]
            X0 = np.column_stack([np.ones(n), pred])
            X1 = np.column_stack([X0, Z[:, j]])
            b0, b1 = ols(X0[f], ys[h][f]), ols(X1[f], ys[h][f])
            sse0 = ((ys[h][s] - X0[s] @ b0) ** 2).sum()
            sse1 = ((ys[h][s] - X1[s] @ b1) ** 2).sum()
            sse1_in = ((ys[h][f] - X1[f] @ b1) ** 2).sum()
            sse0_in = ((ys[h][f] - X0[f] @ b0) ** 2).sum()
            row[str(h)] = {"partial_r2": float(1 - sse1 / sse0), "in_sample": float(1 - sse1_in / sse0_in),
                           "ticks_per_sd": float(b1[2])}
            if h == 0.4:
                inc = Z[:, j] * b1[2] + (b1[1] - 1) * 0  # x's increment only, on the raw forecast
                new = pred + inc
                new_take = np.where(np.abs(new) > need, np.sign(new), 0)
                m = test & one_tick
                row["take_change_share_at_1tick"] = float((new_take[m] != base_take[m]).mean())
        rows[name] = row
    rep["candidates"] = rows
    # every candidate together (calibration interactions included)
    rep["all_together"] = {}
    for h in HORIZONS:
        f, s = fit & ok[h], test & ok[h]
        X0 = np.column_stack([np.ones(n), pred])
        X1 = np.column_stack([X0, Z])
        b0, b1 = ols(X0[f], ys[h][f]), ols(X1[f], ys[h][f])
        sse0 = ((ys[h][s] - X0[s] @ b0) ** 2).sum()
        sse1 = ((ys[h][s] - X1[s] @ b1) ** 2).sum()
        entry = {"partial_r2": float(1 - sse1 / sse0)}
        if h == 0.4:
            inc = Z @ b1[2:]
            new = pred + inc
            new_take = np.where(np.abs(new) > need, np.sign(new), 0)
            m = test & one_tick
            entry["take_change_share_at_1tick"] = float((new_take[m] != base_take[m]).mean())
            entry["new_take_share_at_1tick"] = float((new_take[m] != 0).mean())
        rep["all_together"][str(h)] = entry
    # calibration: the 0.4-s move's slope on the forecast, by state (the whole tape)
    y = ys[0.4]
    base = valid & ok[0.4]
    spd = st["speed"]
    q1, q2 = np.nanquantile(spd[base], [1 / 3, 2 / 3])
    gstate, _ = regimes(gm)
    states = {
        "all": base, "speed_low": base & (spd < q1), "speed_mid": base & (spd >= q1) & (spd < q2),
        "speed_high": base & (spd >= q2), "spread_1": base & (st["spread"] == 1), "spread_2plus": base & (st["spread"] > 1),
        "jump_within_5s": base & (st["jump_age"] < 5), "no_jump_30s": base & (st["jump_age"] >= 30),
        "calm": base & (gstate[:n] == 0), "volatile": base & (gstate[:n] == 1),
        "cancel_burst_top10": base & (st["cancel_burst_0.2s"] > np.quantile(st["cancel_burst_0.2s"][base], 0.9)),
        "abs_pred_over_0.75": base & (np.abs(pred) > 0.75), "abs_gap_over_1": base & (np.abs(st["gap"]) > 1),
    }
    cal = {}
    for name, m in states.items():
        if m.sum() < 100:
            continue
        p, yy = pred[m], y[m]
        cal[name] = {"share": float(m.sum() / base.sum()), "slope": float(np.dot(p, yy) / np.dot(p, p)),
                     "corr": float(np.corrcoef(p, yy)[0, 1]), "sd_pred": float(p.std()), "sd_move": float(yy.std())}
    rep["calibration_0.4s"] = cal
    # signed outcome of base takes at a one-tick spread: the 0.4-s and 1-s move their way, minus the half spread
    m = valid & one_tick & (base_take != 0) & ok[1.0]
    rep["base_take_markout"] = {"n": int(m.sum()), "0.4s": float((base_take[m] * ys[0.4][m]).mean() - 0.5),
                                "1s": float((base_take[m] * ys[1.0][m]).mean() - 0.5),
                                "5s": float(np.nanmean(base_take[m] * ys[5.0][m]) - 0.5)}
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("tape", type=Path)
    ap.add_argument("--pred", type=Path, required=True)
    ap.add_argument("--cache", type=Path)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    d = load(a.tape, a.cache)
    rep = analyse(d, read_pred(a.pred))
    rep["source"] = str(a.tape)
    text = json.dumps(rep, indent=1)
    print(text)
    if a.json:
        a.json.write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
