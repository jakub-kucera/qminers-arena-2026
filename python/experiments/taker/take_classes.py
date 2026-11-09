"""A distributional take decision near F5's bar (8 Nov, round 4; IDEAS.md, "R4-K1").

F5 takes when its 400-ms forecast net of the inventory skew clears 0.25 ticks over half the spread (0.15 for 5 s after
a 3-tick jump). Its forecast is a Huber ridge: the hypothesis is that it downweights large surprises and so hides
jump information that a distributional model would keep. Here, at F5's decision-relevant book events only (a 1-tick
spread, |prediction - skew| in [LO, HI], room to take that way), the signed mid move y = d x (mid(t+H) - mid(t)), d the
signal's side, falls in five classes: large against (y <= -L), small against, flat (|y| < S), small with, large with
(y >= L). A model's expected profit of the take is sum_k P(k) x mean_k(y) - d x skew - half the spread, the class means
from the training block. Models (all sign-normalised by d):

- ``F5``: F5's own rule (the baseline: d x signal > 0.75, 0.65 in the jump state);
- ``lin``: an OLS of y on F5's forecast (its recalibration), the control for a threshold shift;
- ``mnl``: a multinomial logistic on the inputs at t (F5's forecast, the filter gap, the touch imbalance, the log touch
  depth on the side taken and the side kept, the 5-level depth imbalance, the speed, the jump state);
- ``mnlh``: the same plus history: those inputs and the mid at t-50 ms, t-200 ms and t-1 s, and their changes since;
- ``olsh``: an OLS on mnlh's inputs (squared loss: whether the classes or the history carry any gain);
- ``hgb``: sklearn HistGradientBoostingClassifier (max_depth 3) on mnlh's inputs;
- ``mnl_b``, ``ols_b``, ``hgb_b``: the three model kinds on the inputs at t only, the reference for
- ``*_v``: the inputs at t plus Hawkes-style typed histories (decayed counts and log lots of market buys and sells,
  fresh placements and cancels within 3 ticks of the touch per side, at HAWKES_TAUS, oriented by d; two interactions);
- ``*_vi``: the inputs at t plus an MRR surprise (an online logistic of the next market order's side; side minus
  2 P(buy) - 1, and the same times log lots, decayed at MRR_TAUS).

Protocol: chronological blocks; train on the first 50% of the tape, calibrate on the next 20%, test on the last 30%
(three sub-blocks of 10%). Points whose 5-s markout crosses a block boundary are purged. Evaluation (calibration and
test) is on decision points spaced at least SPACE s apart (greedy over the relevant events), so overlapping labels do
not count twice. Each model's rule: ``ep0`` takes when the expected profit is > 0; ``rate`` sets the threshold on the
calibration block so the model takes as often as F5 does there (a ranking test at F5's take count). Reported per model
and rule on the test block: takes, the realised net PnL per lot at 0.4 / 1 / 5 s (y - half spread, at the tape's mid),
the decisions changed against F5 (added, vetoed), and the realised value of the changed decisions (the added takes' net
minus the vetoed takes' net) in total and per sub-block.

Inputs: F5's Rust prediction log (``RIDGE_PRED_LOG=P RIDGE_PRED_EXTRA=1 uv run python -m arena.qsim_rust ridge_maker
TAPE <F5's line> --threads 1``) and tape_stats' cached replay (``uv run python -m experiments.tape.tape_stats TAPE --cache
R.npz``) for the market touch and mid.

    uv run python -m experiments.taker.take_classes TAPE --pred P --cache R.npz [--horizon 0.4] [--json OUT]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

from experiments.tape.tape_stats import load

LAGS = (0.05, 0.2, 1.0)
MARKS = (0.4, 1.0, 5.0)
BAR, JUMP_BAR, HALF = 0.25, 0.15, 0.5
JUMP, JUMP_MS, JUMP_HOLD_MS = 3.0, 200, 5000


def load_pred(path: Path) -> dict:
    import pandas as pd

    df = pd.read_csv(path, header=None, names=["t", "mid", "pred", "skew", "spread", "inv", "gap", "speed"])
    return {k: df[k].to_numpy() for k in df.columns}


def asof(times: np.ndarray, at: np.ndarray) -> np.ndarray:
    return np.clip(np.searchsorted(times, at, side="right") - 1, 0, len(times) - 1)


def jump_state(t: np.ndarray, mid: np.ndarray) -> np.ndarray:
    """F5's jump bar: the mid JUMP ticks from the oldest mid within JUMP_MS starts JUMP_HOLD_MS of the lower bar."""
    oldest = np.searchsorted(t, t - JUMP_MS * 1000, side="left")
    hit = np.abs(mid - mid[oldest]) >= JUMP
    last = np.maximum.accumulate(np.where(hit, t, -10**18))
    return t < last + JUMP_HOLD_MS * 1000


