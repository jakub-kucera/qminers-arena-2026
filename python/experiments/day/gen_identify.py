"""Phase 1 of docs/GENERATOR_PLAN.md: identify the tape generator's structure, one tape at a time (8 Nov, round 3).

One replay of the tape through tape_book's Book (the starter's matching, no user orders) gives every event with the
touch before and after it, the lots each aggressive order traded and each cancel's order (insert time, price, lots
left). Every measurement is then numpy on those arrays. The methods, in the report's order:

- **Latent estimate** `C(t)`: the mean price of the bid G inserts plus the mean of the ask G inserts, halved, over a
  window (0.1 s, ~18 inserts). If inserts sit symmetrically around a latent price it is that price plus noise (its
  noise: the variance of C's change across 0.13 s at times with no aggressive order, `noise_var`). On a 0.1-s grid
  (window +-0.05 s, empty windows carried forward) it is the latent path.
- **Impact** (item 2): for isolated aggressive (F) orders (none in the 0.1 s before, none in the 0.13 s after), the jump
  of C from [t-0.1, t) to [t+0.03, t+0.13), signed by the order's side, regressed through 0 on traded^beta and size^beta
  over a beta grid (the lowest residual variance wins); the table by size bin; whether the jump's variance exceeds the
  noise (a random impact would add p(1-p)). Permanence: C at t+h (h 0.1 s to 300 s) minus C before, minus the fitted
  impacts of the other F orders in between, by size bin: what is left of the order's own impact.
- **Exogenous moves** (item 1): over grid intervals of h s, the change of C against P, the sum of the fitted impacts of
  the F orders inside: var(D - P) / h is the latent's own variance a second (a flat ratio across h means a random walk;
  `slope` of D on P above 1 means the F sides lean the way of the other moves). The 1-s residuals' kurtosis and the
  share of their variance in steps of 2+ / 5+ ticks separate diffusion from jumps. Clustering: the residual's realised
  variance over 60-s blocks (RV60), its quantiles and the autocorrelation of log RV60; a 1-D Gaussian mixture with 1-3
  states on log RV60 (EM; BIC; each state's share, mean run in blocks, and per-state F and G rates, insert width, 1-tick
  share, impact c and exogenous variance): the regimes, and which parameters move with them.
- **Jumps**: a 0.2-s change of R = C - P (the latent net of the impacts) of J+ ticks (default 3); detections within 1 s
  merge into one jump; its size is R 0.7 s after the last detection minus R 0.3 s before the first. Rate, sizes, gaps,
  counts per 500 s, persistence (R at +h over the size), the sign against the previous one. **Precursors**: the book
  spread, the insert width (mean ask insert minus mean bid insert over the last 0.5 s) and the share of inserts 3+ ticks
  behind their own touch, at lags -60 s to +3 s from each onset, for all jumps and for the first jump after 30 s without
  one; hit rates: P(a jump starts within 1 / 5 s | the feature at or over its 90-99.9th percentile), at times 10+ s
  after any jump, and the share of those jumps the signal flags. **Direction**: the correlation of the jump's sign with
  the signed F flow, the insert and cancel imbalance, the latent's drift and centre minus mid, before the onset; and the
  first trade at a 3+ tick spread after 0.3 s without trades: whether its side is the latent's next move, and what a
  taker could take 5 ms later (the lots on that side beyond the latent's new level, from a second replay of the CSV).
- **Placement** (item 3): each G insert's offset from C over the previous 0.1 s (bids C - p, asks p - C), its
  distribution (0.5-tick bins) overall, by RV60 tercile and by the spread; sizes by offset; the insert width and the
  insert rate by RV60 tercile; the offset from the own touch by spread (tape_gen's table).
- **Cancels** (item 4): lifetimes (insert to cancel, filled or not) and the share of G orders with a cancel; a
  discrete-time hazard over age bins: P(cancel in the bin | alive at its start) for orders the latent has passed at the
  bin's start (a bid at or above C, an ask at or below) against fresh ones (0.5+ ticks on their side): stale cancels
  if the hazard ratio is far above 1. The cancels of resting lots in the 50 ms after a jump's onset on its stale side.
- **Aggressive flow** (item 5): inter-arrival CV, the dispersion index (var / mean) of counts in 1-s and 10-s bins and
  the autocorrelation of 1-s counts (Poisson: CV 1, dispersion 1, no autocorrelation); P(side = previous side); the
  side against the latent's past 1-s exogenous move (trend followers), its next 0.2-2 s exogenous move (informed) and
  C minus the mid at arrival; size quantiles and the Hill tail index (top 5%); the limit price against the opposite
  touch and against C.

    uv run python -m experiments.day.gen_identify data/arena/round2/round2_public.csv [--cache R.npz] [--json R.json] [--jump 3]
    uv run python -m experiments.day.gen_identify --compare r1.json r2.json ...   # item 6: the parameter table
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from array import array
from pathlib import Path

import numpy as np

from experiments.day.tape_book import Book

G, F, C = 0, 1, 2
STEP = 0.1  # the latent grid (s)
EDGES = [0, 10, 30, 60, 120, 250, 500, 1000, 10**9]


def replay(path: Path) -> dict:
    """Per event the time, kind (G, F, cancel), side, lots, price, the touch before and after, the lots traded; per
    cancel its order's insert event index, lifetime, first lots and lots left (side -1 if the order was not resting)."""
    book = Book()
    t_a, k_a, s_a, q_a, p_a = array("d"), array("b"), array("b"), array("q"), array("q")
    bb0, ba0, bb1, ba1, tr = array("q"), array("q"), array("q"), array("q"), array("q")
    c_life, c_rem, c_q0, c_ins = array("d"), array("q"), array("q"), array("q")
    live = {}
    i = 0
    with path.open() as fh:
        next(fh)
        for line in fh:
            t, op, oid, side, vol, price, life = line.rstrip("\n").split(",")
            t = float(t)
            b0, a0 = book.best
            t_a.append(t)
            bb0.append(b0 or 0)
            ba0.append(a0 or 0)
            if op == "Insert":
                sd = 0 if side == "B" else 1
                p, q = int(price), int(vol)
                ioc = life == "F"
                tr.append(book.insert(oid, sd, p, q, ioc))
                k_a.append(F if ioc else G)
                s_a.append(sd)
                q_a.append(q)
                p_a.append(p)
                c_life.append(-1.0)
                c_rem.append(0)
                c_q0.append(0)
                c_ins.append(-1)
                if not ioc:
                    live[oid] = (i, t, q)
            else:
                rec = live.pop(oid, None)
                found = book.cancel(oid)
                k_a.append(C)
                s_a.append(found[0] if found else -1)
                p_a.append(found[1] if found else 0)
                c_rem.append(found[2] if found else 0)
                q_a.append(0)
                tr.append(0)
                c_life.append(t - rec[1] if rec else -1.0)
                c_q0.append(rec[2] if rec else 0)
                c_ins.append(rec[0] if rec else -1)
            b1, a1 = book.best
            bb1.append(b1 or 0)
            ba1.append(a1 or 0)
            i += 1
    names = ("t", "kind", "side", "qty", "price", "bb0", "ba0", "bb1", "ba1", "traded", "c_life", "c_rem", "c_q0", "c_ins")
    arrays = (t_a, k_a, s_a, q_a, p_a, bb0, ba0, bb1, ba1, tr, c_life, c_rem, c_q0, c_ins)
    return {n: np.frombuffer(a, dtype=a.typecode) for n, a in zip(names, arrays)}


