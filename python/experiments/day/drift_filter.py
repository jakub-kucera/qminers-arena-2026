"""A drift-aware estimate of the generator's latent price, and what it adds to F5's forecast (8 Nov, round 4).

Round 4's generator model (docs/GENERATOR_ROUND4.json, wide6) has an OU drift in the latent: a velocity v with
stationary sd `drift_sd` ticks/s that decays over `drift_tau` s, applied only in the volatile state. F5's latent filter
(latent_filter.py; ridge_maker's FILTER code) assumes a driftless random walk. This tool adds the velocity offline, as a
second stage on F5's own filter output: a Kalman filter over [level, velocity] on the 0.1-s grid, observing the filter's
E[latent] (mid + the filter's gap, from the Rust prediction log). Dynamics over dt: v' = a v (a = exp(-dt / tau)), the
level moving tau (1 - a) v plus a diffusion of `ql` ticks^2/s; the velocity's innovation keeps its sd at `sv`; the
observation noise is `r` ticks^2. `middrift_*` runs the same Kalman on the mid instead (the mid's own trend, the control).

Features (all causal): `drift` = E[v] (ticks/s); `proj_H` = the filter's gap plus the drift's expected move over H s,
gap + E[v] tau (1 - exp(-H / tau)). Two tests:

- **real** (any tape): beyond F5's own 0.4-s forecast (the prediction log's), the partial R^2 of each feature for the
  mid's 0.4 / 1 / 5-s move (OLS of the move on [1, forecast, x] fitted on the first 75% of the grid, scored on the last
  25%, as forecast_gaps.py); and the **take-relevant** effect: at a one-tick spread with |forecast| in [0.5, 1.2] (where
  the 0.75 bar decides), how often the forecast plus x's 0.4-s increment takes a different decision (only decisions the
  position allows, |inventory| < 100 that way), and the realised move of the changed decisions: the new decision's
  value minus the old one's, in ticks a lot, each take paying the half spread.
- **truth** (`--latent`, a generated tape's true latent): the correlation of the filter's gap, the drift and the
  projections with the true latent's next 0.4-5 s move and the mid's, beside the oracle (the true latent's own past
  1-s slope, its jumps excluded, and the true gap).

`--hmm NAME=key=value,...` adds latent_filter's Python HMM at F5's settings and that variant (e.g. `informed=0.3`, a
market order's side as an observation of lb; `drift=4,drift_sw=0.67`, the joint level x drift HMM) as features.
`--level NAME=key=value,...` (repeatable) runs the level test instead (`level_test`): F5's filter and each variant (W,
depth, rate, jump, jump_med, jump_sd, impact_scale, drift: the Rust FILTER_* knobs) on the same events, each gap clipped
at 5 / 10 / 20 / no ticks (FILTER_CLIP), against the true gap (with `--latent`) and as a held-out partial R^2 beyond F5.

    uv run python -m experiments.day.drift_filter TAPE --pred PREDLOG [--cache TS.npz] [--latent LATENT.csv] [--json OUT]
    uv run python -m experiments.day.drift_filter TAPE --pred PREDLOG --latent L.csv --level w30=W=30,depth=30,jump=0.4

The prediction log: `RIDGE_PRED_LOG=<file> RIDGE_PRED_EXTRA=1 uv run python -m arena.qsim_rust ridge_maker TAPE <F5's
--set line> --threads 1` (F5's line: `experiments.day.family_rust.F5`).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

from experiments.day.tape_stats import GRID, grid_of, load

HORIZONS = (0.4, 1.0, 5.0)
TRUTH_HORIZONS = (0.4, 1.0, 2.0, 5.0)
FIT_SHARE = 0.75
NEED = 0.75  # F5's take bar at a one-tick spread: FT_EDGE 0.25 + the half spread
BAND = (0.5, 1.2)  # |forecast| where the bar decides
LIMIT = 100
# the Kalman settings tried: (tau s, sv ticks/s, ql ticks^2/s, r ticks^2); "w6" is wide6's drift (tau 1.5, sd 6)
SETTINGS = {
    "w6": (1.5, 6.0, 4.0, 1.0),
    "w6_r4": (1.5, 6.0, 4.0, 4.0),
    "w6_r025": (1.5, 6.0, 4.0, 0.25),
    "t3s3": (3.0, 3.0, 4.0, 1.0),
    "t3s3_r4": (3.0, 3.0, 4.0, 4.0),
    "t5s3": (5.0, 3.0, 2.0, 1.0),
}


def read_pred(path: Path) -> np.ndarray:
    cache = path.with_suffix(".npy")
    if cache.exists() and cache.stat().st_mtime >= path.stat().st_mtime:
        return np.load(cache)
    pl = np.loadtxt(path, delimiter=",", dtype=np.float64)
    try:
        np.save(cache, pl)
    except OSError:
        pass
    return pl


def kalman(z: np.ndarray, tau: float, sv: float, ql: float, r: float, dt: float = GRID) -> tuple[np.ndarray, np.ndarray]:
    """[level, velocity] filtered on a regular grid of observations z (NaN: no update). Returns (E[level], E[v])."""
    a = math.exp(-dt / tau)
    f01 = tau * (1.0 - a)
    q00, q11 = ql * dt, sv * sv * (1.0 - a * a)
    n = len(z)
    lev, vel = np.zeros(n), np.zeros(n)
    x0 = x1 = 0.0
    p00, p01, p11 = 100.0, 0.0, sv * sv
    started = False
    zz = z.tolist()
    for i in range(n):
        zi = zz[i]
        if not started:
            if zi == zi:
                x0, started = zi, True
            lev[i] = x0
            continue
        # predict
        x0 = x0 + f01 * x1
        x1 = a * x1
        n00 = p00 + 2 * f01 * p01 + f01 * f01 * p11 + q00
        n01 = a * (p01 + f01 * p11)
        n11 = a * a * p11 + q11
        p00, p01, p11 = n00, n01, n11
        if zi == zi:
            s = p00 + r
            k0, k1 = p00 / s, p01 / s
            y = zi - x0
            x0 += k0 * y
            x1 += k1 * y
            p00, p01, p11 = (1 - k0) * p00, (1 - k0) * p01, p11 - k1 * p01
        lev[i], vel[i] = x0, x1
    return lev, vel


def on_grid(pl: np.ndarray, grid: np.ndarray) -> dict:
    pt = pl[:, 0] / 1e6
    i = np.searchsorted(pt, grid, "right") - 1
    ok = i >= 0
    ii = np.clip(i, 0, len(pt) - 1)
    out = {name: np.where(ok, pl[ii, col], np.nan) for name, col in
           (("pred", 2), ("pmid", 1), ("spread", 4), ("inv", 5), ("gap", 6), ("speed", 7))}
    return out


def features(gm: np.ndarray, st: dict, settings: dict, mid_control: bool = True) -> dict:
    z = st["pmid"] + st["gap"]  # the filter's E[latent] (E[lb] + 0.5), as the bot saw it
    gap = np.nan_to_num(st["gap"])
    c: dict = {"gap_now": gap}
    cs = np.concatenate([[0.0], np.cumsum(gap)])
    m = int(1 / GRID)
    n = len(gap)
    lo = np.maximum(np.arange(n) + 1 - m, 0)
    c["gap_mean_1s"] = (cs[np.arange(n) + 1] - cs[lo]) / (np.arange(n) + 1 - lo)
    for name, (tau, sv, ql, r) in settings.items():
        _, v = kalman(z, tau, sv, ql, r)
        c[f"drift_{name}"] = v
        for h in (1.0, 2.0):
            c[f"proj{h:g}_{name}"] = gap + v * tau * (1 - math.exp(-h / tau))
        if mid_control:
            _, vm = kalman(gm, tau, sv, ql, r)
            c[f"middrift_{name}"] = vm
    return c


def hmm_features(tape: Path, grid: np.ndarray, variants: dict) -> dict:
    """latent_filter's Python HMM at F5's settings (impact x3, depth 6) and each variant on the same events: their gaps
    on the grid (`py_gap`, `py_gap_NAME`) and each variant's gap minus the base's (`py_diff_NAME`)."""
    from experiments.day.latent_filter import DEFAULTS, replay

    params = {**DEFAULTS, "impact_scale": 3.0, "depth": 6}
    rows, _, _ = replay(tape, params, extra=tuple(variants.values()))
    i = np.clip(np.searchsorted(rows[:, 0], grid - 1e-9), 0, len(rows) - 1)
    # clipped +-5 as Rust's FILTER_CLIP: a filter reset (the book beyond its window) otherwise leaves a few huge gaps
    c = {"py_gap": np.clip(rows[i, 2], -5, 5)}
    for j, name in enumerate(variants):
        g = np.clip(rows[i, 7 + j], -5, 5)
        c[f"py_gap_{name}"] = g
        c[f"py_diff_{name}"] = g - rows[i, 2]
    return c


CLIPS = (5.0, 10.0, 20.0, 1e9)


def level_test(tape: Path, grid: np.ndarray, gm: np.ndarray, st: dict, variants: dict, latent: Path | None,
               minutes: float | None) -> dict:
    """The LEVEL (8 Nov, after the truth test): latent_filter's HMM at F5's settings and each variant (any of its
    --set keys: W, depth, rate, jump, jump_med, jump_sd, impact_scale, drift ...) on the same events, the first
    `minutes`; each gap clipped at 5 / 10 / 20 ticks / not (FILTER_CLIP). With `latent`: its correlation with the true
    gap (latent - mid), overall and in the volatile state. Always: the partial R^2 (%) beyond F5's forecast for the
    mid's 0.4 / 1-s move, fitted on the first 75% of the sample, scored on the last 25%."""
    from experiments.day.latent_filter import DEFAULTS, replay

    params = {**DEFAULTS, "impact_scale": 3.0, "depth": 6}
    names = ["F5"] + list(variants)
    rows, _, _ = replay(tape, params, extra=tuple(variants.values()), until_s=minutes * 60 if minutes else None)
    keep = grid <= rows[-1, 0]
    grid, gm = grid[keep], gm[keep]
    i = np.clip(np.searchsorted(rows[:, 0], grid - 1e-9), 0, len(rows) - 1)
    gaps = {"F5": rows[i, 2]}
    for j, name in enumerate(variants):
        gaps[name] = rows[i, 7 + j]
    pred = st["pred"][keep]
    n = len(grid)
    ys = {}
    for h in (0.4, 1.0):
        k = int(round(h / GRID))
        y = np.full(n, np.nan)
        y[:-k] = gm[k:] - gm[:-k]
        ys[h] = y
    valid = np.isfinite(pred) & (grid >= 30) & np.isfinite(ys[1.0])
    cut = grid[valid][int(FIT_SHARE * valid.sum())]
    fit, test = valid & (grid < cut), valid & (grid >= cut)
    out: dict = {"seconds": float(grid[-1]), "variants": {"F5": {}, **variants}, "rows": {}}
    tg = state = None
    if latent is not None:
        lat = np.loadtxt(latent, delimiter=",", skiprows=1)
        step = float(lat[1, 0] - lat[0, 0])
        li = np.clip(np.rint(grid / step).astype(int), 0, len(lat) - 1)
        tg, state = lat[li, 1] - gm, lat[li, 2]
        out["true_gap_sd"] = {"all": float(tg[valid].std()), "volatile": float(tg[valid & (state == 1)].std())}
    X0 = np.column_stack([np.ones(n), pred])
    for name in names:
        row = {}
        for c in CLIPS:
            g = np.clip(gaps[name], -c, c)
            key = f"clip{c:g}" if c < 1e8 else "noclip"
            cell = {}
            if tg is not None:
                cell["corr_true"] = round(float(np.corrcoef(g[valid], tg[valid])[0, 1]), 4)
                vol = valid & (state == 1)
                cell["corr_true_vol"] = round(float(np.corrcoef(g[vol], tg[vol])[0, 1]), 4)
            for h in (0.4, 1.0):
                X1 = np.column_stack([X0, g])
                b0, b1 = _ols(X0[fit], ys[h][fit]), _ols(X1[fit], ys[h][fit])
                sse0, sse1 = ((ys[h][test] - X0[test] @ b0) ** 2).sum(), ((ys[h][test] - X1[test] @ b1) ** 2).sum()
                cell[f"pr2_{h:g}s"] = round(100 * float(1 - sse1 / sse0), 3)
            row[key] = cell
        out["rows"][name] = row
    return out