def decayed(t: np.ndarray, v: np.ndarray, tau: float, block: float = 30.0) -> np.ndarray:
    """Each event's exponentially decayed sum of v (time constant tau s) over the events at or before it."""
    out = np.empty(len(v))
    blocks = np.floor((t - t[0]) / block).astype(np.int64)
    edges = np.concatenate([[0], np.flatnonzero(np.diff(blocks)) + 1, [len(t)]])
    carry, tc = 0.0, t[0]
    for a, b in zip(edges[:-1], edges[1:]):
        rel = t[a:b] - t[a]
        cs = np.cumsum(v[a:b] * np.exp(rel / tau))
        out[a:b] = carry * np.exp(-(t[a:b] - tc) / tau) + cs * np.exp(-rel / tau)
        carry, tc = out[b - 1], t[b - 1]
    return out


def at_times(t_ev: np.ndarray, vals: np.ndarray, tau: float, k: np.ndarray, at: np.ndarray) -> np.ndarray:
    """The decayed sum at query times: the last event's value at or before each, decayed to it (0 before any event)."""
    return np.where(k >= 0, vals[np.maximum(k, 0)] * np.exp(-(at - t_ev[np.maximum(k, 0)]) / tau), 0.0)


def mrr_surprise(ts: dict, rate: float = 0.02) -> tuple[np.ndarray, np.ndarray]:
    """(vi) An online logistic of the next market order's side (+1 buy) on the last three sides, the touch imbalance
    before it and the log time since the last one; updated after each order (causal). Returns the F events' indices and
    each one's surprise, side - (2 P(buy) - 1)."""
    kind, side, t = ts["kind"], ts["side"], ts["t"]
    qb, qa = ts["qb"].astype(float), ts["qa"].astype(float)
    fi = np.flatnonzero(kind == 1)
    w = np.zeros(6)
    s1 = s2 = s3 = 0.0
    last_t = None
    sur = np.empty(len(fi))
    for n, i in enumerate(fi):
        imb = (qb[i - 1] - qa[i - 1]) / max(1.0, qb[i - 1] + qa[i - 1]) if i > 0 else 0.0
        gap = math.log1p(1000 * (t[i] - last_t)) / 5 if last_t is not None else 1.0
        xv = np.array((1.0, s1, s2, s3, imb, gap))
        p = 1 / (1 + math.exp(-max(-30.0, min(30.0, float(w @ xv)))))
        y = 1.0 if side[i] == 0 else -1.0
        sur[n] = y - (2 * p - 1)
        w += rate * ((y + 1) / 2 - p) * xv
        s3, s2, s1, last_t = s2, s1, y, t[i]
    return fi, sur


HAWKES_TAUS = (0.1, 1.5)
MRR_TAUS = (0.2, 1.0)