def load(path: Path, cache: Path | None) -> dict:
    if cache is not None and cache.exists():
        z = np.load(cache)
        return {k: z[k] for k in z.files}
    ev = replay(path)
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.savez(cache, **ev)
    return ev


def win_mean(arr, times, lo, hi):
    cs = np.r_[0, np.cumsum(arr, dtype=float)]
    s, e = np.searchsorted(times, lo, "left"), np.searchsorted(times, hi, "left")
    with np.errstate(invalid="ignore", divide="ignore"):
        return (cs[e] - cs[s]) / (e - s), e - s


def wsum(w, times, lo, hi):
    cs = np.r_[0, np.cumsum(w, dtype=float)]
    return cs[np.searchsorted(times, hi, "left")] - cs[np.searchsorted(times, lo, "left")]


def ffill(x):
    idx = np.where(~np.isnan(x), np.arange(len(x)), 0)
    np.maximum.accumulate(idx, out=idx)
    return x[idx]


def r(x, n=4):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), n)


class Tape:
    def __init__(self, ev: dict, csv: Path) -> None:
        self.ev, self.csv = ev, csv
        t, k, s, p = ev["t"], ev["kind"], ev["side"], ev["price"]
        self.t, self.dur = t, float(t[-1] - t[0])
        gb, ga, f = (k == G) & (s == 0), (k == G) & (s == 1), k == F
        self.gb, self.ga, self.f = gb, ga, f
        self.tb, self.pb, self.ta, self.pa = t[gb], p[gb], t[ga], p[ga]
        self.tf, self.sf, self.pf = t[f], s[f], p[f]
        self.qf, self.trf = ev["qty"][f].astype(float), ev["traded"][f].astype(float)
        self.sign = np.where(self.sf == 0, 1.0, -1.0)
        self.grid = np.arange(1.0, t[-1] - 2, STEP)
        gi = np.clip(np.searchsorted(t, self.grid, "right") - 1, 0, len(t) - 1)
        bb, ba = ev["bb1"][gi].astype(float), ev["ba1"][gi].astype(float)
        ok = (bb > 0) & (ba > 0)
        self.spread_g = np.where(ok, ba - bb, np.nan)
        self.mid_g = np.where(ok, (bb + ba) / 2, np.nan)
        self.C = ffill(self.centre(self.grid - STEP / 2, self.grid + STEP / 2))

    def centre(self, lo, hi):
        eb, _ = win_mean(self.pb, self.tb, lo, hi)
        ea, _ = win_mean(self.pa, self.ta, lo, hi)
        return (eb + ea) / 2

    def at(self, series, times):
        return series[np.clip(np.searchsorted(self.grid, times, "right") - 1, 0, len(self.grid) - 1)]

    def impact_path(self, c, beta):
        return np.r_[0, np.cumsum(self.sign * c * self.trf ** beta)]


def measure_impact(tp: Tape) -> dict:
    tf, W = tp.tf, 0.10
    gap = np.diff(tf)
    prev_gap, next_gap = np.r_[np.inf, gap], np.r_[gap, np.inf]
    iso = (prev_gap > W) & (next_gap > 0.03 + W)
    j = (tp.centre(tf + 0.03, tf + 0.03 + W) - tp.centre(tf - W, tf)) * tp.sign
    m = iso & ~np.isnan(j)
    rng = np.random.default_rng(0)
    rt = np.sort(rng.uniform(2, tp.t[-1] - 2, 100_000))
    k = np.searchsorted(tf, rt)
    quiet = (rt - tf[np.clip(k - 1, 0, None)] > W) & (tf[np.clip(k, 0, len(tf) - 1)] - rt > 0.03 + W)
    d0 = tp.centre(rt[quiet] + 0.03, rt[quiet] + 0.03 + W) - tp.centre(rt[quiet] - W, rt[quiet])
    noise = float(np.nanvar(d0))
    scan = []
    for beta in (0.3, 0.4, 0.45, 0.5, 0.55, 0.6, 0.7, 1.0):
        for name, x in (("traded", tp.trf), ("size", tp.qf)):
            X = x[m] ** beta
            c = float(X @ j[m] / (X @ X))
            scan.append({"beta": beta, "on": name, "c": c, "resid_var": float(np.mean((j[m] - c * X) ** 2))})
    best = min(scan, key=lambda d: d["resid_var"])
    X = tp.trf[m] ** 0.5
    c05 = float(X @ j[m] / (X @ X))
    table = []
    for lo, hi in zip(EDGES[:-1], EDGES[1:]):
        sel = m & (tp.qf > lo) & (tp.qf <= hi)
        if sel.sum() > 5:
            table.append({"size": f"{lo}-{hi}", "n": int(sel.sum()), "jump": r(j[sel].mean()), "var": r(j[sel].var()),
                          "sqrt_fit": r(c05 * np.mean(tp.trf[sel] ** 0.5))})
    opp = np.where(tp.sf == 0, tp.ev["ba0"][tp.f], tp.ev["bb0"][tp.f])
    through = (tp.pf - opp) * tp.sign
    split = {}
    for name, sel in (("limit_at_touch", through == 0), ("limit_through", through >= 1), ("filled", tp.trf >= tp.qf),
                      ("partial", tp.trf < tp.qf)):
        mm = m & sel
        Xs = tp.trf[mm] ** 0.5
        split[name] = {"n": int(mm.sum()), "c": r(Xs @ j[mm] / (Xs @ Xs)) if mm.sum() else None}
    cum = tp.impact_path(c05, 0.5)
    imp = tp.sign * c05 * tp.trf ** 0.5
    pre = tp.centre(tf - W, tf)
    perm = []
    for h in (0.1, 1, 5, 30, 60, 300):
        post = tp.centre(tf + h, tf + h + W)
        idx = np.searchsorted(tf, tf + h + W / 2, "right")
        others = cum[idx] - cum[np.arange(len(tf)) + 1]
        res = (post - pre - others) * tp.sign
        mm = (prev_gap > W) & ~np.isnan(res)
        row = {"h": h}
        for lo, hi in ((0, 30), (30, 120), (120, 500), (500, 10**9)):
            sel = mm & (tp.qf > lo) & (tp.qf <= hi)
            row[f"{lo}-{hi}"] = [r(res[sel].mean(), 3), r(np.abs(imp[sel]).mean(), 3), r(res[sel].std() / np.sqrt(sel.sum()), 3)]
        perm.append(row)
    return {"isolated_n": int(m.sum()), "noise_var": r(noise), "best": best, "c_sqrt_traded": r(c05, 5),
            "scan": scan, "by_size": table, "split": split, "permanence_own_left_fit_se": perm}


