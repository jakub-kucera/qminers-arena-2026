"""Where money can be made on a round-3 tape: a statistical map for strategies other than the forecast taker (8 Nov).

One tape replay (gen_identify's, cached), the latent filter's 50-ms samples (latent_filter, impact x3) and a second
replay recording, per aggressive (F) order, the touch it hit and the lots resting there; plus, optionally, a bot's
per-second PnL (`pnl.csv` from `arena-sim --log-dir` or the Arena simulator). Sections:

- **A. Where a bot earns** (`--pnl`): its per-second PnL summed by regime (gen_identify's 60-s Gaussian mixture, calm
  = the low-variance state), near jumps (from 3 s before an onset to 10 s after) or not, the spread at the second's
  start, 500-s segments; the share made in the best 1% of seconds; its PnL around jumps (mean over onsets).
- **B. Predictability by horizon** (0.1 / 0.4 / 1 / 5 / 30 / 120 s): the mid's move against the filter's gap, the
  backward insert-centre gap, the touch imbalance, signed F lots over the last 1 s, an online volatility proxy
  (the mid's 1-s squared moves over the last 60 s), time since the last jump and the previous jump's signed size;
  correlations on the first 75%, out-of-sample R² of an OLS on all of them on the last 25%, by regime.
  Jumps: the signed mid move from onset + 1 s to + h (continuation > 0, reversal < 0), by size. Minutes: variance
  ratios of the 1-s mid, autocorrelations of non-overlapping 30-600-s returns, and the next 60-600-s move against the
  mid's distance from its 300-s / 1,200-s EMA.
- **C. Maker economics:** a one-lot bid or ask resting at the touch the F order hits. "Front" fills on every F order
  that trades there; "back" (the queue's end) only when the F order takes the whole level; "level 2" when it takes
  the touch and reaches the next price. The markout, ticks a lot: fill price against the mid h s later (h 0 = before
  the trade: the half spread), by regime, by spread, by the F order's size; the fill rate and PnL a second of a
  two-sided one-lot touch quote.
- **D. Other structure:** the regime's block sequence and run lengths, jumps by regime, the last 120 s.
- **E. A jump-catch taker** (R3-S3's rule, on the 50-ms samples): the first 0.2-s mid move of 3+ ticks after 2 s
  without one, bought at the next sample's ask (sold at its bid) and closed at the far touch 0.5-10 s later: ticks a
  lot, by the filter's gap the move's way at entry and the spread.

    uv run python -m experiments.taker.r3_edges data/arena/round3/round3_public.csv --cache R3.npz [--pnl L8/pnl.csv] [--json OUT.json]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

from experiments.generator import gen_identify as gi
from experiments.filter import latent_filter as lf
from experiments.tape.tape_book import Book

HORIZONS = (0.1, 0.4, 1.0, 5.0, 30.0, 120.0)
MARK_H = (0.0, 1.0, 5.0, 30.0)


def r(x, n=3):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), n)


def f_replay(path: Path) -> dict:
    """Per F order that traded: time, F side, the touch price it hit, the lots resting there before, lots traded at
    that price, whether it reached the next price (and that price), its size and the spread before."""
    book = Book()
    out = {k: [] for k in ("t", "side", "touch", "depth", "at_touch", "next_px", "size", "spread")}
    with path.open() as fh:
        next(fh)
        for line in fh:
            t, op, oid, side, vol, price, life = line.rstrip("\n").split(",")
            if op == "Insert":
                sd = 0 if side == "B" else 1
                p, q = int(price), int(vol)
                if life == "F":
                    bb, ba = book.best
                    touch = ba if sd == 0 else bb
                    if touch is None or bb is None or ba is None:
                        book.insert(oid, sd, p, q, True)
                        continue
                    depth = book.depth(1 - sd, touch)
                    fills = []
                    book.insert(oid, sd, p, q, True, fills)
                    if not fills:
                        continue
                    at = sum(f[1] for f in fills if f[2] == touch)
                    beyond = [f[2] for f in fills if f[2] != touch]
                    out["t"].append(float(t))
                    out["side"].append(sd)
                    out["touch"].append(touch)
                    out["depth"].append(depth)
                    out["at_touch"].append(at)
                    out["next_px"].append(beyond[0] if beyond else 0)
                    out["size"].append(q)
                    out["spread"].append(ba - bb)
                else:
                    book.insert(oid, sd, p, q, False)
            else:
                book.cancel(oid)
    return {k: np.array(v) for k, v in out.items()}


def cached(path: Path | None, make):
    if path is not None and path.exists():
        z = np.load(path)
        return {k: z[k] for k in z.files}
    d = make()
    if path is not None:
        np.savez(path, **d)
    return d


class Ctx:
    """The tape's grid (gen_identify.Tape), its regime labels and jumps, the filter's samples and the F replay."""

    def __init__(self, csv: Path, cache: Path | None) -> None:
        ev = gi.load(csv, cache)
        self.tp = tp = gi.Tape(ev, csv)
        self.c = gi.measure_impact(tp)["c_sqrt_traded"]
        _, self.R, labels, span = gi.measure_exogenous(tp, self.c)
        self.lo, self.nb = span
        lab = labels[::60]
        # calm = the state with the lower realised variance of the 1-s residual
        n1 = int(round(1 / gi.STEP))
        R1 = self.R[n1::n1] - self.R[:-n1:n1]
        R1 = np.nan_to_num(R1)[: self.nb * 60]
        rv = (R1 ** 2).reshape(self.nb, 60).sum(1)
        means = {s: rv[lab == s].mean() for s in set(lab.tolist())}
        calm = min(means, key=means.get)
        self.vol_block = (lab != calm).astype(int)  # 1 volatile, per 60-s block from self.lo
        self.rv_block = rv
        _, self.t0, self.jsize = gi.measure_jumps(tp, self.R, 3.0)
        fpath = cache.with_name(cache.stem + "_filt.npy") if cache else None
        if fpath is not None and fpath.exists():
            self.rows = np.load(fpath)
        else:
            p = dict(lf.DEFAULTS)
            p["impact_scale"] = 3.0
            self.rows, _, _ = lf.replay(csv, p)
            if fpath is not None:
                np.save(fpath, self.rows)
        self.fr = cached(cache.with_name(cache.stem + "_f.npz") if cache else None, lambda: f_replay(csv))

    def regime_at(self, times):
        """1 volatile, 0 calm, -1 outside the labelled span."""
        b = np.floor((np.asarray(times) - self.lo) / 60).astype(int)
        ok = (b >= 0) & (b < self.nb)
        return np.where(ok, self.vol_block[np.clip(b, 0, self.nb - 1)], -1)

    def mid_at(self, times):
        return self.tp.at(self.tp.mid_g, np.asarray(times))

    def near_jump(self, times, before=3.0, after=10.0):
        t = np.asarray(times)
        if len(self.t0) == 0:
            return np.zeros(t.shape, bool)
        k = np.searchsorted(self.t0, t + before)  # first onset after t + before ... onset in [t - after, t + before]
        prev_on = self.t0[np.clip(k - 1, 0, len(self.t0) - 1)]
        return (k > 0) & (prev_on >= t - after)


def section_a(cx: Ctx, pnl_csv: Path) -> dict:
    rows = np.loadtxt(pnl_csv, delimiter=",", skiprows=1)
    ts, pnl = rows[:, 0], rows[:, 1]
    d = np.diff(pnl)
    t = ts[:-1]  # the second [t, t+1)
    reg = cx.regime_at(t + 0.5)
    near = cx.near_jump(t + 0.5)
    sp = cx.tp.at(cx.tp.spread_g, t + 0.01)
    out = {"total": r(pnl[-1], 0), "seconds": int(len(d))}
    out["by_regime"] = {name: {"pnl": r(d[reg == v].sum(), 0), "seconds": int((reg == v).sum()),
                               "per_s": r(d[reg == v].mean(), 1) if (reg == v).any() else None}
                        for name, v in (("calm", 0), ("volatile", 1), ("unlabelled", -1))}
    out["near_jump_-3s_+10s"] = {"pnl": r(d[near].sum(), 0), "seconds": int(near.sum()), "per_s": r(d[near].mean(), 1)}
    out["between_jumps"] = {"pnl": r(d[~near].sum(), 0), "seconds": int((~near).sum()), "per_s": r(d[~near].mean(), 1)}
    cross = {}
    for name, v in (("calm", 0), ("volatile", 1)):
        for tag, sel in (("near", near), ("between", ~near)):
            m = (reg == v) & sel
            cross[f"{name}_{tag}"] = {"pnl": r(d[m].sum(), 0), "seconds": int(m.sum()), "per_s": r(d[m].mean(), 1) if m.any() else None}
    out["regime_x_jump"] = cross
    out["by_spread_at_start"] = {}
    for lo_, hi_, tag in ((1, 1, "1"), (2, 2, "2"), (3, 99, "3+")):
        m = (sp >= lo_) & (sp <= hi_)
        out["by_spread_at_start"][tag] = {"pnl": r(d[m].sum(), 0), "seconds": int(m.sum()), "per_s": r(d[m].mean(), 1) if m.any() else None}
    seg = (t // 500).astype(int)
    out["by_500s"] = [r(d[seg == s].sum(), 0) for s in range(seg.max() + 1)]
    out["by_500s_volatile_share"] = [r(np.mean(reg[seg == s] == 1), 2) for s in range(seg.max() + 1)]
    srt = np.sort(d)[::-1]
    k = max(1, len(d) // 100)
    out["best_1pct_seconds_share"] = r(srt[:k].sum() / pnl[-1], 3)
    out["worst_1pct_seconds_share"] = r(srt[-k:].sum() / pnl[-1], 3)
    # around jumps: the mean PnL change from onset + a to onset + b (s), by size
    cum = np.r_[0, np.cumsum(d)]
    def window(a, b, sel):
        i = np.clip(np.floor(cx.t0[sel] + a).astype(int), 0, len(d))
        j = np.clip(np.floor(cx.t0[sel] + b).astype(int), 0, len(d))
        return r((cum[j] - cum[i]).sum(), 0)
    big = np.abs(cx.jsize) >= 5
    out["around_jumps_total"] = {f"{a}..{b}s": {"all": window(a, b, np.ones(len(big), bool)), "5plus": window(a, b, big)}
                                 for a, b in ((-3, 0), (0, 1), (1, 3), (3, 10), (10, 30))}
    out["jumps"] = int(len(cx.t0))
    return out


def ema(x, dt, tau):
    a = 1 - math.exp(-dt / tau)
    out = np.empty_like(x)
    acc = x[0]
    for i, v in enumerate(x):
        acc += a * (v - acc)
        out[i] = acc
    return out


def section_b(cx: Ctx) -> dict:
    rows = cx.rows
    step = float(np.median(np.diff(rows[:, 0])))
    t, mid, gap, imb, spread = rows[:, 0], rows[:, 1], rows[:, 2], rows[:, 4], rows[:, 5]
    tp = cx.tp
    # backward insert-centre gap (0.5 s), signed F lots and sqrt-impact over the last 1 s, online vol proxy
    eb, _ = gi.win_mean(tp.pb, tp.tb, t - 0.5, t)
    ea, _ = gi.win_mean(tp.pa, tp.ta, t - 0.5, t)
    cgap = gi.ffill((eb + ea) / 2) - mid
    cgap = np.nan_to_num(cgap)
    flow1 = gi.wsum(tp.trf * tp.sign, tp.tf, t - 1, t)
    imp1 = gi.wsum(tp.sign * np.sqrt(tp.trf), tp.tf, t - 1, t)
    n1 = int(round(1 / step))
    m1 = np.r_[np.zeros(n1), mid[n1:] - mid[:-n1]]
    cs = np.r_[0, np.cumsum(m1 ** 2)]
    nv = int(round(60 / step))
    idx = np.arange(len(t))
    vol60 = (cs[idx + 1] - cs[np.clip(idx + 1 - nv, 0, None)]) / (60.0 / 1.0) / max(1, n1)
    k = np.searchsorted(cx.t0, t, "right") - 1
    t0p, jsp = np.r_[-1e9, cx.t0], np.r_[0.0, cx.jsize]  # a sentinel jump before the tape
    since = np.minimum(t - t0p[k + 1], 999.0)
    prev = jsp[k + 1]
    reg = cx.regime_at(t)
    feats = {"filter_gap": gap, "centre_gap_0.5s": cgap, "touch_imbalance": imb, "F_lots_1s": flow1, "F_sqrt_impact_1s": imp1,
             "vol60_proxy": vol60, "log_since_jump": np.log1p(since), "prev_jump_size_x_decay": prev * np.exp(-since / 30.0),
             "spread": spread}
    n = len(t)
    cut = int(0.75 * n)
    out = {"samples": n, "step_s": r(step, 3), "horizons": {}}
    for h in HORIZONS:
        lag = int(round(h / step))
        ii = np.arange(n - lag)
        fut = mid[ii + lag] - mid[ii]
        tr, te = ii[ii < cut], ii[(ii >= cut)]
        res = {"sd_move": r(fut.std(), 3)}
        for name, x in feats.items():
            res[name] = r(np.corrcoef(x[tr], fut[tr])[0, 1], 3)
        X = np.column_stack([np.ones(n)] + [feats[k_] for k_ in feats] + [gap * (reg == 1), gap * np.abs(gap)])
        beta, *_ = np.linalg.lstsq(X[tr], fut[tr], rcond=None)
        e = fut[ii >= cut] - X[te] @ beta
        res["ols_r2_in"] = r(1 - np.var(fut[tr] - X[tr] @ beta) / np.var(fut[tr]), 4)
        res["ols_r2_out"] = r(1 - np.var(e) / np.var(fut[ii >= cut]), 4)
        for name, v in (("calm", 0), ("volatile", 1)):
            m = (reg[ii] == v)
            res[f"filter_gap_corr_{name}"] = r(np.corrcoef(gap[ii][m], fut[m])[0, 1], 3) if m.sum() > 100 else None
            res[f"sd_move_{name}"] = r(fut[m].std(), 3) if m.sum() > 100 else None
        # hit rate when the filter's gap is large
        big = np.abs(gap[ii]) >= 1.0
        res["gap_ge1_hit"] = r(np.mean(np.sign(fut[big]) == np.sign(gap[ii][big])), 3) if big.any() else None
        res["gap_ge1_mean_move_its_way"] = r(np.mean(fut[big] * np.sign(gap[ii][big])), 3) if big.any() else None
        out["horizons"][f"{h:g}s"] = res
    # post-jump drift: mid from onset + 1 s to + h, signed by the jump's sign
    sgn = np.sign(cx.jsize)
    m_on = cx.mid_at(cx.t0 - 0.3)
    m1s = cx.mid_at(cx.t0 + 1.0)
    pj = {"n": int(len(cx.t0)), "mid_move_onset-0.3_to_+1s_signed_mean": r(np.nanmean((m1s - m_on) * sgn), 2),
          "jump_size_abs_mean": r(np.mean(np.abs(cx.jsize)), 2)}
    for lo_, hi_, tag in ((3, 5, "3-5"), (5, 10, "5-10"), (10, 1e9, "10+"), (3, 1e9, "all")):
        sel = (np.abs(cx.jsize) >= lo_) & (np.abs(cx.jsize) < hi_)
        row = {"n": int(sel.sum())}
        if sel.sum() < 3:
            continue
        for h in (1, 5, 10, 30, 60, 120):
            x = (cx.mid_at(cx.t0[sel] + 1 + h) - m1s[sel]) * sgn[sel]
            x = x[~np.isnan(x)]
            row[f"+{h}s"] = [r(x.mean(), 2), r(x.mean() / (x.std() / math.sqrt(len(x))), 2) if len(x) > 2 else None]
        pj[f"size_{tag}_mean_t"] = row
    out["post_jump_drift"] = pj
    # minutes scale on a 1-s mid
    g1 = np.arange(math.ceil(t[0]), math.floor(t[-1]))
    m = cx.mid_at(g1)
    m = gi.ffill(m)
    r1 = np.diff(m)
    v1 = r1.var()
    vr = {}
    for kk in (10, 30, 60, 120, 300, 600):
        rk = m[kk:] - m[:-kk]
        vr[f"{kk}s"] = r(rk.var() / (kk * v1), 3)
    out["variance_ratio_1s_base"] = vr
    ac = {}
    for kk in (30, 60, 120, 300, 600):
        rk = np.diff(m[::kk])
        ac[f"{kk}s"] = [r(np.corrcoef(rk[:-1], rk[1:])[0, 1], 3), int(len(rk) - 1)]
    out["return_autocorr_nonoverlap"] = ac
    mr = {}
    for tau in (300.0, 1200.0):
        e_ = ema(m, 1.0, tau)
        dev = m - e_
        for H in (60, 300, 600):
            ii = np.arange(int(tau), len(m) - H)
            fut = m[ii + H] - m[ii]
            x = dev[ii]
            b = float(x @ fut / (x @ x))
            # non-overlapping t-stat
            jj = ii[:: H]
            cc = np.corrcoef(dev[jj], m[jj + H] - m[jj])[0, 1]
            mr[f"ema{int(tau)}_h{H}"] = {"corr": r(np.corrcoef(x, fut)[0, 1], 3), "slope": r(b, 3), "corr_nonoverlap": r(cc, 3), "n_nonoverlap": int(len(jj))}
    out["minutes_mean_reversion"] = mr
    out["price_range"] = [r(np.nanmin(m), 0), r(np.nanmax(m), 0), r(m[0], 0), r(m[-1], 0)]
    return out


def section_c(cx: Ctx) -> dict:
    fr = cx.fr
    t, sd, touch, depth, at, nxt, size, spr = (fr[k] for k in ("t", "side", "touch", "depth", "at_touch", "next_px", "size", "spread"))
    # maker side: an F buy (sd 0) fills a resting ask (maker sells); sign +1 for a maker buy
    msign = np.where(sd == 0, -1.0, 1.0)
    mid0 = (cx.tp.at(cx.tp.mid_g, t - 1e-4))
    reg = cx.regime_at(t)
    back = at >= depth
    lvl2 = nxt != 0
    dur = cx.tp.dur
    out = {"f_orders_trading": int(len(t))}
    def mk(price, sel):
        res = {"n": int(sel.sum()), "per_s": r(sel.sum() / dur, 3)}
        for h in MARK_H:
            m_h = mid0 if h == 0 else cx.mid_at(t + h)
            x = (m_h - price) * msign
            x = x[sel & ~np.isnan(x)]
            res[f"{h:g}s"] = r(x.mean(), 3) if len(x) else None
        return res
    groups = {"all": np.ones(len(t), bool), "calm": reg == 0, "volatile": reg == 1,
              "spread1": spr == 1, "spread2": spr == 2, "spread3+": spr >= 3,
              "calm_spread1": (reg == 0) & (spr == 1), "volatile_spread1": (reg == 1) & (spr == 1),
              "Fsize<=30": size <= 30, "Fsize31-120": (size > 30) & (size <= 120), "Fsize121-500": (size > 120) & (size <= 500), "Fsize>500": size > 500}
    near = cx.near_jump(t, 3.0, 10.0)
    groups["calm_far_from_jump"] = (reg == 0) & ~near
    groups["volatile_far_from_jump"] = (reg == 1) & ~near
    groups["near_jump"] = near
    out["front_touch"] = {g: mk(touch, s) for g, s in groups.items()}
    out["back_touch"] = {g: mk(touch, s & back) for g, s in groups.items()}
    p2 = np.where(sd == 0, touch + 1, touch - 1)  # one tick behind the touch
    out["level2"] = {g: mk(p2, s & lvl2) for g, s in groups.items()}
    # per second of each regime: a two-sided one-lot touch quote (front) and (back)
    secs = {0: 60.0 * np.sum(cx.vol_block == 0), 1: 60.0 * np.sum(cx.vol_block == 1)}
    pps = {}
    for name, v in (("calm", 0), ("volatile", 1)):
        for tag, sel in (("front", np.ones(len(t), bool)), ("back", back), ("level2", lvl2)):
            price = p2 if tag == "level2" else touch
            for h in (1.0, 5.0):
                x = (cx.mid_at(t + h) - price) * msign
                s_ = (reg == v) & sel & ~np.isnan(x)
                pps[f"{name}_{tag}_h{h:g}"] = r(x[s_].sum() / secs[v], 3)
    out["pnl_per_s_one_lot_two_sided"] = pps
    # online conditions at a 1-tick spread: the filter's gap the maker's way ("fav", ticks), and a jump flag (a 1-s mid
    # move of 3+ ticks in the last 10 s, from the 50-ms samples); a Q-lot quote at the front fills min(Q, lots there)
    rows = cx.rows
    k = np.clip(np.searchsorted(rows[:, 0], t) - 1, 0, len(rows) - 1)
    fav = rows[k, 2] * msign
    mid = rows[:, 1]
    n1 = int(round(1.0 / float(np.median(np.diff(rows[:, 0])))))
    m1 = np.r_[np.zeros(n1), np.abs(mid[n1:] - mid[:-n1])]
    big = (m1 >= 3).astype(float)
    cs = np.r_[0, np.cumsum(big)]
    w = 10 * n1
    idx = np.arange(len(mid))
    jflag = (cs[idx + 1] - cs[np.clip(idx + 1 - w, 0, None)] > 0)[k]
    cond = {}
    base = spr == 1
    for name, sel in (("spread1", base), ("spread1_no_jump_flag", base & ~jflag), ("spread1_fav>0", base & (fav > 0)),
                      ("spread1_fav<0", base & (fav < 0)), ("spread1_fav>0.5", base & (fav > 0.5)), ("spread1_fav<-0.5", base & (fav < -0.5)),
                      ("spread1_no_jump_flag_fav>0", base & ~jflag & (fav > 0)), ("spread1_no_jump_flag_calm", base & ~jflag & (reg == 0)),
                      ("spread1_no_jump_flag_volatile", base & ~jflag & (reg == 1))):
        row = {"fills": int(sel.sum()), "jump_flag_share": r(jflag[base].mean(), 3)} if name == "spread1" else {"fills": int(sel.sum())}
        for Q in (1, 10, 50):
            lots = np.minimum(Q, at).astype(float)
            for h in (1.0, 5.0):
                x = (cx.mid_at(t + h) - touch) * msign
                s_ = sel & ~np.isnan(x)
                row[f"Q{Q}_h{h:g}_per_lot"] = r((x[s_] * lots[s_]).sum() / max(1.0, lots[s_].sum()), 3)
                row[f"Q{Q}_h{h:g}_per_s"] = r((x[s_] * lots[s_]).sum() / dur, 2)
        cond[name] = row
    out["front_touch_online_conditions"] = cond
    # where the quote sits, by the gap: a one-lot fill's markout (ticks a lot, 1 / 5 s)
    place = {}
    for lab, price, b in (("touch_spread1", touch, spr == 1), ("touch_spread2", touch, spr == 2),
                          ("level2_spread1", p2, (spr == 1) & lvl2), ("back_spread1", touch, (spr == 1) & back)):
        for fl, sel in (("fav>0.6", fav > 0.6), ("fav>0", fav > 0), ("all", np.ones(len(t), bool))):
            row = {"n": int((b & sel).sum())}
            for h in (1.0, 5.0):
                x = (cx.mid_at(t + h) - price) * msign
                x = x[b & sel & ~np.isnan(x)]
                row[f"{h:g}s"] = r(x.mean(), 3) if len(x) else None
            place[f"{lab}_{fl}"] = row
    out["by_queue_place_and_gap"] = place
    return out


def section_d(cx: Ctx) -> dict:
    lab = cx.vol_block
    runs, cur, cnt = [], lab[0], 0
    for v in lab:
        if v == cur:
            cnt += 1
        else:
            runs.append((int(cur), cnt))
            cur, cnt = v, 1
    runs.append((int(cur), cnt))
    out = {"blocks_volatile_string": "".join("V" if v else "c" for v in lab),
           "volatile_share": r(lab.mean(), 3),
           "runs_calm": [n for v, n in runs if v == 0], "runs_volatile": [n for v, n in runs if v == 1]}
    reg = cx.regime_at(cx.t0)
    out["jumps_by_regime"] = {"calm": int((reg == 0).sum()), "volatile": int((reg == 1).sum()), "unlabelled": int((reg == -1).sum())}
    # transition probabilities and P(switch) by run age
    trans = np.zeros((2, 2))
    for a, b in zip(lab[:-1], lab[1:]):
        trans[a, b] += 1
    out["transition_counts_calm_vol"] = trans.astype(int).tolist()
    tp = cx.tp
    end = tp.grid[-1]
    last = tp.grid > end - 120
    out["last_120s"] = {"mid_first_last": [r(tp.mid_g[last][0], 1), r(tp.mid_g[last][-1], 1)],
                        "spread_mean": r(np.nanmean(tp.spread_g[last]), 2), "regime": cx.regime_at(np.array([end - 60]))[0].item()}
    # F size table: discreteness
    q = tp.qf
    vals, counts = np.unique(q, return_counts=True)
    out["F_size_distinct_values"] = int(len(vals))
    out["F_size_top10"] = [[int(v), int(c_)] for v, c_ in sorted(zip(vals, counts), key=lambda z: -z[1])[:10]]
    return out


def section_e(cx: Ctx) -> dict:
    rows = cx.rows
    t, mid, gap, spr = rows[:, 0], rows[:, 1], rows[:, 2], rows[:, 5]
    bid, ask = mid - spr / 2, mid + spr / 2
    L = int(round(0.2 / float(np.median(np.diff(t)))))
    mv = np.r_[np.zeros(L), mid[L:] - mid[:-L]]
    keep, last = [], -1e9
    for i in np.flatnonzero(np.abs(mv) >= 3):
        if t[i] - last > 2.0:
            keep.append(i)
        last = t[i]
    keep = np.array(keep, dtype=int)
    keep = keep[keep + 201 < len(t)]
    if not len(keep):
        return {"triggers": 0}
    sg = np.sign(mv[keep])
    e = keep + 1
    out = {"triggers": int(len(keep)), "per_1000s": r(1000 * len(keep) / cx.tp.dur, 1), "gap_way_mean": r(np.mean(gap[e] * sg), 2)}
    for G in (-99, 0, 1, 2, 3):
        for SP in (1, 2, 99):
            sel = (gap[e] * sg >= G) & (spr[e] <= SP)
            row = {"n": int(sel.sum())}
            for H in (10, 20, 40, 60, 100, 200):
                x = e + H
                tt = np.where(sg > 0, bid[x] - ask[e], bid[e] - ask[x])[sel]
                row[f"{H * 0.05:g}s"] = r(tt.mean(), 2) if len(tt) else None
            out[f"gap_way>={G}_spread<={SP}"] = row
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("tape", type=Path)
    ap.add_argument("--cache", type=Path, help="gen_identify's replay cache (.npz); the filter and F replays are cached beside it")
    ap.add_argument("--pnl", type=Path, action="append", default=[], help="a bot's per-second pnl.csv (section A), repeatable")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--only", default="ABCDE")
    a = ap.parse_args(argv)
    cx = Ctx(a.tape, a.cache)
    res = {"tape": str(a.tape), "c": cx.c, "jumps": int(len(cx.t0)), "volatile_share": r(cx.vol_block.mean(), 3)}
    if "A" in a.only:
        res["A"] = {str(p): section_a(cx, p) for p in a.pnl}
    if "B" in a.only:
        res["B"] = section_b(cx)
    if "C" in a.only:
        res["C"] = section_c(cx)
    if "E" in a.only:
        res["E"] = section_e(cx)
    if "D" in a.only:
        res["D"] = section_d(cx)
    gi.show(res)
    if a.json:
        a.json.write_text(json.dumps(res, indent=1, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