def event_groups(ts: dict, at_us: np.ndarray) -> dict:
    """(v) Hawkes-style typed histories and (vi) the MRR surprise at the query times (us)."""
    t = ts["t"]
    k = np.searchsorted(np.round(t * 1e6).astype(np.int64), at_us, side="right") - 1
    at = at_us / 1e6
    kind, side, off = ts["kind"], ts["side"], ts["off"]
    lots = np.where(kind == 1, ts["traded"], ts["lots"]).astype(float)
    near = np.nan_to_num(off, nan=99.0) <= 3
    types = {"MB": (kind == 1) & (side == 0), "MS": (kind == 1) & (side == 1),
             "PB": (kind == 0) & (side == 0) & near, "PA": (kind == 0) & (side == 1) & near,
             "CB": (kind == 2) & (side == 0) & near, "CA": (kind == 2) & (side == 1) & near}
    out = {}
    for name, m in types.items():
        for tau in HAWKES_TAUS:
            out[f"h{name}n{tau}"] = at_times(t, decayed(t, m.astype(float), tau), tau, k, at)
            out[f"h{name}l{tau}"] = at_times(t, decayed(t, np.where(m, lots, 0.0), tau), tau, k, at)
    fi, sur = mrr_surprise(ts)
    u = np.zeros(len(t))
    u[fi] = sur
    ul = np.zeros(len(t))
    ul[fi] = sur * np.log1p(lots[fi])
    for tau in MRR_TAUS:
        out[f"u{tau}"] = at_times(t, decayed(t, u, tau), tau, k, at)
        out[f"ul{tau}"] = at_times(t, decayed(t, ul, tau), tau, k, at)
    return out


def build(pred: dict, ts: dict) -> dict:
    t = pred["t"].astype(np.int64)
    ttu = np.round(ts["t"] * 1e6).astype(np.int64)
    bb, ba, qb, qa = ts["bb"], ts["ba"], ts["qb"].astype(float), ts["qa"].astype(float)
    ok = (bb >= 0) & (ba >= 0)
    tmid = np.where(ok, (bb + ba) * 0.5, np.nan)
    idx = np.arange(len(tmid))
    last_ok = np.maximum.accumulate(np.where(ok, idx, 0))
    tmid = tmid[last_ok]
    gt = np.round(ts["gt"] * 1e6).astype(np.int64)
    gd = ts["gdepth"].astype(float)
    half = gd.shape[1] // 2
    dimb5 = (gd[:, :half].sum(1) - gd[:, half:].sum(1)) / np.maximum(1.0, gd.sum(1))

    def touch(at: np.ndarray) -> tuple:
        k = asof(ttu, at)
        g = asof(gt, at)
        return tmid[k], (qb[k] - qa[k]) / np.maximum(1.0, qb[k] + qa[k]), qb[k], qa[k], dimb5[g]

    sig = pred["pred"] - pred["skew"]
    jump = jump_state(t, pred["mid"])
    m0, imb0, qb0, qa0, d50 = touch(t)
    out = dict(t=t, sig=sig, d=np.where(sig >= 0, 1.0, -1.0), jump=jump, mid=m0, imb=imb0, qb=qb0, qa=qa0,
               dimb5=d50)
    for h in MARKS:
        out[f"mid@{h}"] = tmid[asof(ttu, t + int(h * 1e6))]
    for lag in LAGS:
        at = t - int(lag * 1e6)
        k = asof(t, at)
        m, imb, b, a, d5 = touch(at)
        out[f"pred-{lag}"] = pred["pred"][k]
        out[f"gap-{lag}"] = pred["gap"][k]
        out[f"imb-{lag}"] = imb
        out[f"qb-{lag}"] = b
        out[f"qa-{lag}"] = a
        out[f"mid-{lag}"] = m
        out[f"dimb5-{lag}"] = d5
    out.update(pred=pred["pred"], skew=pred["skew"], spread=pred["spread"], inv=pred["inv"], gap=pred["gap"],
               speed=pred["speed"])
    qidx = np.flatnonzero((pred["spread"] == 1) & (np.abs(sig) >= 0.3) & (np.abs(sig) <= 2.0))
    pos = np.full(len(t), -1)
    pos[qidx] = np.arange(len(qidx))
    out["pos"] = pos
    out["ev"] = event_groups(ts, t[qidx])
    return out