def gmm1d(x, K, iters=200):
    """A 1-D Gaussian mixture by EM; returns weights, means, sds, the log-likelihood and the hard labels."""
    mu = np.quantile(x, (np.arange(K) + 0.5) / K)
    sd = np.full(K, x.std() / K + 1e-3)
    w = np.full(K, 1.0 / K)
    for _ in range(iters):
        lp = np.log(w) - 0.5 * ((x[:, None] - mu) / sd) ** 2 - np.log(sd) - 0.5 * np.log(2 * np.pi)
        mx = lp.max(1, keepdims=True)
        resp = np.exp(lp - mx)
        ll = float((mx[:, 0] + np.log(resp.sum(1))).sum())
        resp /= resp.sum(1, keepdims=True)
        nk = resp.sum(0) + 1e-9
        w, mu = nk / len(x), (resp * x[:, None]).sum(0) / nk
        sd = np.sqrt((resp * (x[:, None] - mu) ** 2).sum(0) / nk) + 1e-3
    order = np.argsort(mu)
    labels = np.argsort(order)[resp.argmax(1)]
    return w[order], mu[order], sd[order], ll, labels


def measure_exogenous(tp: Tape, c: float) -> tuple[dict, np.ndarray, np.ndarray]:
    cum = tp.impact_path(c, 0.5)
    g = tp.grid
    P_g = cum[np.searchsorted(tp.tf, g, "right")]
    R = tp.C - P_g
    out = {"intervals": []}
    for h in (1, 5, 30, 60, 300):
        n = int(round(h / STEP))
        D = tp.C[n::n] - tp.C[:-n:n]
        P = P_g[n::n] - P_g[:-n:n]
        ok = ~np.isnan(D)
        D, P = D[ok], P[ok]
        res = D - P
        out["intervals"].append({"h": h, "var_D": r(D.var(), 3), "var_P": r(P.var(), 3), "var_resid": r(res.var(), 3),
                                 "slope_D_on_P": r(P @ D / (P @ P), 3), "exo_var_per_s": r(res.var() / h)})
    n1 = int(round(1 / STEP))
    R1 = R[n1::n1] - R[:-n1:n1]
    R1 = R1[~np.isnan(R1)]
    var = R1.var()
    out["resid_1s"] = {"var": r(var, 3), "kurtosis": r(((R1 - R1.mean()) ** 4).mean() / var ** 2, 1),
                       "abs_q50_q90_q99_q999": [r(v, 2) for v in np.quantile(np.abs(R1), [0.5, 0.9, 0.99, 0.999])],
                       "var_share_steps_2plus": r(np.sum(R1[np.abs(R1) >= 2] ** 2) / np.sum(R1 ** 2), 3),
                       "var_share_steps_5plus": r(np.sum(R1[np.abs(R1) >= 5] ** 2) / np.sum(R1 ** 2), 3)}
    nb = len(R1) // 60
    rv = (R1[: nb * 60] ** 2).reshape(nb, 60).sum(1)
    lrv = np.log(rv + 1e-2)
    out["rv60"] = {"quantiles_5_25_50_75_95": [r(v, 2) for v in np.quantile(rv, [0.05, 0.25, 0.5, 0.75, 0.95])],
                   "log_acf_lags_1_2_5_10": [r(np.corrcoef(lrv[:-L], lrv[L:])[0, 1], 3) for L in (1, 2, 5, 10)]}
    lo = g[0] + n1 * STEP
    bins = (lo, lo + nb * 60)
    fl = np.histogram(tp.tf, bins=nb, range=bins, weights=tp.trf)[0]
    fn = np.histogram(tp.tf, bins=nb, range=bins)[0]
    gn = np.histogram(np.r_[tp.tb, tp.ta], bins=nb, range=bins)[0]
    out["rv60_corr"] = {"F_lots": r(np.corrcoef(rv, fl)[0, 1], 3), "F_count": r(np.corrcoef(rv, fn)[0, 1], 3),
                        "G_count": r(np.corrcoef(rv, gn)[0, 1], 3)}
    fits = []
    for K in (1, 2, 3):
        w, mu, sd, ll, lab = gmm1d(lrv, K)
        bic = -2 * ll + (3 * K - 1) * np.log(len(lrv))
        runs = np.diff(np.flatnonzero(np.r_[True, lab[1:] != lab[:-1], True]))
        states = []
        for s_ in range(K):
            blk = np.flatnonzero(lab == s_)
            lab_runs = [len(x) for x in np.split(blk, np.flatnonzero(np.diff(blk) > 1) + 1)] if len(blk) else []
            states.append({"share": r(w[s_], 3), "rv60_median": r(np.exp(np.median(lrv[lab == s_])) if (lab == s_).any() else None, 2),
                           "mean_run_blocks": r(np.mean(lab_runs), 2) if lab_runs else None})
        fits.append({"K": K, "bic": r(bic, 1), "states": states, "labels": lab, "mean_run": r(runs.mean(), 2)})
    best = min(fits, key=lambda d: d["bic"])
    out["regimes"] = [{k: v for k, v in f_.items() if k != "labels"} for f_ in fits]
    out["regimes_best_K"] = best["K"]
    labels = fits[1]["labels"] if best["K"] == 1 else best["labels"]
    return out, R, np.repeat(labels, 60), (lo, nb)