def _ols(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    return np.linalg.lstsq(X, y, rcond=None)[0]


def real_test(grid: np.ndarray, gm: np.ndarray, st: dict, c: dict) -> dict:
    n = len(grid)
    pred = st["pred"]
    valid = np.isfinite(pred) & (grid >= 30)
    for v in c.values():
        valid &= np.isfinite(v)
    cut = grid[valid][int(FIT_SHARE * valid.sum())]
    fit, test = valid & (grid < cut), valid & (grid >= cut)
    ys = {}
    for h in HORIZONS:
        k = int(round(h / GRID))
        y = np.full(n, np.nan)
        y[:-k] = gm[k:] - gm[:-k]
        ys[h] = y
    one = st["spread"] == 1
    inv = np.nan_to_num(st["inv"])
    band = test & one & (np.abs(pred) >= BAND[0]) & (np.abs(pred) <= BAND[1]) & np.isfinite(ys[5.0])

    def decide(f: np.ndarray) -> np.ndarray:
        s = np.where(np.abs(f) > NEED, np.sign(f), 0.0)
        return np.where(s * inv < LIMIT, s, 0.0)  # a take the position allows

    base = decide(pred)
    rep: dict = {"grid_points": int(valid.sum()), "cut_s": float(cut), "baseline": {},
                 "band_points": int(band.sum()), "band_base_take_share": float((base[band] != 0).mean()),
                 "band_base_value": {f"{h:g}s": float(np.mean(base[band] * ys[h][band] - 0.5 * np.abs(base[band])))
                                     for h in HORIZONS}}
    for h in HORIZONS:
        f, s = fit & np.isfinite(ys[h]), test & np.isfinite(ys[h])
        X0 = np.column_stack([np.ones(n), pred])
        b0 = _ols(X0[f], ys[h][f])
        r = ys[h][s] - X0[s] @ b0
        rep["baseline"][f"{h:g}s"] = {"coef_pred": float(b0[1]), "test_r2": float(1 - r.var() / ys[h][s].var())}
    rows = {}
    for name, x in c.items():
        mu, sd = x[fit].mean(), x[fit].std() + 1e-12
        zx = (x - mu) / sd
        row = {"sd": float(sd), "corr_pred": float(np.corrcoef(x[valid], pred[valid])[0, 1])}
        for h in HORIZONS:
            f, s = fit & np.isfinite(ys[h]), test & np.isfinite(ys[h])
            X0 = np.column_stack([np.ones(n), pred])
            X1 = np.column_stack([X0, zx])
            b0, b1 = _ols(X0[f], ys[h][f]), _ols(X1[f], ys[h][f])
            sse0, sse1 = ((ys[h][s] - X0[s] @ b0) ** 2).sum(), ((ys[h][s] - X1[s] @ b1) ** 2).sum()
            in0, in1 = ((ys[h][f] - X0[f] @ b0) ** 2).sum(), ((ys[h][f] - X1[f] @ b1) ** 2).sum()
            row[f"{h:g}s"] = {"partial_r2_pct": round(100 * float(1 - sse1 / sse0), 3),
                              "in_sample_pct": round(100 * float(1 - in1 / in0), 3), "ticks_per_sd": round(float(b1[2]), 3)}
            if h == 0.4:
                new = decide(pred + zx * b1[2])
                flip = band & (new != base)
                row["take_flip_share"] = round(float(flip.sum() / max(1, band.sum())), 4)
                row["take_flips"] = int(flip.sum())
                for hh in HORIZONS:
                    gain = (new - base) * ys[hh] - 0.5 * (np.abs(new) - np.abs(base))
                    row[f"flip_value_{hh:g}s"] = round(float(gain[flip].mean()), 3) if flip.any() else 0.0
                    row[f"flip_total_{hh:g}s"] = round(float(gain[flip].sum()), 1)
        rows[name] = row
    rep["candidates"] = rows
    return rep


def truth_test(grid: np.ndarray, gm: np.ndarray, st: dict, c: dict, latent_path: Path) -> dict:
    lat = np.loadtxt(latent_path, delimiter=",", skiprows=1)
    step = float(lat[1, 0] - lat[0, 0])
    idx = np.clip(np.rint(grid / step).astype(int), 0, len(lat) - 1)
    L = lat[idx, 1]
    state = lat[idx, 2]
    jcum = np.cumsum(lat[:, 3])[idx]
    n = len(grid)
    k1 = int(round(1 / GRID))
    past = np.full(n, np.nan)
    past[k1:] = (L[k1:] - L[:-k1]) - (jcum[k1:] - jcum[:-k1])  # the true latent's last 1 s, its own jumps excluded
    sig = dict(c)
    sig["oracle_true_gap"] = L - gm
    sig["oracle_past1s_nojump"] = past
    valid = np.isfinite(st["pred"]) & (grid >= 30) & np.isfinite(past)
    out: dict = {"volatile_share": float(state[valid].mean())}
    tg = L - gm
    out["true_gap_corr"] = {name: round(float(np.corrcoef(np.nan_to_num(x[valid]), tg[valid])[0, 1]), 4)
                            for name, x in sig.items() if not name.startswith("oracle")}
    for target in ("latent", "mid"):
        ser = L if target == "latent" else gm
        res = {}
        for h in TRUTH_HORIZONS:
            k = int(round(h / GRID))
            y = np.full(n, np.nan)
            y[:-k] = ser[k:] - ser[:-k]
            m = valid & np.isfinite(y)
            pred = st["pred"][m]
            X0 = np.column_stack([np.ones(m.sum()), pred])
            b0 = _ols(X0, y[m])
            sse0 = ((y[m] - X0 @ b0) ** 2).sum()
            row = {"pred": round(float(np.corrcoef(pred, y[m])[0, 1]), 4)}
            for name, x in sig.items():
                xm = np.nan_to_num(x[m])
                X1 = np.column_stack([X0, xm])
                b1 = _ols(X1, y[m])
                row[name] = {"corr": round(float(np.corrcoef(xm, y[m])[0, 1]), 4),
                             "beyond_pred_pct": round(100 * float(1 - ((y[m] - X1 @ b1) ** 2).sum() / sse0), 3)}
                if target == "latent" and h == 1.0:
                    vol = m & (state == 1)
                    if vol.sum() > 100:
                        row[name]["corr_volatile"] = round(float(np.corrcoef(np.nan_to_num(x[vol]), y[vol])[0, 1]), 4)
            res[f"{h:g}s"] = row
        out[target] = res
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("tape", type=Path)
    ap.add_argument("--pred", type=Path, required=True)
    ap.add_argument("--cache", type=Path, help="tape_stats' replay cache (.npz)")
    ap.add_argument("--latent", type=Path, help="the generated tape's true latent: the truth test")
    ap.add_argument("--set", action="append", default=[], help="another Kalman setting NAME=tau,sv,ql,r")
    ap.add_argument("--only", help="comma-separated settings to run (default all; 'none' for no Kalman)")
    ap.add_argument("--hmm", action="append", default=[],
                    help="also run latent_filter's HMM, F5's settings and this variant: NAME=key=value,key=value")
    ap.add_argument("--level", action="append", default=[],
                    help="the level test instead (level_test): a variant NAME=key=value,key=value (repeatable)")
    ap.add_argument("--minutes", type=float, help="--level: replay only the first N minutes")
    ap.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    if a.level:
        variants = {}
        for item in a.level:
            name, kv = item.split("=", 1)
            variants[name] = {k: float(v) for k, v in (x.split("=", 1) for x in kv.split(","))}
        d = load(a.tape, a.cache)
        grid, gm = grid_of(d)
        st = on_grid(read_pred(a.pred), grid)
        rep = {"tape": str(a.tape), "level": level_test(a.tape, grid, gm, st, variants, a.latent, a.minutes)}
        text = json.dumps(rep, indent=1)
        print(text)
        if a.json:
            a.json.write_text(text)
        return 0
    settings = dict(SETTINGS)
    for item in a.set:
        k, v = item.split("=", 1)
        settings[k] = tuple(float(x) for x in v.split(","))
    if a.only:
        settings = {} if a.only == "none" else {k: settings[k] for k in a.only.split(",")}
    d = load(a.tape, a.cache)
    grid, gm = grid_of(d)
    st = on_grid(read_pred(a.pred), grid)
    c = features(gm, st, settings)
    if a.hmm:
        variants = {}
        for item in a.hmm:
            name, kv = item.split("=", 1)
            variants[name] = {k: float(v) for k, v in (x.split("=", 1) for x in kv.split(","))}
        c.update(hmm_features(a.tape, grid, variants))
    rep = {"tape": str(a.tape), "settings": settings, "real": real_test(grid, gm, st, c)}
    if a.latent:
        rep["truth"] = truth_test(grid, gm, st, c, a.latent)
    text = json.dumps(rep, indent=1)
    print(text)
    if a.json:
        a.json.write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