def features(x: dict, sel: np.ndarray, history: bool, groups: tuple = ()) -> np.ndarray:
    d = x["d"][sel]
    q_take = np.where(d > 0, x["qa"][sel], x["qb"][sel])
    q_keep = np.where(d > 0, x["qb"][sel], x["qa"][sel])
    cols = [d * x["pred"][sel], d * x["gap"][sel], d * x["imb"][sel], np.log1p(q_take), np.log1p(q_keep),
            d * x["dimb5"][sel], x["speed"][sel], x["jump"][sel].astype(float)]
    if history:
        for lag in LAGS:
            qt = np.where(d > 0, x[f"qa-{lag}"][sel], x[f"qb-{lag}"][sel])
            qk = np.where(d > 0, x[f"qb-{lag}"][sel], x[f"qa-{lag}"][sel])
            p, g, i = d * x[f"pred-{lag}"][sel], d * x[f"gap-{lag}"][sel], d * x[f"imb-{lag}"][sel]
            cols += [p, g, i, np.log1p(qt), np.log1p(qk),
                     cols[0] - p, cols[1] - g, cols[2] - i, cols[3] - np.log1p(qt), cols[4] - np.log1p(qk),
                     d * (x["mid"][sel] - x[f"mid-{lag}"][sel])]
    if groups:
        p = x["pos"][sel]
        assert (p >= 0).all()
        ev = {key: v[p] for key, v in x["ev"].items()}
        up = d > 0
    if "v" in groups:
        for tau in HAWKES_TAUS:
            n = {}
            for kind, (buy_side, sell_side) in {"m": ("MB", "MS"), "p": ("PB", "PA"), "c": ("CA", "CB")}.items():
                for unit in ("n", "l"):
                    w_ = np.where(up, ev[f"h{buy_side}{unit}{tau}"], ev[f"h{sell_side}{unit}{tau}"])
                    a_ = np.where(up, ev[f"h{sell_side}{unit}{tau}"], ev[f"h{buy_side}{unit}{tau}"])
                    cols += [np.log1p(w_), np.log1p(a_)]
                    n[kind + unit] = (np.log1p(w_), np.log1p(a_))
            # interactions: cancels on the far side x buying our way; buying our way x far-side replenishment
            cols += [n["cn"][0] * n["mn"][0], n["mn"][0] * n["pn"][1]]
    if "vi" in groups:
        for tau in MRR_TAUS:
            cols += [d * ev[f"u{tau}"], d * ev[f"ul{tau}"]]
    return np.column_stack(cols)


def spaced(times: np.ndarray, gap_us: int) -> np.ndarray:
    keep = np.zeros(len(times), dtype=bool)
    nxt = -10**18
    for i, tt in enumerate(times):
        if tt >= nxt:
            keep[i] = True
            nxt = tt + gap_us
    return keep


def classes(y: np.ndarray, small: float, large: float) -> np.ndarray:
    return np.select([y <= -large, y <= -small, y < small, y < large], [0, 1, 2, 3], 4)


