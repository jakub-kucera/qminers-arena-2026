"""Does fresh order evidence reach F5's latent filter too slowly, and does that cost decisions? (8 Nov, round 4;
docs/ROUND4_RESEARCH_REVIEW.md, section 3; IDEAS.md, "R4-FA").

Replays the tape through F5's filter (latent_filter.LatentFilter with F5's settings: W 8, rate 2, eps 0.01, impact x3,
depth 6; the same events as `latent_filter.replay`) and logs, per insert and per update:

- **the normalized predictive likelihood** sum_i p_i like_i / max_i like_i (1: the insert lands where the filter
  expected it; near eps / max: a surprise), and the posterior mass on states where the insert's likelihood is the
  floor eps (`floor mass`; >= 0.95 is a **surprise**), split into **aggressive** (a bid above the posterior's support,
  an ask below it: the order says lb moved towards it, the change-point case) and passive (deeper than k 0-2);
- **constant-likelihood updates**: the likelihood is eps on every grid state (the insert says lb is off the grid) or
  the same above eps on every state (uninformative);
- **depth exclusions** (an insert more than `depth` ticks from its own touch, behind it or inside the spread);
- **the mass at the grid's two edge states** after each update, and the mass folded onto an edge by a recentre or a
  trade's shift;
- **fresh bid / ask placement disagreement**: 0.5-s decayed means of the lb each fresh unclamped observed insert
  implies (a bid at p: p + E[k]; an ask: p - 1 - E[k]), bids minus asks, and their centre minus E[lb];
- **re-entries**: an order inserted earlier that enters the bot's visible window (public_depth 20 ticks from the
  best) because the touch moved away; the bot sees a new id there, F5 measures its depth from the previous touch.

Then (with `--pred`, F5's Rust prediction log, `RIDGE_PRED_LOG=<file> RIDGE_PRED_EXTRA=1 uv run python -m
arena.qsim_rust ridge_maker TAPE <F5's line> --threads 1`) it links the episodes to decisions on a 50-ms grid: at each
episode's onset, the evidence's direction x, F5's forecast and inventory, and the mid's move 0.4 / 1 / 5 s ahead;
whether F5 held against x when the mid then moved 2+ ticks with x (against the mirror case), and whether a take with x
was missed at a one-tick spread (F5's bar 0.25 + half the spread not met, room left, the mid 1.5+ ticks with x within
1 s); and the held-out partial R^2 of the episode features beyond F5's forecast (fit on the first 75%, scored on the last
25%, as forecast_gaps.py). Counts by L8's speed (QS_RATE's 5-s decayed |mid change| rate) and around jumps (3 s before
to 10 s after a 3-tick move within 200 ms). `proposal_flips`: what a change-point update would do to the take, F5's
forecast moved 0.25 / 0.5 / 1 tick towards (or away from) an aggressive surprise's evidence for ~0.35 s, the take grid
points it adds and drops at a one-tick spread and their 0.4 / 1-s value after the half spread. `--trades` (F5's full
logs' trades.csv) adds F5's own taker lots with and against x within 1 s of each onset and their 1-s markout.

Result (IDEAS.md, "R4-FA"): on round4_public and round3_public the fresh orders that contradict the filter lag it; the
mid moves against them, and moving the filter towards them drops better takes than it adds.

    uv run python -m experiments.filter.filter_audit TAPE --pred PREDLOG [--trades TRADES.csv] [--json OUT.json] [--set K=V ...]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

from experiments.filter.latent_filter import DEFAULTS, IMPACT, LatentFilter, STEP
from experiments.tape.tape_book import Book

F5 = {"W": 8, "rate": 2.0, "eps": 0.01, "pi0": 0.55, "pi1": 0.39, "pi2": 0.06, "impact_scale": 3.0, "depth": 6}
PUBLIC_DEPTH = 20  # the simulator's default public feed: prices within 20 ticks of each side's best
TAU = 0.5  # the fresh-evidence means' decay (s)
SURPRISE = 0.95  # floor mass at or above this: a surprise
BAR = 0.25  # F5's FT_EDGE
JUMP, JUMP_S = 3.0, 0.2
PRE, POST = 3.0, 10.0
HORIZONS = (0.4, 1.0, 5.0)
GKEYS = ("mid", "spread", "gap", "sd", "edge", "speed", "fb", "fa", "fwb", "fwa", "e", "folded", "surp_signed", "surp_n",
         "excl_inside", "surp_cum", "surp_dir_cum", "aggr_signed", "aggr_cum", "aggr_dir_cum", "pass_signed")


class AuditFilter(LatentFilter):
    """F5's filter, with the insert's diagnostics returned and the mass folded onto the edges counted."""

    folded = 0.0

    def recenter(self, bid):
        shift = bid - self.W - self.base
        if shift == 0 or self.p is None:
            return super().recenter(bid)
        if abs(shift) < self.n:
            p, n = self.p, self.n
            lost = sum(p[i] for i in range(n) if not 0 <= i - shift < n)
            self.folded += lost
        else:
            self.folded += 1.0
        super().recenter(bid)

    def trade(self, direction, lots):
        # the mass the shift pushes past the edge (the parent clamps it onto the edge state)
        m = self.impact_scale
        for top, value in IMPACT:
            if lots <= top:
                m *= value
                break
        whole, frac = int(m), m - int(m)
        p, n = self.p, self.n
        for i in range(n):
            v = p[i]
            if v:
                j = i + direction * whole
                k = j + direction
                self.folded += v * ((1.0 - frac) * (not 0 <= j < n) + frac * (not 0 <= k < n))
        super().trade(direction, lots)

    def likes(self, side, price, bid, ask):
        n, base, eps, pi, cum, K = self.n, self.base, self.eps, self.pi, self.cum, self.K
        out = [0.0] * n
        if side == 0:
            clamp = ask - 1
            if price >= clamp:
                for i in range(n):
                    d = base + i - clamp
                    out[i] = eps + (cum[d] if d < K else 1.0) if d >= 0 else eps
                return out, True, float(clamp)
            for i in range(n):
                k = base + i - price
                out[i] = eps + pi[k] if 0 <= k < K else eps
            return out, False, price + self.ek
        clamp = bid + 1
        if price <= clamp:
            for i in range(n):
                d = clamp - 1 - (base + i)
                out[i] = eps + (cum[d] if d < K else 1.0) if d >= 0 else eps
            return out, True, float(clamp - 1)
        for i in range(n):
            k = price - 1 - (base + i)
            out[i] = eps + pi[k] if 0 <= k < K else eps
        return out, False, price - 1 - self.ek

    def audit_insert(self, side, price, bid, ask):
        """Apply the insert; return (normalized likelihood, floor mass, constant kind, clamped, implied lb, E[lb] before)."""
        p, n, eps = self.p, self.n, self.eps
        like, clamped, implied = self.likes(side, price, bid, ask)
        e_before = self.base + sum(i * v for i, v in enumerate(p))
        total = 0.0
        floor = 0.0
        for i in range(n):
            v = p[i] * like[i]
            total += v
            if like[i] <= eps:
                floor += p[i]
            p[i] = v
        hi, lo = max(like), min(like)
        const = 0 if hi > lo else (1 if hi <= eps else 2)
        if total <= 0 or not math.isfinite(total):
            self.p = [1.0 / n] * n
            return 0.0, 1.0, const, clamped, implied, e_before
        self.loglik += math.log(total)
        self.n_obs += 1
        inv = 1.0 / total
        for i in range(n):
            p[i] *= inv
        return total / hi, floor, const, clamped, implied, e_before


def replay(path: Path, params: dict) -> dict:
    """Return per-insert arrays (`ins_*`) and 50-ms grid arrays (`g_*`), plus re-entry counts."""
    filt = AuditFilter(**{k: v for k, v in params.items() if k in F5 or k == "pi3"})
    filt.ek = sum(k * x for k, x in enumerate(filt.pi))
    depth = params.get("depth", 6)
    book = Book()
    I = {k: [] for k in ("t", "side", "dist", "obs", "nl", "floor", "const", "clamped", "disp", "edge", "speed")}
    G = {k: [] for k in ("t", "mid", "spread", "gap", "sd", "edge", "speed", "fb", "fa", "fwb", "fwa", "e", "folded",
                         "surp_signed", "surp_n", "excl_inside", "surp_cum", "surp_dir_cum", "aggr_signed", "aggr_cum",
                         "aggr_dir_cum", "pass_signed")}
    re = {"reentries": 0, "reentries_within_depth_prev_touch": 0, "reentries_within_depth_new_touch": 0}
    next_t = STEP
    last_bb = last_ba = None
    speed = 0.0
    speed_t = None
    speed_mid = None
    fb = fa = fwb = fwa = 0.0  # decayed sums (implied lb x weight) and weights, bids and asks
    ss = sn = sx = 0.0  # decayed signed surprises, surprise count, inside-spread exclusions
    sc = scd = 0.0  # cumulative surprises and their signed sum (undecayed)
    # aggressive surprises (a bid above where the filter puts lb's support, an ask below it: lb has moved towards the
    # crossing side) against passive ones (a bid deeper than k 0-2 behind lb, an ask deeper than k 0-2 above it)
    ags = agc = agd = pss = 0.0
    row = None
    dec_t = 0.0
    vis = [None, None]  # the visible window's far bound per side (bids: lowest visible price; asks: highest)

    def decay(t):
        nonlocal fb, fa, fwb, fwa, ss, sn, sx, dec_t, ags, pss
        if t > dec_t:
            k = math.exp(-(t - dec_t) / TAU)
            fb *= k; fa *= k; fwb *= k; fwa *= k; ss *= k; sn *= k; sx *= k; ags *= k; pss *= k
            dec_t = t

    with path.open() as fh:
        next(fh)
        for line in fh:
            t, op, oid, side, vol, price, life = line.rstrip("\n").split(",")
            t = float(t)
            bb, ba = book.best
            while t >= next_t:
                if last_bb is not None and last_ba is not None and last_bb < last_ba and filt.p is not None:
                    decay(next_t)
                    mid = (last_bb + last_ba) / 2
                    e, sd = filt.moments()
                    row = (mid, last_ba - last_bb, e + 0.5 - mid, sd, filt.p[0] + filt.p[-1], speed, fb, fa, fwb, fwa, e,
                           filt.folded, ss, sn, sx, sc, scd, ags, agc, agd, pss)
                if row is not None:  # an invalid book carries the last valid row forward (a uniform grid)
                    G["t"].append(next_t)
                    for key, v in zip(GKEYS, row):
                        G[key].append(v)
                next_t += STEP
            if op == "Insert":
                sd_ = 0 if side == "B" else 1
                p_, q_ = int(price), int(vol)
                if life == "F":
                    fills = []
                    book.insert(oid, sd_, p_, q_, True, fills)
                    lots = sum(f[1] for f in fills)
                    if lots and filt.p is not None:
                        filt.advance(t)
                        filt.trade(1 if sd_ == 0 else -1, lots)
                elif bb is not None and ba is not None and bb < ba:
                    if filt.p is None:
                        filt.reset(bb)
                    dist = (bb - p_) if sd_ == 0 else (p_ - ba)  # > 0 behind the own touch, < 0 inside the spread
                    obs = abs(dist) <= depth
                    I["t"].append(t); I["side"].append(sd_); I["dist"].append(dist); I["obs"].append(obs)
                    I["speed"].append(speed)
                    if obs:
                        filt.advance(t)
                        filt.recenter(bb)
                        nl, floor, const, clamped, implied, e0 = filt.audit_insert(sd_, p_, bb, ba)
                        disp = implied - e0
                        decay(t)
                        if not clamped:
                            if sd_ == 0:
                                fb += implied; fwb += 1.0
                            else:
                                fa += implied; fwa += 1.0
                        if floor >= SURPRISE:
                            ss += 1.0 if disp > 0 else -1.0
                            sn += 1.0
                            sc += 1.0
                            scd += 1.0 if disp > 0 else -1.0
                            if (sd_ == 0) == (disp > 0):
                                ags += 1.0 if disp > 0 else -1.0
                                agc += 1.0
                                agd += 1.0 if disp > 0 else -1.0
                            else:
                                pss += 1.0 if disp > 0 else -1.0
                        I["nl"].append(nl); I["floor"].append(floor); I["const"].append(const)
                        I["clamped"].append(clamped); I["disp"].append(disp); I["edge"].append(filt.p[0] + filt.p[-1])
                    else:
                        if dist < 0:
                            decay(t)
                            sx += 1.0
                        for k in ("nl", "floor", "const", "clamped", "disp", "edge"):
                            I[k].append(np.nan)
                    book.insert(oid, sd_, p_, q_, False)
                else:
                    book.insert(oid, sd_, p_, q_, False)
            else:
                book.cancel(oid)
            nb, na = book.best
            # re-entries: the visible window's far edge moved outward (bids: the best fell; asks: the best rose)
            for s, best, prev_touch in ((0, nb, bb), (1, na, ba)):
                if best is None:
                    vis[s] = None
                    continue
                far = best - (PUBLIC_DEPTH - 1) if s == 0 else best + (PUBLIC_DEPTH - 1)
                old = vis[s]
                if old is not None and ((s == 0 and far < old) or (s == 1 and far > old)):
                    lo, hi = (far, old - 1) if s == 0 else (old + 1, far)
                    levels = book.levels[s]
                    for price_ in range(lo, hi + 1):
                        qd = levels.get(price_)
                        if not qd:
                            continue
                        c = sum(1 for e_ in qd if e_[1] > 0 and e_[0] != oid)
                        if c:
                            re["reentries"] += c
                            if prev_touch is not None and abs(price_ - prev_touch) <= depth:
                                re["reentries_within_depth_prev_touch"] += c
                            if abs(price_ - best) <= depth:
                                re["reentries_within_depth_new_touch"] += c
                vis[s] = far
            if nb is not None and na is not None and nb < na:
                mid = (nb + na) / 2
                if speed_t is not None:
                    speed = speed * math.exp(-max(0.0, t - speed_t) / 5.0) + abs(mid - speed_mid) / 5.0
                speed_t, speed_mid = t, mid
            last_bb, last_ba = nb, na
    out = {"ins_" + k: np.array(v, dtype=float) for k, v in I.items()}
    out.update({"g_" + k: np.array(v, dtype=float) for k, v in G.items()})
    out["reentry"] = re
    out["loglik_per_insert"] = filt.loglik / max(1, filt.n_obs)
    return out


def jump_windows(t: np.ndarray, mid: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Grid-time masks: 3 s before to the jump, and the jump to 10 s after (a 3-tick move within 200 ms)."""
    k = int(round(JUMP_S / STEP))
    mv = np.zeros(len(mid))
    mv[k:] = mid[k:] - mid[:-k]
    jt = t[np.abs(mv) >= JUMP]
    pre = np.zeros(len(t), bool)
    post = np.zeros(len(t), bool)
    for a in jt:
        pre[np.searchsorted(t, a - PRE):np.searchsorted(t, a)] = True
        post[np.searchsorted(t, a):np.searchsorted(t, a + POST)] = True
    return pre, post, jt