def regime_stats(tp: Tape, labels60, span, c_all) -> list:
    """Per regime (the mixture's labels on 60-s blocks): the rates, insert width, 1-tick share, impact c, exo var/s."""
    lo, nb = span
    blk_f = ((tp.tf - lo) // 60).astype(int)
    blk_g = ((np.r_[tp.tb, tp.ta] - lo) // 60).astype(int)
    blk_grid = ((tp.grid - lo) // 60).astype(int)
    lab = labels60[::60]
    out = []
    W = 0.10
    gap = np.diff(tp.tf)
    iso = (np.r_[np.inf, gap] > W) & (np.r_[gap, np.inf] > 0.03 + W)
    j = (tp.centre(tp.tf + 0.03, tp.tf + 0.03 + W) - tp.centre(tp.tf - W, tp.tf)) * tp.sign
    eb, _ = win_mean(tp.pb, tp.tb, tp.grid - 0.5, tp.grid)
    ea, _ = win_mean(tp.pa, tp.ta, tp.grid - 0.5, tp.grid)
    width = ea - eb
    cum = tp.impact_path(c_all, 0.5)
    P_g = cum[np.searchsorted(tp.tf, tp.grid, "right")]
    R = tp.C - P_g
    dR = np.r_[np.nan, R[10:] - R[:-10]][:: 1]
    for s_ in sorted(set(lab.tolist())):
        blocks = np.flatnonzero(lab == s_)
        bset = np.zeros(nb + 2, bool)
        bset[blocks] = True
        fin = bset[np.clip(blk_f, 0, nb + 1)] & (blk_f >= 0) & (blk_f < nb)
        gin = bset[np.clip(blk_g, 0, nb + 1)] & (blk_g >= 0) & (blk_g < nb)
        grid_in = bset[np.clip(blk_grid, 0, nb + 1)] & (blk_grid >= 0) & (blk_grid < nb)
        secs = 60.0 * len(blocks)
        mm = iso & fin & ~np.isnan(j)
        X = tp.trf[mm] ** 0.5
        step = np.flatnonzero(grid_in)
        step = step[step + 10 < len(R)]
        d1 = R[step + 10] - R[step]
        out.append({"state": int(s_), "blocks": int(len(blocks)), "F_per_s": r(fin.sum() / secs, 3), "G_per_s": r(gin.sum() / secs, 2),
                    "F_lots_per_s": r(tp.trf[fin].sum() / secs, 1), "insert_width": r(np.nanmean(width[grid_in]), 3),
                    "one_tick_share": r(np.nanmean(tp.spread_g[grid_in] == 1), 3), "c_sqrt": r(X @ j[mm] / (X @ X), 5) if mm.sum() > 20 else None,
                    "exo_var_per_s": r(np.nanvar(d1), 3)})
    return out


def measure_jumps(tp: Tape, R: np.ndarray, J: float) -> tuple[dict, np.ndarray, np.ndarray]:
    g = tp.grid
    D2 = R[2:] - R[:-2]
    hit = np.flatnonzero(np.abs(D2) >= J)
    groups = []
    for i in hit:
        if groups and i - groups[-1][1] < int(1.0 / STEP):
            groups[-1][1] = i
        else:
            groups.append([i, i])
    if not groups:
        return {"n": 0, "per_1000s": 0.0}, np.array([]), np.array([])
    i0 = np.array([a for a, _ in groups])
    i1 = np.array([b for _, b in groups])
    pre, post = np.clip(i0 - 3, 0, len(R) - 1), np.clip(i1 + 7, 0, len(R) - 1)
    size = R[post] - R[pre]
    t0 = g[i0]
    qs = [0.1, 0.25, 0.5, 0.75, 0.9, 0.99]
    out = {"n": len(t0), "per_1000s": r(1000 * len(t0) / tp.dur, 2), "threshold": J,
           "abs_size_quantiles_10_25_50_75_90_99": [r(v, 1) for v in np.quantile(np.abs(size), qs)],
           "abs_size_hist_0_3_5_10_20_50_inf": np.histogram(np.abs(size), [0, 3, 5, 10, 20, 50, 1e9])[0].tolist(),
           "up_share": r((size > 0).mean(), 3), "duration_q50_q90": [r(v, 2) for v in np.quantile(g[i1] - t0, [0.5, 0.9])]}
    if len(t0) > 2:
        gaps = np.diff(t0)
        ss = np.sign(size)
        out.update({"gap_quantiles_10_25_50_75_90": [r(v, 1) for v in np.quantile(gaps, qs[:5])], "gap_cv": r(gaps.std() / gaps.mean(), 2),
                    "sign_same_as_previous": r(np.mean(ss[1:] == ss[:-1]), 3)})
    nblk = int(tp.dur // 500)
    out["per_500s"] = np.histogram(t0, bins=nblk, range=(0, 500 * nblk))[0].tolist()
    out["persistence_median_share_kept"] = {h: r(np.median((R[np.clip(i1 + int(h / STEP), 0, len(R) - 1)] - R[pre]) / size), 3)
                                            for h in (1, 5, 30, 60)}
    # precursors
    eb, _ = win_mean(tp.pb, tp.tb, g - 0.5, g)
    ea, _ = win_mean(tp.pa, tp.ta, g - 0.5, g)
    width = ffill(ea - eb)
    ev = tp.ev
    ob = np.where(ev["bb0"][tp.gb] > 0, ev["bb0"][tp.gb] - tp.pb, 0)
    oa = np.where(ev["ba0"][tp.ga] > 0, tp.pa - ev["ba0"][tp.ga], 0)
    db, nb_ = win_mean((ob >= 3).astype(float), tp.tb, g - 0.5, g)
    da, na_ = win_mean((oa >= 3).astype(float), tp.ta, g - 0.5, g)
    deep = ffill((db * nb_ + da * na_) / (nb_ + na_))
    first = np.r_[np.inf, np.diff(t0)] > 30
    out["first_after_30s_quiet"] = int(first.sum())
    lags = (-60, -30, -10, -5, -3, -2, -1, -0.5, -0.2, 0, 0.3, 1, 3)
    prof = {}
    for name, X in (("spread", tp.spread_g), ("insert_width", width), ("deep_insert_share", deep)):
        prof[name] = {"base": r(np.nanmean(X[g > 70]), 3)}
        for tag, sel in (("all", np.ones(len(t0), bool)), ("first", first)):
            if sel.any():
                prof[name][tag] = {L: r(np.nanmean(tp.at(X, t0[sel] + L)), 3) for L in lags}
    out["precursor_profile"] = prof
    onset = np.zeros(len(g), bool)
    onset[np.clip(np.searchsorted(g, t0), 0, len(g) - 1)] = True
    cs = np.r_[0, np.cumsum(onset)]
    hits = []
    for H in (1.0, 5.0):
        nh = int(H / STEP)
        idx = np.arange(len(g) - nh)
        fut = cs[idx + 1 + nh] - cs[idx + 1] > 0
        lastj = np.searchsorted(t0, g[idx], "right") - 1
        clean = np.where(lastj >= 0, g[idx] - t0[np.clip(lastj, 0, None)], np.inf) > 10
        base = fut[clean].mean()
        for name, X in (("spread", tp.spread_g), ("insert_width", width), ("deep_insert_share", deep)):
            Xi = X[idx]
            for qq in (0.9, 0.97, 0.99, 0.999):
                thr = float(np.nanquantile(Xi[clean], qq))
                sig = (Xi >= thr) & clean
                if not sig.any():
                    continue
                hits.append({"within_s": H, "feature": name, "quantile": qq, "threshold": r(thr, 3), "time_share": r(sig.mean(), 4),
                             "p_jump": r(fut[sig].mean(), 3), "base": r(base, 4), "lift": r(fut[sig].mean() / max(base, 1e-9), 1),
                             "share_of_jumps_flagged": r((fut & sig).sum() / max(1, (fut & clean).sum()), 3)})
    out["hit_rates"] = hits
    # direction
    ss = np.sign(size)
    feats = {}
    for lo_, hi_, tag in ((-5, -0.3, "5s"), (-1, -0.3, "1s"), (-0.3, -0.05, "0.3s")):
        L, H = t0 + lo_, t0 + hi_
        feats[f"F_signed_lots_{tag}"] = wsum(tp.trf * tp.sign, tp.tf, L, H)
        feats[f"G_bid_minus_ask_{tag}"] = wsum(np.ones(len(tp.tb)), tp.tb, L, H) - wsum(np.ones(len(tp.ta)), tp.ta, L, H)
        cb = (ev["kind"] == C) & (ev["side"] == 0) & (ev["c_rem"] > 0)
        ca = (ev["kind"] == C) & (ev["side"] == 1) & (ev["c_rem"] > 0)
        feats[f"cancel_bid_minus_ask_{tag}"] = wsum(np.ones(cb.sum()), tp.t[cb], L, H) - wsum(np.ones(ca.sum()), tp.t[ca], L, H)
    feats["latent_drift_5s"] = R[np.clip(i0 - 3, 0, None)] - R[np.clip(i0 - 50, 0, None)]
    feats["latent_drift_60s"] = R[np.clip(i0 - 3, 0, None)] - R[np.clip(i0 - 600, 0, None)]
    feats["centre_minus_mid"] = tp.C[np.clip(i0 - 3, 0, None)] - tp.mid_g[np.clip(i0 - 3, 0, None)]
    feats["previous_jump_sign"] = np.r_[0, ss[:-1]]
    direc = {}
    for key, x in feats.items():
        ok = ~np.isnan(x) & (x != 0)
        if ok.sum() > 10 and np.std(x[ok]) > 0:
            direc[key] = {"corr": r(np.corrcoef(ss[ok], x[ok])[0, 1], 3), "p_agree": r(np.mean(np.sign(x[ok]) == ss[ok]), 3), "n": int(ok.sum())}
    out["direction"] = direc
    return out, t0, size


def first_wide_trades(tp: Tape) -> dict:
    """Trades at a 3+ tick spread: whether the aggressor's side is the latent's next move; the first after 0.3 s without
    trades, and what a taker finds on that side 5 ms later beyond the latent's level 0.3-0.8 s on."""
    ev = tp.ev
    t, k, s, tr = ev["t"], ev["kind"], ev["side"], ev["traded"]
    sp0 = np.where((ev["bb0"] > 0) & (ev["ba0"] > 0), ev["ba0"] - ev["bb0"], 99)
    out = {"trade_share_by_spread": {}}
    for v in (1, 2, 3, 4, 5):
        m = (k == F) & ((sp0 == v) if v < 5 else (sp0 >= 5) & (sp0 < 99))
        if m.any():
            out["trade_share_by_spread"][str(v) + ("+" if v == 5 else "")] = [int(m.sum()), r(np.mean(tr[m] > 0), 3)]
    fi = np.flatnonzero((k == F) & (tr > 0))
    wide = sp0[fi] >= 3

    def follow(ix):
        tw = t[ix]
        before = tp.centre(tw - 0.5, tw)
        after = tp.centre(tw + 0.3, tw + 0.8)
        mv = after - before
        sg = np.where(s[ix] == 0, 1, -1)
        ok = ~np.isnan(mv)
        return mv, sg, ok, after

    mv, sg, ok, _ = follow(fi[wide])
    out["wide_trades"] = {"n": int(wide.sum()), "p_side_is_next_move": r(np.mean(np.sign(mv[ok]) == sg[ok]), 3),
                          "signed_move_mean": r(np.mean(mv[ok] * sg[ok]), 2), "by_abs_move": {}}
    for lo, hi in ((0, 2), (2, 5), (5, 10), (10, 1e9)):
        m = ok & (np.abs(mv) >= lo) & (np.abs(mv) < hi)
        if m.any():
            out["wide_trades"]["by_abs_move"][f"{lo}-{hi:g}"] = [int(m.sum()), r(np.mean(np.sign(mv[m]) == sg[m]), 3)]
    prev_t = np.r_[-1e9, t[fi][:-1]]
    ff = fi[wide & (t[fi] - prev_t > 0.3)]
    mv, sg, ok, after = follow(ff)
    out["first_wide_trade"] = {"n": int(len(ff)), "per_1000s": r(1000 * len(ff) / tp.dur, 1),
                               "p_side_is_next_move": r(np.mean(np.sign(mv[ok]) == sg[ok]), 3),
                               "signed_move_mean_median": [r(np.mean(mv[ok] * sg[ok]), 2), r(np.median(mv[ok] * sg[ok]), 2)]}
    targets = sorted((t[ix] + 0.005, n) for n, ix in enumerate(ff) if not np.isnan(after[n]))
    book, res, ti = Book(), [], 0
    with tp.csv.open() as fh:
        next(fh)
        for line in fh:
            tt, op, oid, side, vol, price, life = line.rstrip("\n").split(",")
            tt = float(tt)
            while ti < len(targets) and tt >= targets[ti][0]:
                n = targets[ti][1]
                lvl = after[n]
                if s[ff[n]] == 0:
                    got = [(lvl - pp, v) for pp, v in book.vol[1].items() if pp < lvl]
                else:
                    got = [(pp - lvl, v) for pp, v in book.vol[0].items() if pp > lvl]
                lots = sum(v for _, v in got)
                value = sum(d * v for d, v in got)
                res.append((lots, value, value * min(1.0, 100 / lots) if lots else 0.0, sg[n] * mv[n]))
                ti += 1
            if op == "Insert":
                book.insert(oid, 0 if side == "B" else 1, int(price), int(vol), life == "F")
            else:
                book.cancel(oid)
    if res:
        a = np.array(res)
        out["first_wide_trade"]["stale_after_5ms"] = {"lots_mean_median": [r(a[:, 0].mean(), 1), r(np.median(a[:, 0]), 1)],
                                                      "value_total": r(a[:, 1].sum(), 0), "value_mean": r(a[:, 1].mean(), 1),
                                                      "value_capped_100_lots_total": r(a[:, 2].sum(), 0),
                                                      "episodes_with_value": int((a[:, 1] > 0).sum())}
    return out


def measure_placement(tp: Tape, rv_labels: np.ndarray, span) -> dict:
    ev = tp.ev
    out = {}
    cb = tp.centre(tp.tb - 0.1, tp.tb)
    ca = tp.centre(tp.ta - 0.1, tp.ta)
    off = np.r_[cb - tp.pb, tp.pa - ca]
    tt = np.r_[tp.tb, tp.ta]
    size = np.r_[ev["qty"][tp.gb], ev["qty"][tp.ga]]
    ok = ~np.isnan(off)

    def dist(sel):
        h = np.round(np.clip(off[sel & ok], -3, 8) * 2) / 2
        v, n = np.unique(h, return_counts=True)
        return {str(a): r(b / n.sum(), 4) for a, b in zip(v, n)}

    out["offset_from_centre"] = dist(np.ones(len(off), bool))
    out["offset_mean_sd"] = [r(np.mean(off[ok]), 3), r(np.std(off[ok]), 3)]
    lo, nb = span
    blk = ((tt - lo) // 60).astype(int)
    inb = (blk >= 0) & (blk < nb)
    lab = np.full(len(tt), -1)
    lab[inb] = rv_labels[::60][blk[inb]]
    out["offset_by_regime"] = {}
    for s_ in sorted(set(lab[inb].tolist())):
        sel = lab == s_
        out["offset_by_regime"][str(s_)] = {"mean": r(np.nanmean(off[sel]), 3), "sd": r(np.nanstd(off[sel]), 3),
                                            "share_2plus": r(np.mean(off[sel & ok] >= 2), 4), "dist": dist(sel)}
    sp = np.r_[ev["ba0"][tp.gb] - ev["bb0"][tp.gb], ev["ba0"][tp.ga] - ev["bb0"][tp.ga]]
    out["offset_by_spread"] = {str(v): {"n": int((sp == v).sum()), "mean": r(np.nanmean(off[sp == v]), 3)} for v in (1, 2, 3, 4)}
    out["size_by_offset"] = {}
    for a, b in ((-9, 0.25), (0.25, 0.75), (0.75, 1.25), (1.25, 1.75), (1.75, 2.75), (2.75, 99)):
        sel = ok & (off >= a) & (off < b)
        if sel.sum() > 10:
            out["size_by_offset"][f"{a}..{b}"] = {"share": r(sel.mean(), 4), "median": r(np.median(size[sel]), 1),
                                                  "mean": r(size[sel].mean(), 1), "p90": r(np.quantile(size[sel], 0.9), 1)}
    out["size_quantiles_10_50_90_99"] = [r(v, 1) for v in np.quantile(size, [0.1, 0.5, 0.9, 0.99])]
    # the offset from the own touch by spread (tape_gen's table)
    tbk = np.r_[ev["bb0"][tp.gb] - tp.pb, tp.pa - ev["ba0"][tp.ga]]
    out["offset_from_own_touch_by_spread"] = {}
    for v in (1, 2, 3):
        sel = (sp == v) if v < 3 else (sp >= 3)
        vals, cnt = np.unique(np.clip(tbk[sel], -3, 4), return_counts=True)
        out["offset_from_own_touch_by_spread"][str(v) + ("+" if v == 3 else "")] = {str(a): r(b / cnt.sum(), 4) for a, b in zip(vals, cnt)}
    gn = np.histogram(tt, bins=nb, range=(lo, lo + nb * 60))[0]
    out["insert_rate_by_regime"] = {str(s_): r(gn[rv_labels[::60] == s_].mean() / 60, 2) for s_ in sorted(set(rv_labels[::60].tolist()))}
    out["bid_share"] = r(len(tp.tb) / (len(tp.tb) + len(tp.ta)), 4)
    out["G_per_s"] = r((len(tp.tb) + len(tp.ta)) / tp.dur, 2)
    return out


def measure_cancels(tp: Tape, t0: np.ndarray, size: np.ndarray) -> dict:
    ev = tp.ev
    kc = ev["kind"] == C
    life = ev["c_life"][kc]
    ins = ev["c_ins"][kc]
    ok = ins >= 0
    out = {"cancels": int(kc.sum()), "G_orders": int(tp.gb.sum() + tp.ga.sum()), "cancels_with_known_order": int(ok.sum()),
           "lifetime_quantiles_10_25_50_75_90_99": [r(v, 3) for v in np.quantile(life[ok], [0.1, 0.25, 0.5, 0.75, 0.9, 0.99])],
           "lifetime_median_resting_vs_filled": [r(np.median(life[ok & (ev["c_rem"][kc] > 0)]), 3), r(np.median(life[ok & (ev["c_rem"][kc] == 0)]), 3)]}
    ti = ev["t"][ins[ok]]
    pi = ev["price"][ins[ok]].astype(float)
    si = ev["side"][ins[ok]]
    L = life[ok]
    ages = [0.0, 0.05, 0.1, 0.2, 0.3, 0.5, 0.8, 1.2, 2.0]
    haz = []
    for a, b in zip(ages[:-1], ages[1:]):
        alive = L > a
        x = tp.at(tp.C, ti[alive] + a)
        rel = np.where(si[alive] == 0, x - pi[alive], pi[alive] - x)  # ticks the order is on its own side of the latent
        died = L[alive] <= b
        stale, fresh = rel <= 0, rel >= 0.5
        haz.append({"age": f"{a}-{b}", "stale_share": r(stale.mean(), 4), "hazard_stale": r(died[stale].mean(), 4) if stale.any() else None,
                    "hazard_fresh": r(died[fresh].mean(), 4) if fresh.any() else None,
                    "ratio": r(died[stale].mean() / max(1e-9, died[fresh].mean()), 2) if stale.any() and fresh.any() else None})
    out["hazard_stale_vs_fresh"] = haz
    if len(t0):
        kt = ev["t"][kc & (ev["c_rem"] > 0)]
        ks = ev["side"][kc & (ev["c_rem"] > 0)]
        stale_side = np.where(size > 0, 1, 0)  # an up jump leaves the asks stale
        post = [np.sum((kt >= a) & (kt < a + 0.05) & (ks == sd)) for a, sd in zip(t0 - 0.1, stale_side)]
        other = [np.sum((kt >= a) & (kt < a + 0.05) & (ks == 1 - sd)) for a, sd in zip(t0 - 0.1, stale_side)]
        base = (ks.size / tp.dur) * 0.05 / 2
        out["resting_cancels_50ms_at_jump_onset_stale_vs_other_vs_base"] = [r(np.mean(post), 2), r(np.mean(other), 2), r(base, 2)]
    return out


def measure_flow(tp: Tape, R: np.ndarray) -> dict:
    tf = tp.tf
    gaps = np.diff(tf)
    out = {"F_per_s": r(len(tf) / tp.dur, 3), "interarrival_cv": r(gaps.std() / gaps.mean(), 3)}
    for w in (1, 10):
        cnt = np.histogram(tf, bins=int(tp.dur // w), range=(0, w * int(tp.dur // w)))[0]
        out[f"dispersion_{w}s"] = r(cnt.var() / cnt.mean(), 3)
        if w == 1:
            out["count_acf_1s_lags_1_2_5_10_60"] = [r(np.corrcoef(cnt[:-L], cnt[L:])[0, 1], 3) for L in (1, 2, 5, 10, 60)]
    out["p_side_same_as_previous"] = r(np.mean(tp.sf[1:] == tp.sf[:-1]), 4)
    out["buy_share"] = r(np.mean(tp.sf == 0), 4)
    past = tp.at(R, tf - 0.1) - tp.at(R, tf - 1.1)
    fut = tp.at(R, tf + 2.0) - tp.at(R, tf + 0.2)
    cm = tp.at(tp.C, tf - 0.05) - tp.at(tp.mid_g, tf - 0.05)
    for name, x in (("past_1s_exo_move", past), ("next_0.2_2s_exo_move", fut), ("centre_minus_mid", cm)):
        ok = ~np.isnan(x) & (x != 0)
        out[f"side_vs_{name}"] = {"corr": r(np.corrcoef(tp.sign[ok], x[ok])[0, 1], 4), "p_agree": r(np.mean(np.sign(x[ok]) == tp.sign[ok]), 4)}
    q = tp.qf
    out["size_quantiles_10_25_50_75_90_99"] = [r(v, 1) for v in np.quantile(q, [0.1, 0.25, 0.5, 0.75, 0.9, 0.99])]
    top = np.sort(q)[-max(10, len(q) // 20):]
    out["size_hill_alpha_top5pct"] = r(1 / np.mean(np.log(top / top[0])), 3)
    opp = np.where(tp.sf == 0, tp.ev["ba0"][tp.f], tp.ev["bb0"][tp.f])
    through = np.clip((tp.pf - opp) * tp.sign, -3, 10)
    v, n = np.unique(through, return_counts=True)
    out["limit_through_opposite_touch"] = {str(a): r(b / n.sum(), 4) for a, b in zip(v, n)}
    cen = tp.centre(tf - 0.1, tf)
    d = (tp.pf - cen) * tp.sign
    ok = ~np.isnan(d)
    h = np.round(np.clip(d[ok], -3, 10) * 2) / 2
    v, n = np.unique(h, return_counts=True)
    out["limit_minus_centre"] = {str(a): r(b / n.sum(), 4) for a, b in zip(v, n)}
    out["limit_minus_centre_median"] = r(np.median(d[ok]), 3)
    out["fill_share"] = r(np.mean(tp.trf >= tp.qf), 4)
    out["traded_zero_share"] = r(np.mean(tp.trf == 0), 4)
    return out


def identify(csv: Path, cache: Path | None, J: float) -> dict:
    ev = load(csv, cache)
    tp = Tape(ev, csv)
    out = {"tape": str(csv), "duration_s": r(tp.dur, 1), "events": int(len(ev["t"]))}
    sp = tp.spread_g[~np.isnan(tp.spread_g)]
    out["spread_time_share_1_2_3_4plus"] = [r(np.mean(sp == 1), 4), r(np.mean(sp == 2), 4), r(np.mean(sp == 3), 4), r(np.mean(sp >= 4), 4)]
    out["impact"] = measure_impact(tp)
    c = out["impact"]["c_sqrt_traded"]
    exo, R, labels, span = measure_exogenous(tp, c)
    out["exogenous"] = exo
    out["regime_stats"] = regime_stats(tp, labels, span, c)
    jumps, t0, size = measure_jumps(tp, R, J)
    out["jumps"] = jumps
    out["wide_trades"] = first_wide_trades(tp)
    out["placement"] = measure_placement(tp, labels, span)
    out["cancels"] = measure_cancels(tp, t0, size)
    out["flow"] = measure_flow(tp, R)
    return out


def show(d, indent=0, width=118):
    pad = "  " * indent
    for k, v in d.items():
        if k == "scan":  # the beta grid: JSON only
            continue
        if isinstance(v, dict) and len(json.dumps(v, default=str)) > width - len(pad) - len(str(k)):
            print(f"{pad}{k}:")
            show(v, indent + 1, width)
        elif isinstance(v, list) and v and isinstance(v[0], dict):
            print(f"{pad}{k}:")
            for row in v:
                print(f"{pad}  " + json.dumps(row, default=str))
        else:
            print(f"{pad}{k}: {json.dumps(v, default=str)}")


TABLE = [
    ("duration s", lambda d: d["duration_s"]),
    ("G inserts /s", lambda d: d["placement"]["G_per_s"]),
    ("F orders /s", lambda d: d["flow"]["F_per_s"]),
    ("F inter-arrival CV", lambda d: d["flow"]["interarrival_cv"]),
    ("F 10-s count dispersion", lambda d: d["flow"]["dispersion_10s"]),
    ("F size median", lambda d: d["flow"]["size_quantiles_10_25_50_75_90_99"][2]),
    ("F size p99", lambda d: d["flow"]["size_quantiles_10_25_50_75_90_99"][5]),
    ("F size Hill alpha", lambda d: d["flow"]["size_hill_alpha_top5pct"]),
    ("F limit - centre (median)", lambda d: d["flow"]["limit_minus_centre_median"]),
    ("F side vs next exo move corr", lambda d: d["flow"]["side_vs_next_0.2_2s_exo_move"]["corr"]),
    ("impact beta (best)", lambda d: d["impact"]["best"]["beta"]),
    ("impact c (sqrt traded)", lambda d: d["impact"]["c_sqrt_traded"]),
    ("estimator noise var", lambda d: d["impact"]["noise_var"]),
    ("own impact left at 60 s (120-500 lots)", lambda d: d["impact"]["permanence_own_left_fit_se"][4]["120-500"][0]),
    ("exogenous var /s (h 60 s)", lambda d: d["exogenous"]["intervals"][3]["exo_var_per_s"]),
    ("impact var /s (h 60 s)", lambda d: r(d["exogenous"]["intervals"][3]["var_P"] / 60, 4)),
    ("1-s residual kurtosis", lambda d: d["exogenous"]["resid_1s"]["kurtosis"]),
    ("var share of 2+ tick steps", lambda d: d["exogenous"]["resid_1s"]["var_share_steps_2plus"]),
    ("regimes (BIC best K)", lambda d: d["exogenous"]["regimes_best_K"]),
    ("RV60 q50 / q95", lambda d: f"{d['exogenous']['rv60']['quantiles_5_25_50_75_95'][2]} / {d['exogenous']['rv60']['quantiles_5_25_50_75_95'][4]}"),
    ("jumps per 1000 s", lambda d: d["jumps"]["per_1000s"]),
    ("jump |size| median / q90", lambda d: f"{d['jumps']['abs_size_quantiles_10_25_50_75_90_99'][2]} / {d['jumps']['abs_size_quantiles_10_25_50_75_90_99'][4]}" if d["jumps"]["n"] else "-"),
    ("jump gap CV", lambda d: d["jumps"].get("gap_cv", "-")),
    ("1/2/3/4+ tick spread share", lambda d: "/".join(str(x) for x in d["spread_time_share_1_2_3_4plus"])),
    ("insert offset from centre mean / sd", lambda d: "/".join(str(x) for x in d["placement"]["offset_mean_sd"])),
    ("G size median", lambda d: d["placement"]["size_quantiles_10_50_90_99"][1]),
    ("lifetime median s", lambda d: d["cancels"]["lifetime_quantiles_10_25_50_75_90_99"][2]),
    ("lifetime p99 s", lambda d: d["cancels"]["lifetime_quantiles_10_25_50_75_90_99"][5]),
    ("stale/fresh cancel hazard, age 0.1-0.2 s", lambda d: d["cancels"]["hazard_stale_vs_fresh"][2]["ratio"]),
    ("stale/fresh cancel hazard, age 0.3-0.5 s", lambda d: d["cancels"]["hazard_stale_vs_fresh"][4]["ratio"]),
]


def compare(paths: list[Path]) -> None:
    ds = [json.loads(p.read_text()) for p in paths]
    names = [p.stem for p in paths]
    w = max(len(n) for n, _ in TABLE)
    print(f"{'parameter':{w}s} " + " ".join(f"{n:>16s}" for n in names))
    for label, fn in TABLE:
        vals = []
        for d in ds:
            try:
                vals.append(str(fn(d)))
            except (KeyError, IndexError, TypeError):
                vals.append("-")
        print(f"{label:{w}s} " + " ".join(f"{v:>16s}" for v in vals))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="experiments.day.gen_identify", description=__doc__.split("\n")[0])
    parser.add_argument("tape", type=Path, nargs="?")
    parser.add_argument("--cache", type=Path, help="an .npz of the replay (written if missing, read if present)")
    parser.add_argument("--json", type=Path, help="write the report's numbers here")
    parser.add_argument("--jump", type=float, default=3.0, help="the 0.2-s exogenous move that counts as a jump (ticks)")
    parser.add_argument("--compare", type=Path, nargs="+", help="the parameter table over these reports' JSON")
    args = parser.parse_args(argv)
    if args.compare:
        compare(args.compare)
        return 0
    if not args.tape:
        parser.error("give a tape, or --compare JSON ...")
    with np.errstate(invalid="ignore", divide="ignore"):
        out = identify(args.tape, args.cache, args.jump)
    show(out)
    if args.json:
        args.json.write_text(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
