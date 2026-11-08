"""Calibrate tape_gen against a validation scoreboard: generator parameters under which our bots score in the server's
order and ratios (8 Nov, round 3; docs/GENERATOR_PLAN.md, Phase 2).

The premise: the server's validation tape is one draw of the organisers' generator, and the scores our uploaded bots
made on it are a fingerprint of its regime. A tape_gen parameter set whose 12,000-s draws give the same bots the same
order and roughly the same ratios is a generator of tapes like the validation one (simulation-based inference with
the bots as summary statistics). Round 2's scoreboard (SCOREBOARD, 14 bots; the composite's file is lost) is built in;
another round's goes in with `--scoreboard FILE.json` ({"bot": score}).

The bots (BOTS): the ridge family through the Rust twin (`arena.qsim_rust.run_batch`, each one's `--set` line from
ridge_maker.rs's doc comment; E2, V2, T1, T2, L1, L3, L8, L9), the flow followers M2, M3, M4, RA (and the slow ridge +
flow-bias H1, L6) through the starter's `simulator.main --no-logs`. The measures (`compare`): Spearman's rank
correlation, the asinh error (RMSE of asinh(sim / 50k) - asinh(target / 50k): a log-ratio error for large scores that
stays finite through zero and sign changes), the mean |log ratio| over the bots positive on both, and the scale-free
fit (the common factor c minimising the log error, and the error left after it).

Subcommands:

- `score TAPE...`: the bots on given tapes (real or generated), against the scoreboard (`--target public` compares
  with round 2's public-tape scores instead, PUBLIC).
- `draw`: `--params` (a fitted tape_gen model) with `--opts JSON` (tape_gen latent options merged in, e.g.
  '{"jump_rate": 1, "jump_size": 1.5}', or a PRESETS name: `r2_validation`, `r3_public_stats`), `--seeds`,
  `--seconds`; generates the draws in `--dir` and scores them.
- `search`: a random search over SPACE (the latent options added for v2, PRIOR for the ranges; `--trials N`, `--seeds`,
  `--seconds`, `--jobs`), each trial its own process (generate, run, score, delete the tapes), one JSON line per
  trial appended to `--out`; the best trials are printed, ranked by OBJECTIVE (asinh error + 0.5 x (1 - Spearman)).
  `--fix JSON` holds options fixed, `--only K1,K2` searches only those keys (the rest at their defaults); `--around
  JSON --spread 0.3 [--vary K1,K2]` searches locally instead (each numeric option times exp(U(-spread, spread))).
- `best FILE.jsonl`: the ranking of a search's trials so far (`--target public --rescore` against the public scores).
- `rank`: bots (`--bots L9,B1,L3`) on `--seeds` draws of a parameter set, no scoreboard: mean, sd, 5th percentile, min
  (and the real tape's score with `--real`), and the pairwise wins over the draws; the draws made `--jobs` at a time
  and deleted once run.
- `stats TAPE...`: a tape's price statistics (tape_stats, impact_curve), to match a generator to a real tape.
- `jumpflow TAPE...`: the aggressive flow around 3+ tick jumps timed by the latent (the 0.1-s insert centre) and by
  the mid (jump_flow): whether the big IOC orders the jump's way come before the latent moves or after it.
- `fitstats --around JSON --real TAPE`: a local search without bots for the options whose draw's statistics are
  nearest the real tape's (STAT_KEYS, the RMS log ratio): a new round's regime before any validation score exists.

    uv run python -m experiments.day.tape_gen --fit data/arena/round2/round2_public.csv --params-out P.json
    uv run python -m experiments.day.gen_calibrate score data/arena/round2/round2_public.csv --target public --threads 5
    uv run python -m experiments.day.gen_calibrate draw --params P.json --seeds 1-3 --seconds 12000 --dir DIR --jobs 5
    uv run python -m experiments.day.gen_calibrate search --params P.json --trials 60 --seeds 1-2 --seconds 6000 \
        --dir DIR --jobs 5 --out DIR/search.jsonl
    uv run python -m experiments.day.gen_calibrate best DIR/search.jsonl
    uv run python -m experiments.day.gen_calibrate rank --params P3.json --opts BEST --bots L9,B1,L3 --seeds 1-30 \
        --dir DIR --real data/arena/round3/round3_public.csv
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from arena import qsim_rust
from experiments.day import tape_gen

ROOT = Path(__file__).resolve().parents[3]
CAND = ROOT / "python" / "bots" / "qminers" / "candidates"

# The ridge family's Rust settings (ridge_maker.rs's doc comment; python/tests/test_arena_rust.py)
C12 = {"POSITION_LIMIT": 1000, "EXPOSURE": 100, "CANCEL_FREE": 1.0, "HEDGE": 1, "MODEL_MEMORY_US": 100_000_000_000,
       "HORIZON_US": 400_000, "DEAD_ZONE": 0.18, "QUOTEFEAT": 1, "FLOWGRP": 2, "FLOWGRP_CAP": 20, "FLOWGRP_US": 1_000_000}
E2 = {**C12, "FT_SZ": 200, "FT_GAP_MS": 50, "SKEW_K": 0.025, "FT_EDGE": 0.25, "QUOTE_SIZE": 200, "EXPOSURE": 30,
      "KEEP_LOTS": 20, "KEEP_TH": 0.3}
V2 = {**E2, "EXPOSURE": 100, "OBS_CAP": 2000, "VOL_EXP": 2, "VOL_REF": 2.5, "VOL_US": 5_000_000, "VOL_MAX": 100,
      "VOL_NOHEDGE": 1}
T1 = {**E2, "EXPOSURE": 100, "QUOTE_SIZE": 1, "FT_EDGE": 0.15, "FT_MAXSPREAD": 1}
T2 = {"POSITION_LIMIT": 1000, "EXPOSURE": 100, "HEDGE": 1, "MODEL_MEMORY_US": 100_000_000_000, "HORIZON_US": 400_000,
      "DEAD_ZONE": 0.18, "QUOTEFEAT": 1, "FLOWGRP": 2, "FLOWGRP_CAP": 20, "FLOWGRP_US": 1_000_000, "FT_EDGE": 0.15,
      "FT_SZ": 200, "FT_GAP_MS": 50, "QUOTE_SIZE": 1, "KEEP_LOTS": 20, "KEEP_TH": 0.3, "FT_MAXSPREAD": 1,
      "FT_ROOM_LIVE": 1}
L1 = {**T2, "LIQ": 1}
L3 = {**L1, "QUOTE_SIZE": 0}
L8 = {**L1, "QS_RATE": 2.5}
L9 = {**L3, "POSITION_LIMIT": 100, "IMPACT_US": 500_000, "HUBER": 6.0, "RIDGE_MIN": 30, "RIDGE_FRAC": 0.003}
B1 = {**L9, "QUOTE_SIZE": 1, "QS_RATE": 2.5}  # R3-B1 (r3_B1_huber_quote_switch.py): L9 with L8's quote switch
# name -> ("rust", params) or ("py", candidate file)
BOTS = {
    "E2": ("rust", E2), "V2": ("rust", V2), "T1": ("rust", T1), "T2": ("rust", T2), "L1": ("rust", L1),
    "L3": ("rust", L3), "L8": ("rust", L8), "L9": ("rust", L9), "B1": ("rust", B1),
    "M2": ("py", CAND / "r2_M2_flow_trend.py"), "M3": ("py", CAND / "r2_M3_flow_stop_gated.py"),
    "M4": ("py", CAND / "r2_M4_flow_window.py"), "RA": ("py", CAND / "r2_RA_flow_window.py"),
    "H1": ("py", CAND / "r2_H1_flow_bias.py"), "L6": ("py", CAND / "r2_L6_pure_flowbias.py"),
    "F1": ("py", CAND / "r3_F1_latent_filter.py"),  # R3-F1: L9 + the latent filter's features (+862,764 on r3 validation)
}
# Round 3's validation tape (12,000 s): the server's scores so far
SCOREBOARD_R3 = {"F1": 862_764}
# Round 2's validation tape (12,000 s), the server's scores (data/arena/round2/HANDOVER.md, CANDIDATES.md)
SCOREBOARD = {"E2": -41_499, "V2": 71_864, "M3": 366_342, "M2": 376_082, "M4": 441_088, "RA": 467_703, "T1": 485_667,
              "T2": 490_359, "H1": 567_740, "L1": 771_770, "L6": 798_269, "L3": 804_018, "L8": 826_778, "L9": 873_719}
# Round 2's public tape (6,000 s), the same bots locally (CANDIDATES.md; IDEAS.md), for the second check
PUBLIC = {"E2": 47_098, "V2": 167_288, "M2": 116_620, "M3": 130_251, "RA": 165_459, "T1": 191_984, "T2": 194_391,
          "H1": 223_773, "L1": 269_920, "L3": 294_098, "L8": 296_181, "L9": 317_057, "L6": 294_522}
SEARCH_BOTS = ("E2", "V2", "T2", "L1", "L3", "L9", "M2", "M4")
# Calibrated option sets, usable as `--opts NAME` (each on its round's tape_gen fit: `tape_gen --fit` of the public tape)
PRESETS = {
    # round 2's validation tape (search trial 94, 8 Nov 01:30): Spearman 0.974 over the 14 bots on 3 draws, the level
    # about 0.75 of the server's (IDEAS.md, "Calibrating the generator to round 2's validation scoreboard")
    "r2_validation": {"impact_sqrt": 0.0365, "f_limit_latent": 1, "jx_rate_off": 0.004, "jx_dwell_off": 600,
                      "jx_dwell_on": 200, "jx_median": 5.6, "jx_logsd": 0.95, "jx_warn_s": 2, "jx_warn_k": 1.2,
                      "jx_lead_s": 0.5, "jx_lead_min": 500, "jx_rate_on": 0.3, "jx_lead_extra": 3},
    # round 3's public tape, its statistics only (fitstats trial 17 around r2_validation plus a transient impact): no
    # scoreboard yet
    "r3_public_stats": {"impact_sqrt": 0.0528, "f_limit_latent": 1, "jx_rate_off": 0.0046, "jx_dwell_off": 597.9,
                        "jx_dwell_on": 142.9, "jx_median": 6.66, "jx_logsd": 0.79, "jx_warn_s": 2.47, "jx_warn_k": 1.15,
                        "jx_lead_s": 0.5, "jx_lead_min": 500, "jx_rate_on": 0.4, "jx_lead_extra": 2.0, "stale_s": 0.216,
                        "impact_delay": -0.22, "impact_tau": 6.8},
}


def parse_opts(text) -> dict:
    """`--opts`: a PRESETS name or a JSON object."""
    if not text:
        return {}
    return dict(PRESETS[text]) if text in PRESETS else json.loads(text)
ASINH_SCALE = 50_000.0


def run_py(file: Path, tape: Path, logdir: Path) -> float:
    out = subprocess.run([sys.executable, "-m", "simulator.main", "--strategy", str(file), "--backtest", str(tape),
                          "--log-dir", str(logdir), "--no-logs"], capture_output=True, text=True, cwd=ROOT)
    m = re.search(r"^pnl=(-?[0-9.]+)", out.stdout, re.M)
    return float(m.group(1)) if m else float("nan")


def _py_job(job):
    name, file, tape, logdir = job
    return name, str(tape), run_py(Path(file), Path(tape), Path(logdir))


def run_bots(tapes: list[Path], bots, threads: int, logroot: Path) -> dict:
    """bot -> [pnl per tape]: the Rust ones in one batch on `threads` threads, the Python ones in a pool of `threads`."""
    out = {}
    rust = [b for b in bots if BOTS[b][0] == "rust"]
    if rust:
        rows = qsim_rust.run_batch("ridge_maker", [BOTS[b][1] for b in rust], tapes, threads)
        for b, per_file in zip(rust, rows):
            out[b] = [r.get("pnl", float("nan")) for r in per_file]
    py = [b for b in bots if BOTS[b][0] == "py"]
    if py:
        jobs = [(b, str(BOTS[b][1]), str(t), str(logroot / f"{b}_{i}")) for b in py for i, t in enumerate(tapes)]
        res = {}
        if threads > 1:
            with ProcessPoolExecutor(min(threads, len(jobs))) as ex:
                for name, tape, pnl in ex.map(_py_job, jobs):
                    res[(name, tape)] = pnl
        else:
            for job in jobs:
                name, tape, pnl = _py_job(job)
                res[(name, tape)] = pnl
        for b in py:
            out[b] = [res[(b, str(t))] for t in tapes]
    return out


def spearman(a, b) -> float:
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    if ra.std() == 0 or rb.std() == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


def compare(sim: dict, target: dict, scale: float = 1.0) -> dict:
    """The fit of the mean scores `sim` (bot -> [pnl, ...], times `scale`) to `target` (bot -> score)."""
    names = [b for b in target if b in sim and np.isfinite(np.mean(sim[b]))]
    s = np.array([scale * float(np.mean(sim[b])) for b in names])
    t = np.array([float(target[b]) for b in names])
    asinh = float(np.sqrt(np.mean((np.arcsinh(s / ASINH_SCALE) - np.arcsinh(t / ASINH_SCALE)) ** 2)))
    pos = (s > 0) & (t > 0)
    logr = np.log(s[pos] / t[pos]) if pos.any() else np.array([np.nan])
    c = float(np.exp(-logr.mean())) if pos.any() else float("nan")
    rho = spearman(s, t)
    return {"bots": names, "sim": s.round(0).tolist(), "target": t.tolist(), "spearman": rho, "asinh": asinh,
            "logratio": float(np.abs(logr).mean()), "scale_c": c, "logratio_after_c": float(np.abs(logr - logr.mean()).mean()),
            "sign_misses": int(((s > 0) != (t > 0)).sum()), "objective": objective(asinh, rho)}


def objective(asinh: float, rho: float) -> float:
    return asinh + 0.5 * (1.0 - (rho if np.isfinite(rho) else -1.0))


def print_compare(sim: dict, target: dict, scale: float = 1.0, title: str = "") -> dict:
    cmp = compare(sim, target, scale)
    if title:
        print(title)
    order = np.argsort(cmp["target"])
    print(f"  {'bot':4s} {'target':>10s} {'sim mean':>10s} {'ratio':>6s}  per tape")
    for i in order:
        b = cmp["bots"][i]
        per = " ".join(f"{scale * v:,.0f}" for v in sim[b])
        ratio = cmp["sim"][i] / cmp["target"][i] if cmp["target"][i] else float("nan")
        print(f"  {b:4s} {cmp['target'][i]:>10,.0f} {cmp['sim'][i]:>10,.0f} {ratio:>6.2f}  {per}")
    print(f"  spearman {cmp['spearman']:.3f}  asinh err {cmp['asinh']:.3f}  |log ratio| {cmp['logratio']:.3f}  "
          f"scale c {cmp['scale_c']:.2f} (|log ratio| after it {cmp['logratio_after_c']:.3f})  sign misses "
          f"{cmp['sign_misses']}  objective {cmp['objective']:.3f}")
    return cmp


def parse_seeds(text: str) -> list[int]:
    out = []
    for part in text.split(","):
        lo, _, hi = part.partition("-")
        out += list(range(int(lo), int(hi or lo) + 1))
    return out


def with_opts(params: dict, opts: dict) -> dict:
    """The fitted params with latent options merged in (top-level keys `g_rate`, `f_rate` too)."""
    p = copy.deepcopy(params)
    for k, v in opts.items():
        if k in ("g_rate", "f_rate"):
            p[k] = v
        else:
            p["latent"][k] = v
    return p


def _gen(job):
    params, seed, seconds, out = job
    if not Path(out).exists():
        tape_gen.generate(params, seed, seconds, Path(out))
    return out


# The search space: tape_gen's v2 latent options (defaults off), each a sampler; the structure is Phase 1's (8 Nov):
# sqrt impact, IOC limits at the latent +- 1, clustered lognormal jumps announced by wider inserts, informed IOC
# orders before them, fast stale cancels after them, and a slow drift
PRIOR = {
    "impact_sqrt": ("uniform", 0.025, 0.05),
    "f_limit_latent": ("choice", [0, 1]),
    "jx_rate_on": ("loguniform", 0.08, 0.5),
    "jx_rate_off": ("loguniform", 0.001, 0.03),
    "jx_dwell_on": ("loguniform", 80.0, 600.0),
    "jx_dwell_off": ("loguniform", 200.0, 2000.0),
    "jx_median": ("uniform", 3.0, 8.0),
    "jx_logsd": ("uniform", 0.6, 1.1),
    "jx_warn_s": ("uniform", 0.5, 3.0),
    "jx_warn_k": ("uniform", 0.0, 2.0),
    "jx_stale_s": ("loguniform", 0.005, 0.25),
    "jx_lead_extra": ("choice_or_uniform", 0.0, 10.0),
    "jx_lead_s": ("uniform", 0.2, 1.0),
    "jx_lead_min": ("choice", [0, 300, 500]),
    "stale_s": ("loguniform", 0.08, 0.4),
    "drift_sd": ("choice_or_uniform", 0.0, 0.15),
    "drift_tau": ("loguniform", 100.0, 1500.0),
}


def sample(rng: np.random.Generator, only=None) -> dict:
    out = {}
    for k, spec in PRIOR.items():
        if only and k not in only:
            continue
        kind = spec[0]
        if kind == "uniform":
            out[k] = float(rng.uniform(spec[1], spec[2]))
        elif kind == "loguniform":
            out[k] = float(math.exp(rng.uniform(math.log(spec[1]), math.log(spec[2]))))
        elif kind == "choice":
            out[k] = spec[1][int(rng.integers(len(spec[1])))]
        elif kind == "choice_or_uniform":  # off half the time
            out[k] = 0.0 if rng.random() < 0.5 else float(rng.uniform(spec[1], spec[2]))
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in out.items()}


CATEGORICAL = {"f_limit_latent", "jx_lead_min", "jump_df", "vol_impact", "continuous", "spread2"}


def perturb(rng: np.random.Generator, base: dict, spread: float, vary=None) -> dict:
    """A local draw around `base`: each numeric option (not CATEGORICAL, not 0) times exp(U(-spread, spread))."""
    out = dict(base)
    for k, v in base.items():
        if (vary and k not in vary) or k in CATEGORICAL or isinstance(v, bool) or not isinstance(v, (int, float)) or v == 0:
            continue
        out[k] = round(float(v * math.exp(rng.uniform(-spread, spread))), 4)
    return out


def trial(job) -> dict:
    """One search trial in its own process: generate the seeds, run the bots on one thread, score, delete the tapes."""
    tid, params, opts, seeds, seconds, workdir, bots, target, scale = job
    t0 = time.time()
    p = with_opts(params, opts)
    wd = Path(workdir) / f"t{tid}"
    wd.mkdir(parents=True, exist_ok=True)
    files = []
    try:
        for s in seeds:
            f = wd / f"s{s}.csv"
            tape_gen.generate(p, s, seconds, f)
            files.append(f)
        sim = run_bots(files, bots, 1, wd)
        stats = {**tape_stats(files[0]), **impact_curve(files[0])}
    except Exception as exc:  # a bad corner of the space: recorded, not fatal
        return {"trial": tid, "opts": opts, "error": repr(exc)}
    finally:
        for f in files:
            f.unlink(missing_ok=True)
    cmp = compare(sim, target, scale)
    return {"trial": tid, "opts": opts, "sim": {b: v for b, v in sim.items()}, "scale": scale, "spearman": cmp["spearman"],
            "asinh": cmp["asinh"], "logratio": cmp["logratio"], "scale_c": cmp["scale_c"], "objective": cmp["objective"],
            "sign_misses": cmp["sign_misses"], "stats": stats, "seconds": round(time.time() - t0, 1)}


IMPACT_BINS = (60, 250, 500, 1000, 10**9)


def tape_stats(path) -> dict:
    """A tape's price statistics on a 1-s grid (tape_character.replay): the sd of the mid's change over 1, 10, 60 and
    300 s, the mid's changes a second, the 1- and 2-tick spreads' shares, the mid's move 5 s after an IOC order by its
    size (ticks, its way; from the grid, so +-1 s)."""
    from experiments.day.tape_character import replay
    mid, spread, f, changes = replay(Path(path))
    out = {"seconds": len(mid), "changes_s": round(changes / max(1, len(mid)), 3)}
    for h in (1, 10, 60, 300):
        d = mid[h:] - mid[:-h]
        out[f"sd{h}"] = round(float(np.nanstd(d)), 2)
    out["one_tick"] = round(float((spread == 1).mean()), 3)
    out["two_tick"] = round(float((spread == 2).mean()), 3)
    if len(f):
        i = np.minimum(f[:, 0].astype(int), len(mid) - 1)
        ok = i + 6 < len(mid)
        move = (mid[np.minimum(i + 5, len(mid) - 1)] - mid[np.maximum(i - 1, 0)]) * np.where(f[:, 1] == 0, 1, -1)
        lo = 0
        for hi in IMPACT_BINS:
            sel = ok & (f[:, 2] > lo) & (f[:, 2] <= hi)
            out[f"imp<={hi if hi < 10**9 else 'max'}"] = round(float(np.nanmean(move[sel])), 2) if sel.any() else float("nan")
            lo = hi
    return out


CURVE_H = (0.1, 0.5, 2.0, 5.0, 15.0, 60.0)


def impact_curve(path, big: int = 500) -> dict:
    """The mid's mean move (ticks, the order's way) CURVE_H seconds after an IOC order of `big`+ lots, from the mid just
    before it, in event time (tape_book's Book): how fast a big order's impact arrives. Also the latent-price test
    (tape_gen's docstring): at a 1-tick spread, the share of limit inserts landing at their own touch (not behind it)
    when the mid has moved their way 0.5 s later (`touch|up`) and against it (`touch|down`), every 5th insert."""
    from experiments.day.tape_book import Book
    book = Book()
    mt, mv, fb, gi = [], [], [], []
    last = None
    n = 0
    with Path(path).open() as fh:
        next(fh)
        for line in fh:
            t, op, oid, side, vol, price, life = line.rstrip("\n").split(",")
            t = float(t)
            if op == "Insert":
                sd = 0 if side == "B" else 1
                if life == "F" and int(vol) >= big and last is not None:
                    fb.append((t, 1 if sd == 0 else -1, last))
                elif life != "F":
                    n += 1
                    bb, ba = book.best
                    if n % 5 == 0 and bb is not None and ba is not None and ba - bb == 1:
                        px = int(price)
                        gi.append((t, 1 if sd == 0 else -1, px == (bb if sd == 0 else ba), last))
                book.insert(oid, sd, int(price), int(vol), life == "F")
            else:
                book.cancel(oid)
            bb, ba = book.best
            if bb is not None and ba is not None:
                m = (bb + ba) / 2
                if m != last:
                    mt.append(t)
                    mv.append(m)
                    last = m
    mt, mv = np.array(mt), np.array(mv)
    out = {}
    if len(mv) > 1:  # moves of 3+ ticks within 50 ms, at most one a second (Phase 1's jumps, roughly)
        after = mv[np.clip(np.searchsorted(mt, mt + 0.05, side="right") - 1, 0, len(mv) - 1)]
        big_move = np.abs(after - np.r_[mv[0], mv[:-1]]) >= 3
        n_j, last_j = 0, -10.0
        for tj in mt[big_move]:
            if tj - last_j > 1.0:
                n_j += 1
                last_j = tj
        out["jumps3_per_ks"] = round(1000.0 * n_j / max(1.0, mt[-1] - mt[0]), 1)
    if fb:
        f = np.array(fb)
        for h in CURVE_H:
            after = mv[np.clip(np.searchsorted(mt, f[:, 0] + h, side="right") - 1, 0, len(mv) - 1)]
            out[f"big@{h:g}s"] = round(float(((after - f[:, 2]) * f[:, 1]).mean()), 2)
    if gi:
        g = np.array(gi, dtype=float)
        after = mv[np.clip(np.searchsorted(mt, g[:, 0] + 0.5, side="right") - 1, 0, len(mv) - 1)]
        move = (after - g[:, 3]) * g[:, 1]
        out["touch|up"] = round(float(g[move > 0, 2].mean()), 3) if (move > 0).any() else float("nan")
        out["touch|down"] = round(float(g[move < 0, 2].mean()), 3) if (move < 0).any() else float("nan")
    return out


def _stats_job(path):
    return str(path), {**tape_stats(path), **impact_curve(path)}


def print_stats(rows) -> None:
    keys = list(rows[0][1])
    print("  " + " ".join(f"{k:>9s}" for k in keys) + "  tape")
    for name, st in rows:
        print("  " + " ".join(f"{st[k]:>9}" for k in keys) + f"  {Path(name).name}")


def cmd_stats(args) -> int:
    with ProcessPoolExecutor(min(args.jobs, len(args.tapes))) as ex:
        rows = list(ex.map(_stats_job, args.tapes))
    print_stats(rows)
    return 0


def cmd_score(args) -> int:
    target = PUBLIC if args.target == "public" else load_target(args)
    bots = args.bots.split(",") if args.bots else [b for b in BOTS if b in target]
    logroot = args.dir or Path(os.environ.get("TMPDIR", "/tmp")) / "gen_calibrate_logs"
    sim = run_bots([Path(t) for t in args.tapes], bots, args.threads, logroot)
    print_compare(sim, target, args.scale, f"{len(args.tapes)} tape(s) against the {args.target} scores")
    if args.out:
        args.out.write_text(json.dumps({"tapes": [str(t) for t in args.tapes], "sim": sim}))
    return 0


def load_target(args) -> dict:
    if getattr(args, "scoreboard", None):
        return json.loads(Path(args.scoreboard).read_text())
    return PUBLIC if getattr(args, "target", "validation") == "public" else SCOREBOARD


def cmd_draw(args) -> int:
    params = with_opts(json.loads(args.params.read_text()), parse_opts(args.opts))
    args.dir.mkdir(parents=True, exist_ok=True)
    seeds = parse_seeds(args.seeds)
    files = [args.dir / f"{args.tag}_{args.seconds:.0f}s_{s}.csv" for s in seeds]
    t0 = time.time()
    with ProcessPoolExecutor(min(args.jobs, len(files))) as ex:
        list(ex.map(_gen, [(params, s, args.seconds, str(f)) for s, f in zip(seeds, files)]))
    print(f"generated {len(files)} tapes in {time.time() - t0:.0f} s", flush=True)
    if args.stats:
        with ProcessPoolExecutor(min(args.jobs, len(files))) as ex:
            print_stats(list(ex.map(_stats_job, [str(f) for f in files])))
        if args.stats_only:
            files = [] if args.keep else files
            for f in files:
                f.unlink(missing_ok=True)
            return 0
    target = PUBLIC if args.target == "public" else load_target(args)
    bots = args.bots.split(",") if args.bots else [b for b in BOTS if b in target]
    sim = run_bots(files, bots, args.jobs, args.dir / "logs")
    print_compare(sim, target, args.scale, f"{args.tag}: {len(files)} draws of {args.seconds:.0f} s against the {args.target} scores")
    if args.out:
        args.out.write_text(json.dumps({"opts": parse_opts(args.opts), "seeds": seeds, "seconds": args.seconds, "sim": sim}))
    if not args.keep:
        for f in files:
            f.unlink(missing_ok=True)
    return 0


def _gen_files(args, params) -> list[Path]:
    args.dir.mkdir(parents=True, exist_ok=True)
    seeds = parse_seeds(args.seeds)
    files = [args.dir / f"{args.tag}_{args.seconds:.0f}s_{s}.csv" for s in seeds]
    with ProcessPoolExecutor(min(args.jobs, len(files))) as ex:
        list(ex.map(_gen, [(params, s, args.seconds, str(f)) for s, f in zip(seeds, files)]))
    return files


JUMPFLOW_WINDOWS = ((-2.0, -0.5), (-0.5, -0.2), (-0.2, -0.1), (-0.1, 0.0), (0.0, 0.1), (0.1, 0.3), (0.3, 1.0))


def jump_flow(path, step: float = 0.1, big: int = 500) -> dict:
    """The aggressive flow around the latent's 3+ tick jumps, timed two ways: by the latent (the mean new bid insert
    price plus the mean new ask insert price, halved, over `step`-s bins; a bin whose centre moved 3+ ticks and stays
    moved two bins on, at most one a second) and by the mid (a 3+ tick move within 50 ms, tape_book's Book, at most one
    a second). Per window around the onset: the signed IOC lots per jump (the jump's way positive) and the count of
    `big`+ lot IOC orders the jump's way and against it. Informed flow that a bot could act on would show before the
    latent's onset; orders priced off an already-moved latent show at it."""
    from experiments.day.tape_book import Book
    book = Book()
    ins = ([], [], [], [])  # bid t, bid price, ask t, ask price
    fr, mt, mv = [], [], []
    last = None
    with Path(path).open() as fh:
        next(fh)
        for line in fh:
            t, op, oid, side, vol, price, life = line.rstrip("\n").split(",")
            t = float(t)
            if op == "Insert":
                sd = 0 if side == "B" else 1
                if life == "F":
                    fr.append((t, 1 if sd == 0 else -1, int(vol)))
                else:
                    ins[2 * sd].append(t)
                    ins[2 * sd + 1].append(int(price))
                book.insert(oid, sd, int(price), int(vol), life == "F")
            else:
                book.cancel(oid)
            bb, ba = book.best
            if bb is not None and ba is not None and (bb + ba) / 2 != last:
                last = (bb + ba) / 2
                mt.append(t)
                mv.append(last)
    n = int(max(ins[0][-1], ins[2][-1]) / step) + 1

    def binmean(ts, ps):
        k = (np.array(ts) / step).astype(int)
        tot = np.bincount(k, weights=np.array(ps, float), minlength=n)
        cnt = np.bincount(k, minlength=n)
        m = np.where(cnt > 0, tot / np.maximum(cnt, 1), np.nan)
        for i in range(1, n):
            if np.isnan(m[i]):
                m[i] = m[i - 1]
        return m

    c = (binmean(ins[0], ins[1]) + binmean(ins[2], ins[3])) / 2
    lat, last_j = [], -10.0
    for k in range(2, n - 2):
        d = c[k] - c[k - 1]
        if abs(d) >= 3 and abs(c[k + 1] - c[k - 1]) >= 3 and abs(c[k + 2] - c[k - 1]) >= 3 and k * step - last_j > 1.0:
            lat.append((k * step, np.sign(d)))
            last_j = k * step
    mt, mv = np.array(mt), np.array(mv)
    after = mv[np.clip(np.searchsorted(mt, mt + 0.05, side="right") - 1, 0, len(mv) - 1)]
    d = after - np.r_[mv[0], mv[:-1]]
    mid, last_j = [], -10.0
    for i in np.where(np.abs(d) >= 3)[0]:
        if mt[i] - last_j > 1.0:
            mid.append((mt[i], np.sign(d[i])))
            last_j = mt[i]
    f = np.array(fr, float)
    out = {}
    for name, jumps in (("latent", lat), ("mid", mid)):
        rows = []
        for lo, hi in JUMPFLOW_WINDOWS:
            signed, w, a = 0.0, 0, 0
            for tj, sg in jumps:
                i, j = np.searchsorted(f[:, 0], [tj + lo, tj + hi])
                seg = f[i:j]
                signed += float((seg[:, 1] * seg[:, 2]).sum() * sg)
                bg = seg[seg[:, 2] >= big]
                w += int((bg[:, 1] == sg).sum())
                a += int((bg[:, 1] != sg).sum())
            rows.append({"window": [lo, hi], "signed_lots_per_jump": round(signed / max(1, len(jumps)), 1),
                         "big_with": w, "big_against": a})
        out[name] = {"jumps": len(jumps), "windows": rows}
    return out


def cmd_jumpflow(args) -> int:
    for path in args.tapes:
        res = jump_flow(path)
        for name in ("latent", "mid"):
            r = res[name]
            print(f"{Path(path).name}: {r['jumps']} jumps of 3+ ticks timed by the {name}")
            for w in r["windows"]:
                print(f"  [{w['window'][0]:+.1f}, {w['window'][1]:+.1f}) s: signed IOC lots per jump "
                      f"{w['signed_lots_per_jump']:+8.1f}, 500+ lot orders with / against {w['big_with']} / {w['big_against']}")
    return 0


STAT_KEYS = ("changes_s", "sd1", "sd10", "sd60", "sd300", "two_tick", "big@0.1s", "big@0.5s", "big@5s", "big@15s",
             "touch|up", "touch|down", "jumps3_per_ks")


def stat_distance(st: dict, ref: dict) -> float:
    """The RMS log ratio of a draw's statistics to a real tape's (STAT_KEYS; the 1-tick share as its complement)."""
    errs = []
    for k in STAT_KEYS:
        a, b = st.get(k), ref.get(k)
        if a is None or b is None or not (np.isfinite(a) and np.isfinite(b)) or a <= 0 or b <= 0:
            continue
        errs.append(math.log(a / b) ** 2)
    return float(math.sqrt(np.mean(errs))) if errs else float("nan")


def _fitstats_trial(job):
    tid, params, opts, seed, seconds, workdir, ref = job
    f = Path(workdir) / f"fs{tid}.csv"
    try:
        tape_gen.generate(with_opts(params, opts), seed, seconds, f)
        st = {**tape_stats(f), **impact_curve(f)}
    except Exception as exc:
        return {"trial": tid, "opts": opts, "error": repr(exc)}
    finally:
        f.unlink(missing_ok=True)
    return {"trial": tid, "opts": opts, "stats": st, "distance": stat_distance(st, ref)}


def cmd_fitstats(args) -> int:
    """A local search (no bots) for the options whose draws' statistics match a real tape's."""
    params = json.loads(args.params.read_text())
    ref = {**tape_stats(args.real), **impact_curve(args.real)}
    print("real:", json.dumps({k: ref.get(k) for k in STAT_KEYS}))
    around = parse_opts(args.around)
    vary = set(args.vary.split(",")) if args.vary else None
    rng = np.random.default_rng(args.rng)
    args.dir.mkdir(parents=True, exist_ok=True)
    jobs = [(0, params, around, args.seed, args.seconds, str(args.dir), ref)]
    jobs += [(i + 1, params, perturb(rng, around, args.spread, vary), args.seed, args.seconds, str(args.dir), ref)
             for i in range(args.trials)]
    rows = []
    with ProcessPoolExecutor(args.jobs) as ex, args.out.open("a") as fh:
        for res in ex.map(_fitstats_trial, jobs):
            fh.write(json.dumps(res) + "\n")
            fh.flush()
            if "error" not in res:
                rows.append(res)
    rows.sort(key=lambda r: r["distance"])
    for r in rows[:args.top]:
        print(f"trial {r['trial']}: distance {r['distance']:.3f}\n   {json.dumps(r['opts'])}\n   "
              + json.dumps({k: r["stats"].get(k) for k in STAT_KEYS}))
    return 0


def add_extra_bots(specs) -> None:
    """`--extra NAME=FILE`: a Python bot file run by simulator.main under NAME."""
    for spec in specs or []:
        name, _, file = spec.partition("=")
        BOTS[name] = ("py", Path(file).resolve())


def cmd_rank(args) -> int:
    """Bots ranked on a parameter set's draws: mean, sd, 5th percentile, min, and pairwise wins over the seeds."""
    add_extra_bots(args.extra)
    params = with_opts(json.loads(args.params.read_text()), parse_opts(args.opts))
    bots = args.bots.split(",")
    sim = {b: [] for b in bots}
    seeds = parse_seeds(args.seeds)
    chunk = max(1, args.jobs)
    t0 = time.time()
    for i in range(0, len(seeds), chunk):  # a chunk of draws at a time, deleted once run (12,000-s draws are ~150 MB)
        sub = argparse.Namespace(**{**vars(args), "seeds": ",".join(str(s) for s in seeds[i:i + chunk])})
        files = _gen_files(sub, params)
        part = run_bots(files, bots, args.jobs, args.dir / "logs")
        for b in bots:
            sim[b] += part[b]
        if not args.keep:
            for f in files:
                f.unlink(missing_ok=True)
        print(f"  {len(sim[bots[0]])}/{len(seeds)} draws ({time.time() - t0:.0f} s)", flush=True)
    real = {}
    if args.real:
        real = {b: v[0] for b, v in run_bots([args.real], bots, args.jobs, args.dir / "logs").items()}
    print(f"{args.tag}: {len(seeds)} draws of {args.seconds:.0f} s, opts {args.opts or '{}'}")
    print(f"  {'bot':4s} {'mean':>10s} {'sd':>9s} {'p5':>10s} {'min':>10s}" + (f" {'real':>10s}" if real else ""))
    for b in sorted(bots, key=lambda b: -np.mean(sim[b])):
        v = np.array(sim[b])
        print(f"  {b:4s} {v.mean():>10,.0f} {v.std(ddof=1) if len(v) > 1 else 0:>9,.0f} {np.percentile(v, 5):>10,.0f} "
              f"{v.min():>10,.0f}" + (f" {real[b]:>10,.0f}" if real else ""))
    print("  pairwise: row beats column on how many draws (mean difference, its se)")
    for a in bots:
        cells = []
        for b in bots:
            if a == b:
                cells.append(f"{'-':>18s}")
                continue
            d = np.array(sim[a]) - np.array(sim[b])
            se = d.std(ddof=1) / np.sqrt(len(d)) if len(d) > 1 else 0.0
            cells.append(f"{int((d > 0).sum()):>3d} {d.mean() / 1000:+7.1f}k ({se / 1000:.1f}k)")
        print(f"  {a:4s} " + " ".join(cells))
    if args.out:
        args.out.write_text(json.dumps({"opts": parse_opts(args.opts), "seeds": seeds, "seconds": args.seconds,
                                        "sim": sim, "real": real}))
    return 0


def cmd_search(args) -> int:
    params = json.loads(args.params.read_text())
    fixed = json.loads(args.fix or "{}")
    only = set(args.only.split(",")) if args.only else None
    seeds = parse_seeds(args.seeds)
    target = load_target(args)
    bots = args.bots.split(",") if args.bots else list(SEARCH_BOTS)
    scale = args.scale if args.scale else 12000.0 / args.seconds
    rng = np.random.default_rng(args.rng)
    args.dir.mkdir(parents=True, exist_ok=True)
    done = 0
    start = 0
    if args.out.exists():
        start = sum(1 for _ in args.out.open())
    jobs = []
    around = parse_opts(args.around) if args.around else None
    vary = set(args.vary.split(",")) if args.vary else None
    for i in range(args.trials):
        opts = {**(perturb(rng, around, args.spread, vary) if around else sample(rng, only)), **fixed}
        jobs.append((start + i, params, opts, seeds, args.seconds, str(args.dir), bots, target, scale))
    if args.include:
        for j, text in enumerate(args.include):
            jobs.insert(j, (start + args.trials + j, params, {**json.loads(text), **fixed}, seeds, args.seconds,
                            str(args.dir), bots, target, scale))
    with ProcessPoolExecutor(args.jobs) as ex, args.out.open("a") as fh:
        for res in ex.map(trial, jobs):
            fh.write(json.dumps(res) + "\n")
            fh.flush()
            done += 1
            if "error" in res:
                print(f"[{done}/{len(jobs)}] trial {res['trial']} error {res['error']}", flush=True)
                continue
            print(f"[{done}/{len(jobs)}] trial {res['trial']} obj {res['objective']:.3f} rho {res['spearman']:.2f} "
                  f"asinh {res['asinh']:.3f} ({res['seconds']:.0f} s) {json.dumps(res['opts'])}", flush=True)
    return show_best(args.out, args.top, target)


def show_best(path: Path, top: int, target: dict, rescore: bool = False) -> int:
    rows = [json.loads(line) for line in path.open() if line.strip()]
    rows = [r for r in rows if "error" not in r]
    if rescore:  # against another target: the public scores are 6,000-s ones, so the scale is the trial's tape length's
        for r in rows:
            r["scale"] = 6000.0 / r["stats"]["seconds"] if target is PUBLIC and "stats" in r else r["scale"]
            r.update({k: v for k, v in compare(r["sim"], target, r["scale"]).items() if k in ("spearman", "asinh", "scale_c", "objective")})
    rows.sort(key=lambda r: r["objective"])
    for r in rows[:top]:
        sim = r["sim"]
        line = " ".join(f"{b} {r['scale'] * np.mean(sim[b]) / 1000:,.0f}k" for b in sorted(sim, key=lambda b: target.get(b, 0)))
        print(f"trial {r['trial']}: obj {r['objective']:.3f} rho {r['spearman']:.2f} asinh {r['asinh']:.3f} "
              f"c {r['scale_c']:.2f}\n   {json.dumps(r['opts'])}\n   {line}")
    return 0


def cmd_best(args) -> int:
    return show_best(args.file, args.top, load_target(args), args.rescore)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="experiments.day.gen_calibrate", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("score", help="the bots on given tapes against the scoreboard")
    sc.add_argument("tapes", nargs="+")
    sc.add_argument("--target", choices=("validation", "public"), default="validation")
    sc.add_argument("--scoreboard", type=Path, help="a JSON {bot: score} instead of round 2's validation scores")
    sc.add_argument("--bots", help="comma-separated (default: every bot the target scores)")
    sc.add_argument("--threads", type=int, default=5)
    sc.add_argument("--scale", type=float, default=1.0, help="multiply the simulated PnL (e.g. 2 for 6,000-s tapes against 12,000-s scores)")
    sc.add_argument("--dir", type=Path, help="where the Python bots' log dirs go")
    sc.add_argument("--out", type=Path)
    dr = sub.add_parser("draw", help="generate draws of a parameter set and score them")
    dr.add_argument("--params", type=Path, required=True)
    dr.add_argument("--opts", help="JSON latent options merged into the params")
    dr.add_argument("--seeds", default="1-3")
    dr.add_argument("--seconds", type=float, default=12000.0)
    dr.add_argument("--dir", type=Path, required=True)
    dr.add_argument("--tag", default="draw")
    dr.add_argument("--jobs", type=int, default=5)
    dr.add_argument("--target", choices=("validation", "public"), default="validation")
    dr.add_argument("--scoreboard", type=Path)
    dr.add_argument("--bots")
    dr.add_argument("--scale", type=float, default=1.0)
    dr.add_argument("--keep", action="store_true", help="keep the generated tapes")
    dr.add_argument("--stats", action="store_true", help="print each draw's price statistics (tape_stats) first")
    dr.add_argument("--stats-only", action="store_true", help="with --stats: no bots")
    dr.add_argument("--out", type=Path)
    fs = sub.add_parser("fitstats", help="a local search (no bots) matching a real tape's price statistics")
    fs.add_argument("--params", type=Path, required=True)
    fs.add_argument("--around", required=True, help="JSON options to search around")
    fs.add_argument("--vary", help="comma-separated keys to perturb (default every numeric one)")
    fs.add_argument("--spread", type=float, default=0.4)
    fs.add_argument("--real", type=Path, required=True)
    fs.add_argument("--trials", type=int, default=40)
    fs.add_argument("--seed", type=int, default=1)
    fs.add_argument("--seconds", type=float, default=6000.0)
    fs.add_argument("--dir", type=Path, required=True)
    fs.add_argument("--jobs", type=int, default=5)
    fs.add_argument("--rng", type=int, default=0)
    fs.add_argument("--out", type=Path, required=True)
    fs.add_argument("--top", type=int, default=5)
    jf = sub.add_parser("jumpflow", help="the aggressive flow around jumps, timed by the latent and by the mid")
    jf.add_argument("tapes", nargs="+")
    rk = sub.add_parser("rank", help="bots ranked on a parameter set's draws (no scoreboard)")
    rk.add_argument("--params", type=Path, required=True)
    rk.add_argument("--opts", help="JSON latent options merged into the params")
    rk.add_argument("--bots", required=True, help="comma-separated, from BOTS")
    rk.add_argument("--seeds", default="1-30")
    rk.add_argument("--seconds", type=float, default=12000.0)
    rk.add_argument("--dir", type=Path, required=True)
    rk.add_argument("--tag", default="rank")
    rk.add_argument("--jobs", type=int, default=5)
    rk.add_argument("--real", type=Path, help="a real tape to run the bots on too")
    rk.add_argument("--extra", action="append", help="NAME=FILE: another Python bot (repeatable)")
    rk.add_argument("--keep", action="store_true")
    rk.add_argument("--out", type=Path)
    se = sub.add_parser("search", help="random search over the generator's v2 options")
    se.add_argument("--params", type=Path, required=True)
    se.add_argument("--trials", type=int, default=40)
    se.add_argument("--seeds", default="1-2")
    se.add_argument("--seconds", type=float, default=6000.0)
    se.add_argument("--scale", type=float, help="multiply the simulated PnL (default 12,000 / seconds)")
    se.add_argument("--dir", type=Path, required=True)
    se.add_argument("--jobs", type=int, default=5)
    se.add_argument("--out", type=Path, required=True)
    se.add_argument("--rng", type=int, default=0)
    se.add_argument("--fix", help="JSON options held fixed in every trial")
    se.add_argument("--only", help="comma-separated PRIOR keys to search (the rest off)")
    se.add_argument("--include", action="append", help="JSON options of a trial to run first (repeatable)")
    se.add_argument("--around", help="JSON options: a local search, each numeric one times exp(U(-spread, spread))")
    se.add_argument("--spread", type=float, default=0.3)
    se.add_argument("--vary", help="with --around: comma-separated keys to perturb (default every numeric one)")
    se.add_argument("--scoreboard", type=Path)
    se.add_argument("--target", choices=("validation", "public"), default="validation",
                    help="public: round 2's public-tape scores (then --seconds 6000 and --scale 1)")
    se.add_argument("--bots", help=f"comma-separated (default {','.join(SEARCH_BOTS)})")
    se.add_argument("--top", type=int, default=8)
    st = sub.add_parser("stats", help="the price statistics of tapes (the sd over 1-300 s, changes, spreads, impact)")
    st.add_argument("tapes", nargs="+")
    st.add_argument("--jobs", type=int, default=5)
    be = sub.add_parser("best", help="rank a search's trials")
    be.add_argument("file", type=Path)
    be.add_argument("--top", type=int, default=10)
    be.add_argument("--scoreboard", type=Path)
    be.add_argument("--target", choices=("validation", "public"), default="validation")
    be.add_argument("--rescore", action="store_true", help="recompute each trial's measures against this target")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(line_buffering=True)
    return {"score": cmd_score, "draw": cmd_draw, "search": cmd_search, "best": cmd_best, "stats": cmd_stats,
            "rank": cmd_rank, "fitstats": cmd_fitstats, "jumpflow": cmd_jumpflow}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