def label_times(times: np.ndarray, t: np.ndarray, mask: np.ndarray) -> np.ndarray:
    i = np.clip(np.searchsorted(t, times, "right") - 1, 0, len(t) - 1)
    return mask[i]


def speed_bucket(s: np.ndarray) -> np.ndarray:
    return np.digitize(s, [2.5, 5.0])  # 0 slow (F5 quotes), 1 2.5-5, 2 fast


def counts(a: dict, hours: float) -> dict:
    t = a["g_t"]
    pre, post, jt = jump_windows(t, a["g_mid"])
    it = a["ins_t"]
    ipre, ipost = label_times(it, t, pre), label_times(it, t, post)
    obs = a["ins_obs"] == 1
    sb = speed_bucket(a["ins_speed"])
    rep = {"hours": hours, "jumps": int(len(jt)), "jumps_merged_1s": int(1 + (np.diff(jt) > 1.0).sum()) if len(jt) else 0, "loglik_per_insert": a["loglik_per_insert"], "reentry": a["reentry"]}
    rows = {}
    dist = a["ins_dist"]
    surprise = obs & (a["ins_floor"] >= SURPRISE)
    aggr = surprise & ((a["ins_side"] == 0) == (a["ins_disp"] > 0))
    nl = a["ins_nl"]
    for name, sel in (("all", np.ones(len(it), bool)), ("slow<2.5", sb == 0), ("mid2.5-5", sb == 1), ("fast>=5", sb == 2),
                      ("pre_jump_3s", ipre), ("post_jump_10s", ipost), ("away_from_jumps", ~ipre & ~ipost)):
        o = obs & sel
        n_ins = int(sel.sum())
        rows[name] = {
            "inserts": n_ins, "observed": int(o.sum()),
            "excluded_behind": int((sel & ~obs & (dist > 0)).sum()), "excluded_inside": int((sel & ~obs & (dist < 0)).sum()),
            "excluded_share": float((sel & ~obs).sum() / max(1, n_ins)),
            "surprise_share_of_observed": float((surprise & sel).sum() / max(1, o.sum())),
            "surprises_per_hour": float((surprise & sel).sum() / hours),
            "aggressive_surprise_share_of_observed": float((aggr & sel).sum() / max(1, o.sum())),
            "aggressive_surprises_per_hour": float((aggr & sel).sum() / hours),
            "const_all_eps": int((o & (a["ins_const"] == 1)).sum()), "const_uninformative": int((o & (a["ins_const"] == 2)).sum()),
            "nl_mean": float(np.nanmean(nl[o])) if o.any() else float("nan"),
            "nl_q10": float(np.nanquantile(nl[o], 0.1)) if o.any() else float("nan"),
            "edge_mass_ge_0.05_share": float((a["ins_edge"][o] >= 0.05).mean()) if o.any() else float("nan"),
            "edge_mass_ge_0.2_share": float((a["ins_edge"][o] >= 0.2).mean()) if o.any() else float("nan"),
        }
    rep["inserts"] = rows
    # surprise runs: 2+ / 3+ surprises within 0.5 s, all one direction
    runs = {}
    for label, sel in (("", surprise), ("aggressive_", aggr)):
        runs.update(surprise_runs(it[sel], np.sign(a["ins_disp"][sel]), hours, label))
    rep["surprise_runs"] = runs
    return grid_counts(a, rep, hours, t, pre, post)