def run(x: dict, horizon: float, small: float, large: float, lo: float, hi: float, space: float,
        cuts=(0.5, 0.7), test_parts: int = 3, seed: int = 0,
        extra: tuple = (("_b", ()), ("_v", ("v",)), ("_vi", ("vi",)))) -> dict:
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LinearRegression, LogisticRegression
    from sklearn.preprocessing import StandardScaler

    t = x["t"]
    t0, t1 = t[0], t[-1]
    span = t1 - t0
    b1, b2 = t0 + cuts[0] * span, t0 + cuts[1] * span
    purge = int(max(MARKS) * 1e6)
    absig = np.abs(x["sig"])
    room = x["d"] * x["inv"] < 100
    rel = (x["spread"] == 1) & (absig >= lo) & (absig <= hi) & room & np.isfinite(x[f"mid@{max(MARKS)}"])
    y = {h: x["d"] * (x[f"mid@{h}"] - x["mid"]) for h in MARKS}
    block = np.where(t < b1, 0, np.where(t < b2, 1, 2))
    edge = np.where(block == 0, b1, np.where(block == 1, b2, t1 + 1))
    rel &= t + purge < edge
    tr = rel & (block == 0)
    f5_take = absig > np.where(x["jump"], JUMP_BAR, BAR) + HALF

    ev = {}
    for b in (1, 2):
        m = rel & (block == b)
        idx = np.flatnonzero(m)
        ev[b] = idx[spaced(t[idx], int(space * 1e6))]
    ytr = y[horizon][tr]
    cls = classes(ytr, small, large)
    means = np.array([ytr[cls == k].mean() if (cls == k).any() else 0.0 for k in range(5)])
    share = np.array([(cls == k).mean() for k in range(5)])
    skew_cost = x["d"] * x["skew"]

    models = {}
    xb_tr = features(x, tr, False)
    xh_tr = features(x, tr, True)
    sb = StandardScaler().fit(xb_tr)
    sh = StandardScaler().fit(xh_tr)
    lin = LinearRegression().fit((x["d"] * x["pred"])[tr][:, None], ytr)
    models["lin"] = lambda s: lin.predict((x["d"] * x["pred"])[s][:, None])
    mnl = LogisticRegression(C=1.0, max_iter=1000).fit(sb.transform(xb_tr), cls)
    models["mnl"] = lambda s: mnl.predict_proba(sb.transform(features(x, s, False))) @ means[mnl.classes_]
    mnlh = LogisticRegression(C=1.0, max_iter=1000).fit(sh.transform(xh_tr), cls)
    models["mnlh"] = lambda s: mnlh.predict_proba(sh.transform(features(x, s, True))) @ means[mnlh.classes_]
    olsh = LinearRegression().fit(sh.transform(xh_tr), ytr)
    models["olsh"] = lambda s: olsh.predict(sh.transform(features(x, s, True)))
    hgb = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200, l2_regularization=1.0,
                                         random_state=seed).fit(xh_tr, cls)
    models["hgb"] = lambda s: hgb.predict_proba(features(x, s, True)) @ means[hgb.classes_]
    for tag, groups in extra:
        xg_tr = features(x, tr, False, groups)
        sg = StandardScaler().fit(xg_tr)
        mg = LogisticRegression(C=1.0, max_iter=1000).fit(sg.transform(xg_tr), cls)
        og = LinearRegression().fit(sg.transform(xg_tr), ytr)
        hg = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200, l2_regularization=1.0,
                                            random_state=seed).fit(xg_tr, cls)
        models[f"mnl{tag}"] = (lambda s, mg=mg, sg=sg, groups=groups:
                               mg.predict_proba(sg.transform(features(x, s, False, groups))) @ means[mg.classes_])
        models[f"ols{tag}"] = (lambda s, og=og, sg=sg, groups=groups:
                               og.predict(sg.transform(features(x, s, False, groups))))
        models[f"hgb{tag}"] = (lambda s, hg=hg, groups=groups:
                               hg.predict_proba(features(x, s, False, groups)) @ means[hg.classes_])

    def mask(idx):
        s = np.zeros(len(t), dtype=bool)
        s[idx] = True
        return s

    cal, test = ev[1], ev[2]
    f5_cal = f5_take[cal]
    result = dict(horizon=horizon, small=small, large=large, lo=lo, hi=hi, space=space, train_events=int(tr.sum()),
                  class_share=share.round(4).tolist(), class_mean=means.round(3).tolist(), cal_points=len(cal),
                  test_points=len(test), models={})
    parts = np.minimum(test_parts - 1, ((t[test] - b2) * test_parts / (t1 - b2)).astype(int))
    net = {h: y[h][test] - HALF for h in MARKS}
    f5_t = f5_take[test]
    spd = x["speed"][test]
    tert = np.searchsorted(np.quantile(spd, [1 / 3, 2 / 3]), spd, side="right")

    def score(take: np.ndarray) -> dict:
        add, veto = take & ~f5_t, f5_t & ~take
        r = dict(takes=int(take.sum()), added=int(add.sum()), vetoed=int(veto.sum()))
        for h in MARKS:
            r[f"net/lot@{h}"] = float(net[h][take].mean()) if take.any() else math.nan
            r[f"changed@{h}"] = float(net[h][add].sum() - net[h][veto].sum())
            c = np.concatenate([net[h][add], -net[h][veto]])
            r[f"t@{h}"] = float(c.sum() / (c.std(ddof=1) * math.sqrt(len(c)))) if len(c) > 1 else 0.0
        r["changed_parts@%s" % horizon] = [float(net[horizon][add & (parts == p)].sum()
                                                 - net[horizon][veto & (parts == p)].sum()) for p in range(test_parts)]
        for h in (0.4, 5.0):
            r[f"changed_speed@{h}"] = [float(net[h][add & (tert == k)].sum() - net[h][veto & (tert == k)].sum())
                                       for k in range(3)]
        r["changed_parts@5.0"] = [float(net[5.0][add & (parts == p)].sum() - net[5.0][veto & (parts == p)].sum())
                                  for p in range(test_parts)]
        return r

    result["models"]["F5"] = {"rule": score(f5_t)}
    for name, fn in models.items():
        ep_cal = fn(mask(cal)) - skew_cost[cal] - HALF
        ep_test = fn(mask(test)) - skew_cost[test] - HALF
        n_f5 = int(f5_cal.sum())
        theta = float(np.sort(ep_cal)[::-1][n_f5 - 1]) if 0 < n_f5 <= len(ep_cal) else 0.0
        result["models"][name] = {"ep0": score(ep_test > 0), "rate": score(ep_test >= theta),
                                  "theta": theta, "ep_test_mean": float(ep_test.mean())}
    return result


