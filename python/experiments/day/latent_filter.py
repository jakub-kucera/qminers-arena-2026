"""An online filter of the generator's hidden fair price, and its offline forecast quality on a tape (8 Nov, round 3).

The generator's structure (experiments/day/tape_gen.py): new limit orders are placed around a latent reference bid
`lb` (the latent mid is lb + 0.5), bids at lb - k and asks at lb + 1 + k with k mostly 0-2, never crossing the book
(clamped one tick off the other touch); aggressive orders move the latent price by a size-dependent impact. The filter
is a discrete hidden-Markov filter over integer `lb` (2W+1 states around the book):

- **prediction:** between events `lb` steps one tick either way at `rate` a second (a random walk);
- **an aggressive trade** of q lots moves the mass `impact(q) * impact_scale` ticks its way (a fractional shift);
- **a new limit order** within `depth` ticks of its touch multiplies the mass by its likelihood: a bid at p < ask - 1
  says lb = p + k with P(k) = pi[k] (pi0-pi2, and pi3 if set); a bid at ask - 1 (the clamp) says lb - k >= ask - 1;
  asks the mirror image; plus a floor `eps` for outliers;
- **options, off by default:** `sqrt_c` (Phase 1's impact, sqrt_c x sqrt(lots), instead of the table); `jump` (lognormal
  jumps at that rate a second, `jump_med` / `jump_sd`, mixed in around the mode: Rust's FILTER_JUMP); `sweep` (a market
  buy that filled up to P truncates lb < P - 1 - sweep, a sell lb > P + sweep, by `sweep_eps`).

`--latent FILE` (tape_gen --latent-out's true latent of a generated tape) adds the oracle check: the tracking RMSE by
regime, the lag after 3+ tick jumps, and the true gap's correlation with the mid's moves beside the filter's (the
ceiling). Every run reports `loglik_per_insert`, the inserts' predictive log-likelihood (the dynamics' fit).

The signal is E[lb] + 0.5 - mid, the filter's forecast of where the mid is going. `--eval` replays a tape through
tape_book.Book (what the bot sees: every insert with the touch before it, every aggressive trade's filled lots),
samples every 50 ms and prints the correlation of the signal (and of the touch imbalance, the baseline) with the mid's
move 0.1 / 0.4 / 1 / 5 s ahead, on the first 75% and the last 25% of the tape; `--offsets` re-estimates pi from the
inserts' offsets to the filter's confident MAP (one EM-like step).

    uv run python -m experiments.day.latent_filter data/arena/round2/round2_public.csv [--set rate=2 --set eps=0.01]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

from experiments.day.tape_book import Book

# tape_gen's round-1 impact table: (max lots, mean 5 s mid move in ticks)
IMPACT = ((10, 0.097), (30, 0.111), (60, 0.161), (120, 0.254), (250, 0.349), (500, 0.468), (1000, 0.704), (10**9, 0.903))
DEFAULTS = {"W": 8, "rate": 2.0, "eps": 0.01, "pi0": 0.55, "pi1": 0.39, "pi2": 0.06, "pi3": 0.0, "impact_scale": 1.0, "depth": 99, "sqrt_c": 0.0, "use_size": 0,
            "jump": 0.0, "jump_med": 6.66, "jump_sd": 0.79, "sweep": -1, "sweep_eps": 0.01}
HORIZONS = (0.1, 0.4, 1.0, 5.0)
STEP = 0.05


class LatentFilter:
    """The bot's copy lives in candidates/r3_F1_latent_filter.py (kept identical by hand)."""

    def __init__(self, W=8, rate=2.0, eps=0.01, pi0=0.55, pi1=0.39, pi2=0.06, pi3=0.0, impact_scale=1.0, depth=99, sqrt_c=0.0, use_size=0,
                 jump=0.0, jump_med=6.66, jump_sd=0.79, sweep=-1, sweep_eps=0.01):
        self.W = int(W)
        self.n = 2 * self.W + 1
        self.rate = rate
        self.eps = eps
        raw = [pi0, pi1, pi2] + ([pi3] if pi3 > 0 else [])
        s = sum(raw)
        self.pi = tuple(x / s for x in raw)
        self.K = len(self.pi)
        # cumulative: cum[j] = pi0 + ... + pi_j
        self.cum = tuple(sum(self.pi[: j + 1]) for j in range(self.K - 1)) + (1.0,)
        self.depth = depth
        self.impact_scale = impact_scale
        self.sqrt_c = sqrt_c  # > 0: Phase 1's rule, the latent moves sqrt_c * sqrt(lots) (replaces the table)
        self.use_size = use_size  # offline only: 1 moves it by the order's size, 0 by its filled lots (what a bot sees)
        # (a) jumps: at `jump` a second lb jumps a lognormal size (median jump_med, log-sd jump_sd) either way,
        # spread around the MAP (the posterior is concentrated, so the convolution is taken at its mode)
        self.jump = jump
        w = []
        for k in range(1, self.n):
            hi = 0.5 * (1 + math.erf((math.log(k + 0.5) - math.log(jump_med)) / (jump_sd * math.sqrt(2))))
            lo = 0.5 * (1 + math.erf((math.log(k - 0.5) - math.log(jump_med)) / (jump_sd * math.sqrt(2)))) if k > 1 else 0.0
            w.append(hi - lo)
        tot = sum(w) or 1.0
        self.jump_k = [0.0] + [x / tot / 2 for x in w]  # by |offset| from the mode, each sign half
        # (b) sweep bounds: a market buy that filled up to P says lb >= P - 1 - sweep, a sell down to P lb <= P + sweep
        self.sweep = sweep
        self.sweep_eps = sweep_eps
        self.base = None  # lb of index 0 is base
        self.loglik = 0.0
        self.n_obs = 0
        self.p = None
        self.t = None

    def reset(self, bid):
        self.base = bid - self.W
        self.p = [0.0] * self.n
        self.p[self.W] = 1.0

    def advance(self, t):
        if self.t is None:
            self.t = t
            return
        dt = t - self.t
        if dt <= 0:
            return
        self.t = t
        a = self.rate * dt
        if a < 1e-9:
            return
        if a > 0.3:
            a = 0.3
        p = self.p
        n = self.n
        keep = 1.0 - 2.0 * a
        q = [0.0] * n
        prev = 0.0
        for i in range(n):
            cur = p[i]
            nxt = p[i + 1] if i + 1 < n else 0.0
            q[i] = keep * cur + a * (prev + nxt)
            prev = cur
        # mass lost off the edges goes back to the edge states
        q[0] += a * p[0]
        q[-1] += a * p[-1]
        if self.jump > 0:
            pj = min(0.5, self.jump * dt)
            m = max(range(n), key=q.__getitem__)
            k = self.jump_k
            total = 0.0
            for i in range(n):
                v = (1.0 - pj) * q[i] + pj * k[abs(i - m)]
                q[i] = v
                total += v
            inv = 1.0 / total
            for i in range(n):
                q[i] *= inv
        self.p = q

    def bound(self, direction, deepest):
        """(b): truncate the mass below (a buy) or above (a sell) what the order's deepest fill says."""
        if self.sweep < 0:
            return
        p, n, base, e = self.p, self.n, self.base, self.sweep_eps
        total = 0.0
        for i in range(n):
            lb = base + i
            if (direction > 0 and lb < deepest - 1 - self.sweep) or (direction < 0 and lb > deepest + self.sweep):
                p[i] *= e
            total += p[i]
        if total > 0:
            inv = 1.0 / total
            for i in range(n):
                p[i] *= inv

    def recenter(self, bid):
        """Keep the grid centred on the book's bid (shift by whole ticks; mass beyond the edge piles on the edge)."""
        shift = bid - self.W - self.base
        if shift == 0:
            return
        if abs(shift) >= self.n:
            self.reset(bid)
            return
        p = self.p
        n = self.n
        q = [0.0] * n
        for i in range(n):
            j = i - shift
            if j < 0:
                j = 0
            elif j >= n:
                j = n - 1
            q[j] += p[i]
        self.p = q
        self.base += shift

    def trade(self, direction, lots):
        """An aggressive order filled `lots` lots, `direction` +1 (bought the ask) or -1."""
        if self.sqrt_c > 0:
            m = self.sqrt_c * math.sqrt(lots)
        else:
            m = self.impact_scale
            for top, value in IMPACT:
                if lots <= top:
                    m *= value
                    break
        if m <= 0:
            return
        whole = int(m)
        frac = m - whole
        p = self.p
        n = self.n
        q = [0.0] * n
        for i in range(n):
            v = p[i]
            if v == 0.0:
                continue
            j = i + direction * whole
            k = j + direction
            j = 0 if j < 0 else n - 1 if j >= n else j
            k = 0 if k < 0 else n - 1 if k >= n else k
            q[j] += v * (1.0 - frac)
            q[k] += v * frac
        self.p = q

    def insert(self, side, price, bid, ask):
        """A new limit order at `price` (side 0 bid, 1 ask), the touch (bid, ask) before it."""
        p = self.p
        n = self.n
        base = self.base
        eps = self.eps
        pi, cum, K = self.pi, self.cum, self.K
        total = 0.0
        if side == 0:
            clamp = ask - 1
            if price >= clamp:
                # lb - k >= clamp for the drawn k: lb >= clamp + k
                for i in range(n):
                    d = base + i - clamp
                    like = eps + (cum[d] if d < K else 1.0) if d >= 0 else eps
                    v = p[i] * like
                    p[i] = v
                    total += v
            else:
                for i in range(n):
                    k = base + i - price
                    v = p[i] * (eps + pi[k] if 0 <= k < K else eps)
                    p[i] = v
                    total += v
        else:
            clamp = bid + 1
            if price <= clamp:
                # lb + 1 + k <= clamp: lb <= clamp - 1 - k
                for i in range(n):
                    d = clamp - 1 - (base + i)
                    like = eps + (cum[d] if d < K else 1.0) if d >= 0 else eps
                    v = p[i] * like
                    p[i] = v
                    total += v
            else:
                for i in range(n):
                    k = price - 1 - (base + i)
                    v = p[i] * (eps + pi[k] if 0 <= k < K else eps)
                    p[i] = v
                    total += v
        if total <= 0 or not math.isfinite(total):
            self.p = [1.0 / n] * n
            return
        # the predictive likelihood of this insert (up to the observation model's constant): its log summed is the
        # fit of the dynamics (rate, impact, jumps) to the tape's inserts, the maximum-likelihood criterion
        self.loglik += math.log(total)
        self.n_obs += 1
        inv = 1.0 / total
        for i in range(n):
            p[i] *= inv

    def moments(self):
        """(E[lb], sd[lb])."""
        m = s2 = 0.0
        base = self.base
        for i, v in enumerate(self.p):
            m += v * i
            s2 += v * i * i
        var = max(0.0, s2 - m * m)
        return base + m, math.sqrt(var)

    def map(self):
        p = self.p
        i = max(range(self.n), key=p.__getitem__)
        return self.base + i, p[i]