def surprise_runs(st, sd, hours, label):
    runs = {}
    for need in (2, 3, 5):
        n = 0
        j = 0
        last_end = -1.0
        for i in range(len(st)):
            while st[i] - st[j] > TAU:
                j += 1
            if i - j + 1 >= need and np.all(sd[j:i + 1] == sd[i]) and st[i] > last_end + 1.0:
                n += 1
                last_end = st[i]
        runs[f"{label}runs_{need}plus_per_hour"] = n / hours
    return runs


def grid_counts(a, rep, hours, t, pre, post):
    # the grid: edge mass, fresh disagreement and the fresh centre's distance from E[lb]
    fwb, fwa = a["g_fwb"], a["g_fwa"]
    ok = (fwb > 0.3) & (fwa > 0.3)
    ib = np.where(fwb > 0, a["g_fb"] / np.maximum(fwb, 1e-12), np.nan)
    ia = np.where(fwa > 0, a["g_fa"] / np.maximum(fwa, 1e-12), np.nan)
    dis = np.where(ok, ib - ia, np.nan)
    cen = np.where(ok, 0.5 * (ib + ia) - a["g_e"], np.nan)
    gs = speed_bucket(a["g_speed"])
    grid = {}
    for name, sel in (("all", np.ones(len(t), bool)), ("slow<2.5", gs == 0), ("mid2.5-5", gs == 1), ("fast>=5", gs == 2),
                      ("pre_jump_3s", pre), ("post_jump_10s", post), ("away_from_jumps", ~pre & ~post)):
        grid[name] = {"time_share": float(sel.mean()),
                      "edge_ge_0.05": float((a["g_edge"][sel] >= 0.05).mean()),
                      "edge_ge_0.2": float((a["g_edge"][sel] >= 0.2).mean()),
                      "both_sides_fresh": float(ok[sel].mean()),
                      "abs_disagree_ge_1": float((np.abs(dis[sel]) >= 1).sum() / max(1, ok[sel].sum())),
                      "abs_disagree_ge_2": float((np.abs(dis[sel]) >= 2).sum() / max(1, ok[sel].sum())),
                      "abs_centre_minus_E_ge_1": float((np.abs(cen[sel]) >= 1).sum() / max(1, ok[sel].sum())),
                      "abs_centre_minus_E_ge_2": float((np.abs(cen[sel]) >= 2).sum() / max(1, ok[sel].sum()))}
    rep["grid"] = grid
    fold = np.diff(a["g_folded"], prepend=0.0)
    rep["folded_mass_per_hour"] = float(fold.sum() / hours)
    rep["folded_ge_0.05_steps_per_hour"] = float((fold >= 0.05).sum() / hours)
    a["g_dis"], a["g_cen"], a["g_pre"], a["g_post"], a["g_fold"] = dis, cen, pre, post, fold
    return rep