def table(res: dict) -> str:
    lines = [f"H {res['horizon']} s, classes at +-{res['small']} / +-{res['large']}, |signal| {res['lo']}-{res['hi']}; "
             f"train events {res['train_events']:,}, cal points {res['cal_points']}, test points {res['test_points']}",
             f"class shares {res['class_share']}, class means {res['class_mean']}",
             f"{'model':6} {'rule':5} {'takes':>5} {'add':>4} {'veto':>4} {'net@0.4':>8} {'net@1':>7} {'net@5':>7} "
             f"{'chg@0.4 (t)':>13} {'chg@1 (t)':>13} {'chg@5 (t)':>13}  parts@H / parts@5 | speed slow/mid/fast @0.4 / @5"]
    for name, m in res["models"].items():
        for rule in ("rule", "ep0", "rate"):
            if rule not in m:
                continue
            r = m[rule]
            lines.append(f"{name:6} {rule:5} {r['takes']:5d} {r['added']:4d} {r['vetoed']:4d} {r['net/lot@0.4']:8.3f} "
                         f"{r['net/lot@1.0']:7.3f} {r['net/lot@5.0']:7.3f} "
                         + " ".join(f"{r[f'changed@{h}']:7.1f} ({r[f't@{h}']:+.1f})" for h in MARKS) + "  "
                         + " ".join(f"{v:+.0f}" for v in r[f"changed_parts@{res['horizon']}"]) + " / "
                         + " ".join(f"{v:+.0f}" for v in r["changed_parts@5.0"]) + " | "
                         + " ".join(f"{v:+.0f}" for v in r["changed_speed@0.4"]) + " / "
                         + " ".join(f"{v:+.0f}" for v in r["changed_speed@5.0"])
                         + (f"  theta {m['theta']:+.3f}" if rule == "rate" else ""))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("tape", type=Path)
    ap.add_argument("--pred", type=Path, required=True)
    ap.add_argument("--cache", type=Path, default=None)
    ap.add_argument("--horizon", type=float, nargs="+", default=[0.4, 1.0])
    ap.add_argument("--small", type=float, default=0.5)
    ap.add_argument("--large", type=float, default=3.0)
    ap.add_argument("--lo", type=float, default=0.4)
    ap.add_argument("--hi", type=float, default=1.5)
    ap.add_argument("--space", type=float, default=0.4)
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args(argv)
    x = build(load_pred(a.pred), load(a.tape, a.cache))
    out = []
    for h in a.horizon:
        res = run(x, h, a.small, a.large, a.lo, a.hi, a.space)
        print(table(res), flush=True)
        print()
        out.append(res)
    if a.json:
        a.json.write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