def replay(path: Path, params: dict, offsets: bool = False):
    """Replay the tape; return the 50-ms samples (t, mid, signal, sd, imbalance, spread) and, with offsets, the
    inserts' offsets k to a confident MAP (bid: lb - p, ask: p - 1 - lb) at a 1- and 2-tick spread."""
    book = Book()
    filt = LatentFilter(**params)
    rows = []
    next_t = STEP
    ks = {}
    fchk = []
    last_bb = last_ba = None
    with path.open() as fh:
        next(fh)
        for line in fh:
            t, op, oid, side, vol, price, life = line.rstrip("\n").split(",")
            t = float(t)
            bb, ba = book.best
            while t >= next_t:
                if last_bb is not None and last_ba is not None and last_bb < last_ba:
                    mid = (last_bb + last_ba) / 2
                    e, sd = filt.moments()
                    bq = book.depth(0, last_bb)
                    aq = book.depth(1, last_ba)
                    rows.append((next_t, mid, e + 0.5 - mid, sd, (bq - aq) / (bq + aq), last_ba - last_bb))
                next_t += STEP
            if op == "Insert":
                sd_ = 0 if side == "B" else 1
                p_, q_ = int(price), int(vol)
                if life == "F":
                    fills = []
                    book.insert(oid, sd_, p_, q_, True, fills)
                    lots = sum(f[1] for f in fills)
                    if filt.p is not None and bb is not None and ba is not None and bb < ba:
                        # Phase 1: an F's limit is the latent mid +-1, a direct check of the filter
                        e, _ = filt.moments()
                        fchk.append(((p_ - 1 if sd_ == 0 else p_ + 1) - (bb + ba) / 2, e + 0.5 - (bb + ba) / 2))
                    if lots and filt.p is not None:
                        filt.advance(t)
                        if filt.sweep >= 0:
                            filt.bound(1 if sd_ == 0 else -1, max(f[2] for f in fills) if sd_ == 0 else min(f[2] for f in fills))
                        filt.trade(1 if sd_ == 0 else -1, q_ if filt.use_size else lots)
                else:
                    if bb is not None and ba is not None and bb < ba:
                        if filt.p is None:
                            filt.reset(bb)
                        filt.advance(t)
                        filt.recenter(bb)
                        if offsets and abs(p_ - (bb if sd_ == 0 else ba)) <= 4:
                            lb, conf = filt.map()
                            if conf > 0.9:
                                k = lb - p_ if sd_ == 0 else p_ - 1 - lb
                                key = (min(ba - bb, 3), sd_ == 0 and p_ >= ba - 1 or sd_ == 1 and p_ <= bb + 1, k)
                                ks[key] = ks.get(key, 0) + 1
                        if abs(p_ - (bb if sd_ == 0 else ba)) <= filt.depth:
                            filt.insert(sd_, p_, bb, ba)
                    book.insert(oid, sd_, p_, q_, False)
            else:
                book.cancel(oid)
            last_bb, last_ba = book.best
    replay.last_loglik = (filt.loglik, filt.n_obs)
    return np.array(rows), ks, np.array(fchk)