def ols(X, y):
    return np.linalg.lstsq(X, y, rcond=None)[0]


def link(a: dict, pl: np.ndarray, hours: float, trades=None) -> dict:
    """Episodes against F5's decisions on the 50-ms grid."""
    t, mid = a["g_t"], a["g_mid"]
    n = len(t)
    pt = pl[:, 0] / 1e6
    i = np.searchsorted(pt, t, "right") - 1
    have = i >= 0
    ii = np.clip(i, 0, len(pt) - 1)
    pred = np.where(have, pl[ii, 2], np.nan)
    inv = np.where(have, pl[ii, 5], np.nan)
    rgap = np.where(have, pl[ii, 6], np.nan)
    spread = a["g_spread"]
    ys = {}
    for h in HORIZONS:
        k = int(round(h / STEP))
        y = np.full(n, np.nan)
        y[:-k] = mid[k:] - mid[:-k]
        ys[h] = y
    # the strongest move within (0.4 s, 5 s]: max and min of mid over the window minus mid now
    k0, k1 = int(round(0.4 / STEP)), int(round(5.0 / STEP))
    hi = np.full(n, np.nan)
    lo = np.full(n, np.nan)
    from numpy.lib.stride_tricks import sliding_window_view
    w = sliding_window_view(mid, k1 - k0 + 1)  # w[j] = mid[j .. j + k1 - k0]
    m = len(w)
    hi[:m - k0] = w[k0:].max(1) - mid[:m - k0]
    lo[:m - k0] = w[k0:].min(1) - mid[:m - k0]
    k1s = int(round(1.0 / STEP))
    w1 = sliding_window_view(mid, k1s)
    hi1 = np.full(n, np.nan)
    lo1 = np.full(n, np.nan)
    hi1[:len(w1) - 1] = w1[1:].max(1) - mid[:len(w1) - 1]
    lo1[:len(w1) - 1] = w1[1:].min(1) - mid[:len(w1) - 1]
    sanity = {"corr_offline_gap_vs_rust_gap": float(np.corrcoef(np.nan_to_num(rgap), np.clip(a["g_gap"], -5, 5))[0, 1])}
    valid = have & np.isfinite(ys[5.0]) & np.isfinite(hi) & (t >= 30)
    # episodes (state from events up to t), each with a direction x
    surp_new = np.diff(a["g_surp_cum"], prepend=0.0) > 0  # a surprise since the previous grid point
    ss = a["g_surp_signed"]
    ags = a["g_aggr_signed"]
    aggr_new = np.diff(a["g_aggr_cum"], prepend=0.0) > 0
    run2 = (np.abs(ss) >= 1.8) & surp_new
    run3 = (np.abs(ss) >= 2.7) & surp_new
    dis, cen = a["g_dis"], a["g_cen"]
    edge = a["g_edge"]
    gapx = a["g_gap"]
    eps = {
        "surprise": (surp_new, np.sign(np.diff(a["g_surp_dir_cum"], prepend=0.0))),
        "aggr_surprise": (aggr_new, np.sign(np.diff(a["g_aggr_dir_cum"], prepend=0.0))),
        "aggr_run2": ((np.abs(ags) >= 1.8) & aggr_new, np.sign(ags)),
        "aggr_run3": ((np.abs(ags) >= 2.7) & aggr_new, np.sign(ags)),
        "surprise_run2": (run2, np.sign(ss)),
        "surprise_run3": (run3, np.sign(ss)),
        "edge_mass_ge_0.05": (edge >= 0.05, np.sign(gapx)),
        "edge_mass_ge_0.2": (edge >= 0.2, np.sign(gapx)),
        "fold_ge_0.05": (a["g_fold"] >= 0.05, np.sign(gapx)),
        "disagree_ge_2": (np.nan_to_num(np.abs(dis)) >= 2, np.sign(np.nan_to_num(cen))),
        "centre_off_ge_1": (np.nan_to_num(np.abs(cen)) >= 1, np.sign(np.nan_to_num(cen))),
        "centre_off_ge_2": (np.nan_to_num(np.abs(cen)) >= 2, np.sign(np.nan_to_num(cen))),
        "excl_inside_ge_1": (a["g_excl_inside"] >= 1, np.sign(gapx)),
    }
    gs = speed_bucket(a["g_speed"])
    pre, post = a["g_pre"], a["g_post"]
    rep = {"sanity": sanity, "episodes": {}}
    need = BAR + 0.5
    one = spread == 1
    onsets = {}
    for name, (mask, x) in eps.items():
        mask = mask & valid & (x != 0)
        # onsets: the first grid point after 1 s without the episode
        idx = np.flatnonzero(mask)
        keep = []
        last = -1e9
        for j in idx:
            if t[j] - last >= 1.0:
                keep.append(j)
            last = t[j]
        on = np.array(keep, dtype=int)
        if len(on) < 20:
            rep["episodes"][name] = {"onsets": int(len(on))}
            continue
        sx = x[on]
        onsets[name] = (on, sx)
        r = {"onsets": int(len(on)), "per_hour": len(on) / hours,
             "share_slow_mid_fast": [float((gs[on] == b).mean()) for b in range(3)],
             "share_pre_post_jump": [float(pre[on].mean()), float(post[on].mean())]}
        for h in HORIZONS:
            mv = ys[h][on] * sx
            r[f"move_with_x_{h}s"] = float(mv.mean())
            r[f"move_with_x_{h}s_se"] = float(mv.std() / math.sqrt(len(mv)))
        r["pred_with_x"] = float((pred[on] * sx).mean())
        r["rust_gap_with_x"] = float((rgap[on] * sx).mean())
        # the move beyond F5's forecast (slope from all valid points, first 75%)
        r["abs_move_1s_mean"] = float(np.abs(ys[1.0][on]).mean())
        # wrong position: F5 holds against x by 50+ lots and the mid then moves 2+ ticks with x within 0.4-5 s; mirror:
        # holds with x by 50+ and the mid moves 2+ against x
        up, dn = hi[on] * (sx > 0) - lo[on] * (sx < 0), -lo[on] * (sx > 0) + hi[on] * (sx < 0)
        against = inv[on] * sx <= -50
        withx = inv[on] * sx >= 50
        r["held_against_x_share"] = float(against.mean())
        r["wrong_pos_2t"] = int((against & (up >= 2)).sum())
        r["wrong_pos_2t_per_hour"] = float((against & (up >= 2)).sum() / hours)
        r["mirror_wrong_pos_2t"] = int((withx & (dn >= 2)).sum())
        r["P(move>=2 with x | held against)"] = float((up[against] >= 2).mean()) if against.any() else float("nan")
        r["P(move>=2 against x | held with)"] = float((dn[withx] >= 2).mean()) if withx.any() else float("nan")
        # missed take: one-tick spread, F5's forecast short of its bar with x, room with x, the mid 1.5+ ticks with x
        # within 1 s; mirror: the same against x
        o1 = one[on]
        no_take_x = pred[on] * sx < need
        room_x = inv[on] * sx < 100
        up1 = hi1[on] * (sx > 0) - lo1[on] * (sx < 0)
        dn1 = -lo1[on] * (sx > 0) + hi1[on] * (sx < 0)
        no_take_m = -pred[on] * sx < need
        room_m = -inv[on] * sx < 100
        r["missed_take_x"] = int((o1 & no_take_x & room_x & (up1 >= 1.5)).sum())
        r["missed_take_x_per_hour"] = float((o1 & no_take_x & room_x & (up1 >= 1.5)).sum() / hours)
        r["mirror_missed_take"] = int((o1 & no_take_m & room_m & (dn1 >= 1.5)).sum())
        rep["episodes"][name] = r
    # held-out partial R^2 beyond F5's forecast: the episode features (signed), fit on the first 75%, score the last 25%
    feats = {"surp_signed": ss, "aggr_signed": ags, "pass_signed": a["g_pass_signed"], "centre_minus_E": np.nan_to_num(cen), "disagree": np.nan_to_num(dis),
             "edge_x_gapsign": edge * np.sign(gapx), "gap_offline": np.clip(gapx, -5, 5),
             "centre_x_edge": np.nan_to_num(cen) * (edge >= 0.05), "surp_x_fast": ss * (gs == 2)}
    pv = valid & np.isfinite(pred)
    cut = t[pv][int(0.75 * pv.sum())]
    fit, test = pv & (t < cut), pv & (t >= cut)
    pr = {}
    for h in HORIZONS:
        y = ys[h]
        X0 = np.column_stack([np.ones(n), np.nan_to_num(pred)])
        b0 = ols(X0[fit], y[fit])
        sse0 = ((y[test] - X0[test] @ b0) ** 2).sum()
        row = {}
        for name, f in feats.items():
            X1 = np.column_stack([X0, f])
            b1 = ols(X1[fit], y[fit])
            sse1 = ((y[test] - X1[test] @ b1) ** 2).sum()
            row[name] = {"partial_r2_pct": 100 * float(1 - sse1 / sse0), "coef": float(b1[2])}
        X1 = np.column_stack([X0] + list(feats.values()))
        b1 = ols(X1[fit], y[fit])
        row["all"] = {"partial_r2_pct": 100 * float(1 - ((y[test] - X1[test] @ b1) ** 2).sum() / sse0)}
        pr[str(h)] = row
    rep["partial_r2_beyond_F5"] = pr
    # the surprises beyond the filter's own gap: [1, forecast, offline gap] against that plus the surprise features
    for h in HORIZONS:
        y = ys[h]
        X0 = np.column_stack([np.ones(n), np.nan_to_num(pred), feats["gap_offline"]])
        b0 = ols(X0[fit], y[fit])
        sse0 = ((y[test] - X0[test] @ b0) ** 2).sum()
        X1 = np.column_stack([X0, ss, ags, a["g_pass_signed"], np.nan_to_num(cen)])
        b1 = ols(X1[fit], y[fit])
        pr[str(h)]["surprises_beyond_gap"] = {"partial_r2_pct": 100 * float(1 - ((y[test] - X1[test] @ b1) ** 2).sum() / sse0)}
    # the change-point proposal's decisions: within ~0.35 s of an aggressive surprise (|decayed signed count| >= 0.5),
    # F5's forecast moved delta ticks towards the evidence (+1, what the proposal would do) or away from it (-1); at a
    # one-tick spread, the takes that appear or vanish, and the mid's move 0.4 / 1 s later signed by the take, less the
    # half spread paid (whole tape: nothing is fitted)
    xm = np.sign(ags) * (np.abs(ags) >= 0.5)
    base_take = np.where(np.abs(pred) > need, np.sign(pred), 0)
    room = lambda d: np.where(d > 0, inv < 100, inv > -100)
    prop = {}
    for toward in (1, -1):
        for delta in (0.25, 0.5, 1.0):
            new = np.nan_to_num(pred) + toward * delta * xm
            new_take = np.where(np.abs(new) > need, np.sign(new), 0)
            m = valid & one & (xm != 0)
            added = m & (new_take != 0) & (new_take != base_take) & room(new_take)
            dropped = m & (base_take != 0) & (new_take != base_take) & room(base_take)
            row = {"added_per_hour": float(added.sum() / hours), "dropped_per_hour": float(dropped.sum() / hours)}
            for h in (0.4, 1.0):
                row[f"added_value_{h}s"] = float((ys[h][added] * new_take[added]).mean() - 0.5) if added.any() else float("nan")
                row[f"dropped_value_{h}s"] = float((ys[h][dropped] * base_take[dropped]).mean() - 0.5) if dropped.any() else float("nan")
            prop[f"{'toward' if toward > 0 else 'away'}_{delta}"] = row
    rep["proposal_flips"] = prop
    rep["proposal_flips_base"] = {"one_tick_points_near_aggr_surprise_per_hour": float((valid & one & (xm != 0)).sum() / hours),
                                  "base_takes_there_per_hour": float((valid & one & (xm != 0) & (base_take != 0)).sum() / hours)}
    # F5's own takes after each episode (its full logs' trades.csv, the user's taker fills): lots with x and against x
    # within 1 s of the onset, and their markout against the mid 1 s after the fill
    if trades is not None and len(trades):
        tt, sg, qq, px = trades
        k1 = int(round(1.0 / STEP))
        gi = np.clip(np.searchsorted(t, tt, "right") - 1 + k1, 0, n - 1)
        mark = sg * (mid[gi] - px)
        own = {}
        for name, (on, sx) in onsets.items():
            lo = np.searchsorted(tt, t[on], "right")
            hi_ = np.searchsorted(tt, t[on] + 1.0, "right")
            w_lots = a_lots = 0.0
            w_mk = a_mk = 0.0
            for j in range(len(on)):
                sl = slice(lo[j], hi_[j])
                with_x = sg[sl] == sx[j]
                q = qq[sl]
                w_lots += q[with_x].sum()
                a_lots += q[~with_x].sum()
                w_mk += (q * mark[sl])[with_x].sum()
                a_mk += (q * mark[sl])[~with_x].sum()
            own[name] = {"lots_with_x_per_onset": w_lots / len(on), "lots_against_x_per_onset": a_lots / len(on),
                         "markout_1s_with_x": w_mk / w_lots if w_lots else float("nan"),
                         "markout_1s_against_x": a_mk / a_lots if a_lots else float("nan")}
        rep["own_takes_after_onsets"] = own
    return rep