def evaluate(rows: np.ndarray) -> dict:
    out = {}
    n = len(rows)
    cut = int(n * 0.75)
    mid = rows[:, 1]
    for name, lo, hi in (("first75", 0, cut), ("last25", cut, n)):
        res = {}
        for h in HORIZONS:
            lag = int(round(h / STEP))
            idx = np.arange(lo, min(hi, n - lag))
            fut = mid[idx + lag] - mid[idx]
            sig = rows[idx, 2]
            imb = rows[idx, 4]
            r_sig = float(np.corrcoef(sig, fut)[0, 1])
            r_imb = float(np.corrcoef(imb, fut)[0, 1])
            x = np.column_stack([np.ones(len(idx)), imb, sig])
            beta, *_ = np.linalg.lstsq(x, fut, rcond=None)
            r2_both = 1 - np.var(fut - x @ beta) / np.var(fut)
            x1 = x[:, :2]
            b1, *_ = np.linalg.lstsq(x1, fut, rcond=None)
            r2_imb = 1 - np.var(fut - x1 @ b1) / np.var(fut)
            res[f"{h:g}s"] = {"r_sig": round(r_sig, 4), "r_imb": round(r_imb, 4), "r2_imb": round(float(r2_imb), 4),
                              "r2_both": round(float(r2_both), 4), "beta_sig": round(float(beta[2]), 3)}
        out[name] = res
    out["signal_sd"] = round(float(np.std(rows[:, 2])), 4)
    out["post_sd_mean"] = round(float(np.mean(rows[:, 3])), 4)
    out["big"] = big_moves(rows)
    return out


def f_check(fchk: np.ndarray) -> dict:
    """The filter against the F orders' limits (the latent mid +-1 by Phase 1), both relative to the mid."""
    implied, est = fchk[:, 0], fchk[:, 1]
    err = est - implied
    return {"n": len(fchk), "corr": round(float(np.corrcoef(implied, est)[0, 1]), 4),
            "implied_sd": round(float(implied.std()), 3), "err_mean": round(float(err.mean()), 3),
            "err_sd": round(float(err.std()), 3), "slope": round(float(np.polyfit(est, implied, 1)[0]), 3)}


def big_moves(rows: np.ndarray) -> dict:
    """The large-gap question: when |signal| >= g, the move 1 / 5 s ahead the signal's way (hit rate among non-zero
    moves, mean, share >= 5 ticks right and wrong); and of the moves of 5+ ticks, the share the signal called
    (|signal| >= 1 the right way) at their start."""
    mid, sig = rows[:, 1], rows[:, 2]
    n = len(rows)
    out = {}
    for h in (1.0, 5.0):
        lag = int(round(h / STEP))
        fut = mid[lag:] - mid[: n - lag]
        s = sig[: n - lag]
        res = {"move_sd": round(float(fut.std()), 3), "share_5plus": round(float(np.mean(np.abs(fut) >= 5)), 4)}
        for g in (0.5, 1.0, 1.5, 2.0, 3.0):
            sel = np.abs(s) >= g
            if sel.sum() < 20:
                continue
            way = np.sign(s[sel]) * fut[sel]
            nz = way != 0
            res[f"gap{g:g}"] = {"share": round(float(sel.mean()), 4), "hit": round(float(np.mean(way[nz] > 0)), 3),
                                "mean": round(float(way.mean()), 3), "right5": round(float(np.mean(way >= 5)), 4),
                                "wrong5": round(float(np.mean(way <= -5)), 4)}
        big = np.abs(fut) >= 5
        if big.sum():
            called = np.sign(s[big]) * np.sign(fut[big]) * (np.abs(s[big]) >= 1)
            res["of_5plus_called"] = round(float(np.mean(called > 0)), 3)
            res["of_5plus_against"] = round(float(np.mean(called < 0)), 3)
        out[f"{h:g}s"] = res
    return out