def read_trades(path: Path):
    """F5's taker fills from its full logs' trades.csv: (time s, +1 buy / -1 sell, lots, price)."""
    tt, sg, qq, px = [], [], [], []
    with path.open() as fh:
        next(fh)
        for line in fh:
            ts, price, side, qty, _, _, towner, _ = line.rstrip("\n").split(",")
            if towner != "user":
                continue
            tt.append(int(ts) / 1e6)
            sg.append(1.0 if side == "B" else -1.0)
            qq.append(float(qty))
            px.append(float(price))
    return np.array(tt), np.array(sg), np.array(qq), np.array(px)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tape", type=Path)
    ap.add_argument("--pred", type=Path, help="F5's Rust prediction log (RIDGE_PRED_EXTRA columns)")
    ap.add_argument("--trades", type=Path, help="F5's full logs' trades.csv (exchange-simulator --log-dir without --no-logs)")
    ap.add_argument("--set", action="append", default=[], help="filter setting K=V (latent_filter's names)")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)
    params = dict(F5)
    for kv in args.set:
        k, v = kv.split("=", 1)
        if k not in DEFAULTS:
            ap.error(f"unknown setting {k}")
        params[k] = float(v)
    a = replay(args.tape, params)
    hours = (a["g_t"][-1] - a["g_t"][0]) / 3600
    rep = {"tape": str(args.tape), "params": params, "counts": counts(a, hours)}
    if args.pred:
        pl = np.loadtxt(args.pred, delimiter=",", dtype=np.float64)
        rep["decisions"] = link(a, pl, hours, read_trades(args.trades) if args.trades else None)
    text = json.dumps(rep, indent=1, default=float)
    if args.json:
        args.json.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