def oracle(rows: np.ndarray, latent_path: Path) -> dict:
    """Against a generated tape's true latent (tape_gen --latent-out: time, latent, state, jump every 10 ms): the
    filter's tracking error by regime, its lag after jumps of 3+ ticks (time until within 1 tick), and the true gap's
    correlation with the mid's moves (the ceiling) beside the filter's."""
    lat = np.loadtxt(latent_path, delimiter=",", skiprows=1)
    t = rows[:, 0]
    idx = np.clip(np.rint(t / 0.01).astype(int), 0, len(lat) - 1)
    L, state = lat[idx, 1], lat[idx, 2]
    mid, sig = rows[:, 1], rows[:, 2]
    est = mid + sig  # E[lb] + 0.5
    out = {}
    for name, sel in (("all", np.ones(len(t), bool)), ("calm", state == 0), ("volatile", state == 1)):
        if sel.sum() < 10:
            continue
        out[name] = {"share": round(float(sel.mean()), 3),
                     "rmse_filter": round(float(np.sqrt(np.mean((est[sel] - L[sel]) ** 2))), 3),
                     "rmse_mid": round(float(np.sqrt(np.mean((mid[sel] - L[sel]) ** 2))), 3),
                     "rmse_floor": round(float(np.sqrt(np.mean((est[sel] - (np.floor(L[sel]) + 0.5)) ** 2))), 3)}
    # jumps of 3+ ticks: the lag until the filter (and the mid) is within 1 tick of the latent
    jt = lat[np.abs(lat[:, 3]) >= 3, 0]
    lags_f, lags_m = [], []
    for tj in jt:
        i0 = np.searchsorted(t, tj)
        seg = slice(i0, min(len(t), i0 + 200))  # 10 s
        ok_f = np.nonzero(np.abs(est[seg] - L[seg]) < 1)[0]
        ok_m = np.nonzero(np.abs(mid[seg] - L[seg]) < 1)[0]
        lags_f.append(ok_f[0] * STEP if len(ok_f) else 10.0)
        lags_m.append(ok_m[0] * STEP if len(ok_m) else 10.0)
    if jt.size:
        out["jumps3"] = {"n": int(jt.size), "lag_filter_median": round(float(np.median(lags_f)), 3),
                         "lag_filter_q90": round(float(np.quantile(lags_f, 0.9)), 3),
                         "lag_mid_median": round(float(np.median(lags_m)), 3),
                         "lag_mid_q90": round(float(np.quantile(lags_m, 0.9)), 3)}
    n = len(t)
    for h in HORIZONS:
        lag = int(round(h / STEP))
        fut = mid[lag:] - mid[: n - lag]
        r = lambda x: round(float(np.corrcoef(x[: n - lag], fut)[0, 1]), 4)
        out[f"corr_{h:g}s"] = {"filter_gap": r(sig), "true_gap": r(L - mid), "true_floor_gap": r(np.floor(L) + 0.5 - mid)}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("tape", type=Path)
    ap.add_argument("--set", action="append", default=[], help="a filter parameter, NAME=VALUE (see DEFAULTS)")
    ap.add_argument("--offsets", action="store_true", help="also tabulate the inserts' offsets to a confident MAP")
    ap.add_argument("--out", type=Path, help="write the result as JSON")
    ap.add_argument("--latent", type=Path, help="a generated tape's true latent (tape_gen --latent-out): the oracle check")
    args = ap.parse_args(argv)
    params = dict(DEFAULTS)
    for item in args.set:
        k, v = item.split("=", 1)
        if k not in params:
            ap.error(f"unknown parameter {k}")
        params[k] = float(v)
    rows, ks, fchk = replay(args.tape, params, args.offsets)
    ll, n_obs = replay.last_loglik
    result = {"tape": str(args.tape), "params": params, "samples": len(rows), "loglik_per_insert": round(ll / max(1, n_obs), 5),
              **evaluate(rows), "f_check": f_check(fchk)}
    if args.latent:
        result["oracle"] = oracle(rows, args.latent)
    if args.offsets:
        result["offsets"] = {f"spread{s}_{'clamp' if c else 'free'}_k{k}": v for (s, c, k), v in sorted(ks.items())}
    text = json.dumps(result, indent=1)
    print(text)
    if args.out:
        args.out.write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
