"""A pretrained non-linear forecast of the bots' label (the mid's move 400 ms ahead), trained offline on many tapes and
embedded in the bot file (8 Nov, round 3; IDEAS.md, "A pretrained forecaster of the 400-ms move").

The online ridge of R2-L8 / R2-L9 / R3-F1 is refitted every second on the tape so far. This script asks whether a
frozen model fitted on other tapes (real ones and tape_gen v2 draws) does better, alone or as an extra feature of
that ridge (stacking: the ridge re-weights it per tape).

Subcommands:

- `gen --params P.json --opts PRESET --seeds 1-12 --seconds 3000 --dir DIR`: tape_gen draws (gen_calibrate's presets).
- `dump TAPE... --dir DIR --jobs 3 [--head-seconds 3000 --tag-parent]`: each tape (or its first seconds) through the starter's simulator with `pretrain_dump_bot.py` (R3-F1 plus
  a dump of every observation's features and matured label) to DIR/<stem>.bin; the PnL line to DIR/<stem>.pnl.
- `rdump TAPE... --dir DIR --jobs 3 [--head-seconds S --tag-parent]`: the same rows from the Rust ridge_maker with
  R3-F1's settings (`RIDGE_FEAT_LOG`, ridge_maker.rs), about 10 s a 6,000-s tape instead of 200-400 s.
- `run BOT... --tapes TAPE... --dir DIR [--split 4500] --jobs 3`: the bots on the tapes through the starter's
  simulator, the PnL before and after --split and the run's seconds (the candidates' backtests).
- `baseline TAPE... [--split 4500]`: R3-F1, F2 and F3 by the Rust twin, the PnL before and after --split.
- `table --dir DIR --gen GLOB`: the offline comparison. For each test tape (round 3's last 25%, t >= 4,500 s; round
  2's public tape; round 1) and each training source (real tapes only, generated only, both; the test tape and its
  mirror never in training, round 3 only before 4,500 s): out-of-sample R^2 and the take region (|forecast| > 0.65
  ticks at a 1-tick spread: share, hit rate, mean move the forecast's way) for a frozen ridge, a frozen MLP and
  HistGradientBoosting, against the online ridge as the bot ran it (its stored forecast) and an offline replay of it
  with the frozen MLP's forecast as a 40th feature (stacked).
- `rescale --dir DIR --gen GLOB [--hgb]`: models trained on generated dumps only, scored on round 3's last 25%:
  (a) as fitted, (b) rescaled by one linear fit on round3_public before 4,500 s, (c) (b) stacked under the online ridge.
- `export --dir DIR --gen GLOB --out W.json`: the MLP fitted on every training tape (round 3 only before 4,500 s),
  its weights as JSON lists; `embed --weights W.json --bot FILE` writes them into the candidate's PRE_BLOB block
  (`python/bots/qminers/candidates/r3_P1_pretrained_mlp.py`).

    uv run python -m experiments.day.tape_gen --fit data/arena/round3/round3_public.csv --params-out P3.json
    uv run python -m experiments.day.pretrain_forecast gen --params P3.json --opts r3_public_stats --seeds 1-12 --dir G
    uv run python -m experiments.day.pretrain_forecast dump data/arena/round3/round3_public.csv G/*.csv --dir DUMP
    uv run python -m experiments.day.pretrain_forecast table --dir DUMP
    uv run python -m experiments.day.pretrain_forecast export --dir DUMP --out W.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
DUMP_BOT = Path(__file__).resolve().parent / "pretrain_dump_bot.py"
NF = 39       # R3-F1's ridge features
NX = 14       # the dump bot's extras
HEAD = 5      # t, mid, response, stored forecast, inventory
ROW = HEAD + NF + NX
R3_SPLIT = 4500.0   # round 3's held-out last 25% starts here


def set_nf(n: int) -> None:
    """The dumps' feature count: 39 (R3-F1's ridge, the default) or 36 (R3-F2's, `rdump --settings F2`)."""
    global NF, ROW
    NF = n
    ROW = HEAD + NF + NX


# ---------------------------------------------------------------- tapes and dumps
def _gen(job):
    from experiments.day import gen_calibrate, tape_gen
    params_path, opts, seed, seconds, out = job
    if Path(out).exists():
        return out
    params = gen_calibrate.with_opts(json.loads(Path(params_path).read_text()), gen_calibrate.parse_opts(opts))
    tape_gen.generate(params, seed, seconds, Path(out))
    return out


def cmd_gen(args) -> int:
    from experiments.day import gen_calibrate
    args.dir.mkdir(parents=True, exist_ok=True)
    seeds = gen_calibrate.parse_seeds(args.seeds)
    tag = args.tag or (args.opts if args.opts and not args.opts.startswith("{") else "gen")
    jobs = [(str(args.params), args.opts, s, args.seconds, str(args.dir / f"{tag}_{s}.csv")) for s in seeds]
    with ProcessPoolExecutor(args.jobs) as ex:
        for out in ex.map(_gen, jobs):
            print(out, flush=True)
    return 0


def _dump(job):
    tape, out_dir, bot = job
    stem = Path(tape).stem
    out = Path(out_dir) / f"{stem}.bin"
    env = dict(os.environ, PRETRAIN_DUMP=str(out))
    if bot:
        env["PRETRAIN_BASE"] = str(bot)
    t0 = time.time()
    res = subprocess.run([sys.executable, "-m", "simulator.main", "--strategy", str(DUMP_BOT), "--backtest", str(tape),
                          "--log-dir", str(Path(out_dir) / "logs" / stem), "--no-logs"],
                         capture_output=True, text=True, cwd=ROOT, env=env)
    m = re.search(r"^pnl=(-?[0-9.]+)", res.stdout, re.M)
    pnl = float(m.group(1)) if m else float("nan")
    (Path(out_dir) / f"{stem}.pnl").write_text(f"{pnl} {time.time() - t0:.0f}\n")
    return stem, pnl, time.time() - t0, res.returncode


def head_copy(tape: Path, seconds: float, out_dir: Path, tag: str = "") -> Path:
    """The tape's rows up to `seconds` (a time-sorted CSV), as out_dir/<tag><stem>_<seconds>s.csv."""
    out = out_dir / f"{tag}{tape.stem}_{seconds:.0f}s.csv"
    if out.exists():
        return out
    with open(tape) as src, open(out, "w") as dst:
        dst.write(src.readline())
        for line in src:
            if float(line[:line.index(",")]) > seconds:
                break
            dst.write(line)
    return out


def cmd_dump(args) -> int:
    args.dir.mkdir(parents=True, exist_ok=True)
    tapes = [Path(t) for t in args.tapes]
    if args.head_seconds:
        (args.dir / "tapes").mkdir(exist_ok=True)
        tapes = [head_copy(t, args.head_seconds, args.dir / "tapes", f"{t.parent.name}_" if args.tag_parent else "")
                 for t in tapes]
    jobs = [(str(t), str(args.dir), args.bot) for t in tapes]
    with ProcessPoolExecutor(args.jobs) as ex:
        for stem, pnl, sec, rc in ex.map(_dump, jobs):
            print(f"{stem}: pnl {pnl:,.0f}, {sec:.0f} s, rc {rc}", flush=True)
    return 0


def _rdump(job):
    """One tape through the Rust ridge_maker with R3-F1's settings and RIDGE_FEAT_LOG (the same rows as `dump`)."""
    from arena import qsim_rust
    from experiments.day import gen_calibrate
    tape, out_dir, stem, stride, settings = job
    out = Path(out_dir) / f"{stem}.bin"
    t0 = time.time()
    base = {"F1": gen_calibrate.L9, "F2": gen_calibrate.L8}[settings]
    with open(Path(out_dir) / f"{stem}.task.jsonl", "w") as f:
        f.write(json.dumps({**base, "FILTER": 1}) + "\n")
    res = subprocess.run([str(qsim_rust.BINARY), "batch", "--strategy", "ridge_maker", "--tasks",
                          str(Path(out_dir) / f"{stem}.task.jsonl"), "--threads", "1", "--public-depth", "20",
                          "--backtest", str(tape)], capture_output=True, text=True,
                         env=dict(os.environ, RIDGE_FEAT_LOG=str(out)))
    try:
        pnl = json.loads(res.stdout.splitlines()[0])["pnl"]
    except (IndexError, KeyError, ValueError):
        pnl = float("nan")
    if stride > 1 and out.exists():
        set_nf(36 if settings == "F2" else 39)
        load(out)[::stride].tofile(out)
    (Path(out_dir) / f"{stem}.pnl").write_text(f"{pnl} {time.time() - t0:.0f} rust\n")
    return stem, pnl, time.time() - t0, res.returncode


def cmd_rdump(args) -> int:
    from arena import qsim_rust
    qsim_rust.build()
    args.dir.mkdir(parents=True, exist_ok=True)
    tapes = [Path(t) for t in args.tapes]
    if args.head_seconds:
        (args.dir / "tapes").mkdir(exist_ok=True)
        tapes = [head_copy(t, args.head_seconds, args.dir / "tapes", f"{t.parent.name}_" if args.tag_parent else "")
                 for t in tapes]
    stems = [f"{t.parent.name}_{t.stem}" if args.tag_parent and not args.head_seconds else t.stem for t in tapes]
    jobs = [(str(t), str(args.dir), st, args.stride, args.settings) for t, st in zip(tapes, stems)
            if not (args.dir / f"{st}.pnl").exists()]
    with ProcessPoolExecutor(args.jobs) as ex:
        for stem, pnl, sec, rc in ex.map(_rdump, jobs):
            print(f"{stem}: pnl {pnl:,.0f}, {sec:.0f} s, rc {rc}", flush=True)
    return 0


def _run(job):
    """One bot on one tape through the starter's simulator: PnL, PnL at --split s, run seconds."""
    bot, tape, logdir, split = job
    t0 = time.time()
    res = subprocess.run([sys.executable, "-m", "simulator.main", "--strategy", str(bot), "--backtest", str(tape),
                          "--log-dir", str(logdir), "--no-logs"], capture_output=True, text=True, cwd=ROOT)
    sec = time.time() - t0
    m = re.search(r"^pnl=(-?[0-9.]+)", res.stdout, re.M)
    pnl = float(m.group(1)) if m else float("nan")
    at = float("nan")
    curve = Path(logdir) / "pnl.csv"
    if curve.exists():
        rows = [line.split(",") for line in curve.read_text().splitlines()[1:]]
        before = [float(p) for t, p in rows if float(t) <= split]
        at = before[-1] if before else float("nan")
    err = "" if m else (res.stderr.strip().splitlines() or ["?"])[-1][:200]
    return Path(bot).stem, Path(tape).stem, pnl, at, sec, err


def cmd_run(args) -> int:
    jobs = [(b, t, args.dir / f"{Path(b).stem}__{Path(t).stem}", args.split) for t in args.tapes for b in args.bots]
    with ProcessPoolExecutor(args.jobs) as ex:
        for bot, tape, pnl, at, sec, err in ex.map(_run, jobs):
            print(f"{bot} | {tape} | pnl {pnl:,.0f} | to {args.split:.0f} s {at:,.0f} | after {pnl - at:,.0f} | {sec:.0f} s {err}",
                  flush=True)
    return 0


def cmd_baseline(args) -> int:
    """R3-F1, R3-F2 and R3-F3 by the Rust twin (each reproducing its file to the unit): PnL before / after --split."""
    from arena import qsim_rust
    from experiments.day import gen_calibrate
    qsim_rust.build()
    bots = {"F1": {**gen_calibrate.L9, "FILTER": 1}, "F2": {**gen_calibrate.L8, "FILTER": 1},
            "F3": {**gen_calibrate.B1, "FILTER": 1}}
    tapes = [Path(t) for t in args.tapes]
    runs = qsim_rust.run_batch("ridge_maker", list(bots.values()), tapes, threads=args.jobs)
    for name, row in zip(bots, runs):
        for tape, r in zip(tapes, row):
            before = [p for ts, p in r["curve"] if ts <= args.split * 1e6]
            at = before[-1] if before else 0.0
            print(f"{name} | {tape.stem} | pnl {r['pnl']:,.0f} | to {args.split:.0f} s {at:,.0f} | after {r['pnl'] - at:,.0f}")
    return 0


def load(path: Path) -> np.ndarray:
    a = np.fromfile(path, dtype=np.float64)
    return a[: len(a) // ROW * ROW].reshape(-1, ROW)


# ---------------------------------------------------------------- models
def r2(y, p) -> float:
    return 1.0 - float(np.sum((y - p) ** 2) / np.sum((y - y.mean()) ** 2))


def take_stats(y, p, spread, th=0.65):
    m = (np.abs(p) > th) & (spread <= 1)
    if not m.any():
        return 0.0, float("nan"), float("nan")
    s = np.sign(p[m])
    mv = s * y[m]
    nz = mv != 0
    return float(m.mean()), float((mv[nz] > 0).mean()) if nz.any() else float("nan"), float(mv.mean())


class Scaler:
    def __init__(self, X):
        self.mu = X.mean(0)
        self.sd = X.std(0) + 1e-6

    def __call__(self, X):
        return (X - self.mu) / self.sd


def fit_ridge(X, y, lam=30.0):
    Xa = np.hstack([X, np.ones((len(X), 1))])
    A = Xa.T @ Xa + lam * np.eye(Xa.shape[1])
    A[-1, -1] -= lam
    w = np.linalg.solve(A, Xa.T @ y)
    return lambda Z: np.hstack([Z, np.ones((len(Z), 1))]) @ w


def huber_w(res, delta=6.0):
    a = np.abs(res)
    return np.minimum(1.0, delta / np.maximum(a, 1e-12))


def fit_mlp(X, y, hidden=(32, 16), epochs=6, lr=2e-3, batch=2048, seed=0, l2=1e-5, delta=3.0, log=None):
    """A tanh MLP on standardised inputs, Adam, Huber loss (delta in ticks); returns (predict, weights)."""
    rng = np.random.default_rng(seed)
    sc = Scaler(X)
    Xs = sc(X).astype(np.float32)
    y = y.astype(np.float32)
    sizes = [X.shape[1], *hidden, 1]
    W = [rng.normal(0, 1 / np.sqrt(a), (a, b)).astype(np.float32) for a, b in zip(sizes[:-1], sizes[1:])]
    B = [np.zeros(b, np.float32) for b in sizes[1:]]
    params = W + B
    m = [np.zeros_like(p) for p in params]
    v = [np.zeros_like(p) for p in params]
    t = 0
    n = len(Xs)
    for ep in range(epochs):
        idx = rng.permutation(n)
        lr_ep = lr * (0.5 ** max(0, ep - epochs // 2))
        for s in range(0, n - batch + 1, batch):
            bi = idx[s:s + batch]
            h = [Xs[bi]]
            for i in range(len(W) - 1):
                h.append(np.tanh(h[-1] @ W[i] + B[i]))
            out = (h[-1] @ W[-1] + B[-1])[:, 0]
            err = out - y[bi]
            g = np.clip(err, -delta, delta)[:, None] / len(bi)
            gW = [None] * len(W)
            gB = [None] * len(W)
            for i in range(len(W) - 1, -1, -1):
                gW[i] = h[i].T @ g + l2 * W[i]
                gB[i] = g.sum(0)
                if i:
                    g = (g @ W[i].T) * (1 - h[i] ** 2)
            grads = gW + gB
            t += 1
            for k, (p, gr) in enumerate(zip(params, grads)):
                m[k] = 0.9 * m[k] + 0.1 * gr
                v[k] = 0.999 * v[k] + 0.001 * gr * gr
                p -= lr_ep * (m[k] / (1 - 0.9 ** t)) / (np.sqrt(v[k] / (1 - 0.999 ** t)) + 1e-8)
        if log:
            log(f"  mlp epoch {ep + 1}/{epochs}")
    W = [w.astype(np.float64) for w in W]
    B = [b.astype(np.float64) for b in B]

    def predict(Z):
        h = sc(Z)
        for i in range(len(W) - 1):
            h = np.tanh(h @ W[i] + B[i])
        return (h @ W[-1] + B[-1])[:, 0]

    return predict, {"mu": sc.mu.tolist(), "sd": sc.sd.tolist(), "W": [w.tolist() for w in W], "B": [b.tolist() for b in B]}


def fit_hgb(X, y, seed=0):
    from sklearn.ensemble import HistGradientBoostingRegressor
    m = HistGradientBoostingRegressor(loss="squared_error", max_iter=300, learning_rate=0.08, max_leaf_nodes=31,
                                      min_samples_leaf=200, l2_regularization=1.0, random_state=seed)
    m.fit(X, y)
    return m.predict


def online_ridge(X, y, t, horizon=0.4, refit=1.0, min_labels=200, delta=6.0, frac=0.003, lam=30.0):
    """An offline replay of the bots' online ridge (no intercept, Huber weights from the forecast at observation time,
    ridge max(30, 0.003 mass), a refit at most every second on the labels matured by then); returns its forecasts."""
    n, k = X.shape
    xx = np.zeros((k, k))
    xy = np.zeros(k)
    w = np.zeros(k)
    mass = 0.0
    labels = 0
    pred = np.zeros(n)
    j = 0   # next label to add
    i = 0
    last_fit = -1e18
    while i < n:
        # the block of observations until the next refit
        e = np.searchsorted(t, t[i] + refit, side="left") if labels >= min_labels else min(n, i + 50)
        e = max(e, i + 1)
        pred[i:e] = np.clip(X[i:e] @ w, -2, 2)
        i = e
        now = t[i - 1] if i == n else t[i]
        jj = np.searchsorted(t, now - horizon, side="right")
        if jj > j:
            Xb, yb = X[j:jj], y[j:jj]
            wt = huber_w(yb - pred[j:jj], delta)
            xx += (Xb * wt[:, None]).T @ Xb
            xy += (Xb * wt[:, None]).T @ yb
            mass += wt.sum()
            labels += jj - j
            j = jj
        if labels >= min_labels and now - last_fit >= refit:
            last_fit = now
            A = xx + max(lam, frac * mass) * np.eye(k)
            try:
                w = np.linalg.solve(A, xy)
            except np.linalg.LinAlgError:
                pass
    return pred


# ---------------------------------------------------------------- the comparison
REAL = {  # stem: (group, the rows it may train on)
    "round3_public": "r3", "round2_public": "r2", "round2_public_mirror": "r2", "round1": "r1",
    "private_reconstructed": "r1",
}


def split_xy(a, feats):
    X = a[:, HEAD:HEAD + NF] if feats == "f1" else a[:, HEAD:]
    return X, a[:, 2], a[:, HEAD + NF] if a.shape[1] > HEAD + NF else None


def gather(dumps: dict, stems, sub=2):
    parts = []
    for s in stems:
        a = dumps[s]
        if s == "round3_public":
            a = a[a[:, 0] < R3_SPLIT]
        parts.append(a[::sub])
    return np.vstack(parts) if parts else np.zeros((0, ROW))


def load_dumps(d: Path, gen_glob: str):
    dumps = {}
    for p in sorted(d.glob("*.bin")):
        done = p.with_suffix(".pnl")
        if not done.exists() or done.read_text().startswith("nan"):
            continue  # still running, or failed
        dumps[p.stem] = load(p)
    gen = [s for s in dumps if Path(s).match(gen_glob) and s not in REAL]
    return dumps, gen


def cmd_table(args) -> int:
    set_nf(args.nf)
    dumps, gen = load_dumps(args.dir, args.gen)
    if args.only:
        dumps = {k: v for k, v in dumps.items() if k in args.only.split(",") or k in gen}
    real = [s for s in dumps if s in REAL]
    print(f"dumps: real {real}, generated {len(gen)} ({sum(len(dumps[g]) for g in gen):,} rows)", flush=True)
    tests = [("r3 last 25%", "round3_public"), ("r2 public", "round2_public"), ("r1", "round1")]
    if args.tests:
        tests = [x for x in tests if x[1] in args.tests.split(",")]
    rows = []
    for label, stem in tests:
        if stem not in dumps:
            continue
        a = dumps[stem]
        test = a[a[:, 0] >= R3_SPLIT] if stem == "round3_public" else a
        group = REAL[stem]
        real_train = [s for s in real if REAL[s] != group or (stem == "round3_public" and s == stem)]
        if stem == "round1":
            real_train = [s for s in real if s != "round1"]
        sources = {"real": real_train, "gen": gen, "both": real_train + gen}
        sources = {k: v for k, v in sources.items() if k in args.sources.split(",") and (k != "both" or gen)}
        y = test[:, 2]
        tt = test[:, 0]
        early = tt < tt[0] + 600.0

        def row(src, name, p):
            sh, hit, mv = take_stats(y, p, spread)
            rows.append((label, src, name, r2(y, p), sh, hit, mv, r2(y[early], p[early]), r2(y[~early], p[~early])))
            print(rows[-1], flush=True)

        spread = test[:, HEAD + NF]
        stored = test[:, 3]
        base = {"online ridge (as run)": stored}
        # the online ridge replayed offline on the whole tape (for round 3 its last 25% only scored)
        Xall = a[:, HEAD:HEAD + NF]
        on = online_ridge(Xall, a[:, 2], a[:, 0])
        on_t = on[a[:, 0] >= R3_SPLIT] if stem == "round3_public" else on
        base["online ridge (replay)"] = on_t
        for name, p in base.items():
            row("-", name, p)
        for src, stems in sources.items():
            if not stems:
                continue
            tr = gather(dumps, stems, sub=args.sub)
            for feats in ("f1", "all"):
                Xtr, ytr, _ = split_xy(tr, feats)
                Xte, _, _ = split_xy(test, feats)
                models = {"ridge": lambda: fit_ridge(Xtr, ytr)}
                models["mlp"] = lambda: fit_mlp(Xtr, ytr, epochs=args.epochs)[0]
                if args.hgb and feats == "all":
                    models["hgb"] = lambda: fit_hgb(Xtr, ytr)
                for mname, fit in models.items():
                    t0 = time.time()
                    f = fit()
                    p = f(Xte)
                    row(src, f"{mname}/{feats}", p)
                    print(f"  {time.time() - t0:.0f}s", flush=True)
                    if mname == "mlp":
                        # stacked: the online ridge replayed with the frozen forecast as a 40th feature
                        fa = f(split_xy(a, feats)[0])
                        st = online_ridge(np.hstack([Xall, fa[:, None]]), a[:, 2], a[:, 0])
                        st_t = st[a[:, 0] >= R3_SPLIT] if stem == "round3_public" else st
                        row(src, f"stack ridge+mlp/{feats}", st_t)
                        row(src, f"blend 0.5 ridge+mlp/{feats}", 0.5 * on_t + 0.5 * np.clip(p, -2, 2))
    print("\n| test | train | model | R^2 | take share | hit | mean move | R^2 first 600 s | R^2 after |")
    print("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]:.4f} | {r[4]:.4f} | {r[5]:.3f} | {r[6]:.3f} | {r[7]:.4f} | {r[8]:.4f} |")
    if args.out:
        args.out.write_text(json.dumps(rows))
    return 0


def cmd_rescale(args) -> int:
    """Generated-only training, scored on round 3's last 25% (t >= 4,500 s, never trained on): (a) the frozen model
    as fitted; (b) its output rescaled by one linear fit (slope, intercept) on round3_public before 4,500 s, the shape
    learnt from the draws and the scale from the real tape; (c) (b) as the online ridge's 40th feature (the offline
    replay, stacked). The draws' own label sd and online-ridge R^2 against the real tape's, first."""
    set_nf(args.nf)
    dumps, gen = load_dumps(args.dir, args.gen)
    a = dumps["round3_public"]
    t, y_all = a[:, 0], a[:, 2]
    early, te = t < R3_SPLIT, t >= R3_SPLIT
    y, spread = y_all[te], a[te, HEAD + NF]
    print(f"generated {len(gen)} ({sum(len(dumps[g]) for g in gen):,} rows): {gen}", flush=True)
    for s in ["round3_public", *gen]:
        d = dumps[s]
        print(f"  {s}: label sd {d[:, 2].std():.3f}, |label| mean {np.abs(d[:, 2]).mean():.3f}, "
              f"online ridge as run R^2 {r2(d[:, 2], d[:, 3]):.4f}, forecast sd {d[:, 3].std():.3f}", flush=True)
    base_edge = None
    rows = []

    def row(name, p, note=""):
        nonlocal base_edge
        sh, hit, mv = take_stats(y, p, spread)
        edge = sh * (mv - 0.5)
        base_edge = edge if base_edge is None else base_edge
        rows.append((name, r2(y, p), sh, hit, mv, edge, edge / base_edge - 1.0, note))
        print(rows[-1], flush=True)

    row("online ridge (as run)", a[te, 3])
    Xall = a[:, HEAD:HEAD + NF]
    row("online ridge (replay)", online_ridge(Xall, y_all, t)[te])
    tr = gather(dumps, gen, sub=args.sub)
    for feats in ("f1", "all"):
        Xtr, ytr, _ = split_xy(tr, feats)
        Xa = split_xy(a, feats)[0]
        models = {"ridge": lambda: fit_ridge(Xtr, ytr), "mlp": lambda: fit_mlp(Xtr, ytr, epochs=args.epochs)[0]}
        if args.hgb and feats == "all":
            models["hgb"] = lambda: fit_hgb(Xtr, ytr)
        for mname, fit in models.items():
            t0 = time.time()
            p = fit()(Xa)
            row(f"(a) {mname}/{feats}", p[te])
            slope, icpt = np.polyfit(p[early], y_all[early], 1)
            q = slope * p + icpt
            row(f"(b) {mname}/{feats}", q[te], f"x {slope:.3f} {icpt:+.3f}")
            row(f"(c) stack {mname}/{feats}", online_ridge(np.hstack([Xall, q[:, None]]), y_all, t)[te])
            print(f"  {time.time() - t0:.0f}s", flush=True)
    print("\n| model | R^2 | take share | hit | mean move | edge | edge vs as run | rescale |")
    print("|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r[0]} | {r[1]:.4f} | {r[2]:.4f} | {r[3]:.3f} | {r[4]:.3f} | {r[5]:.4f} | {r[6]:+.1%} | {r[7]} |")
    if args.out:
        args.out.write_text(json.dumps(rows))
    return 0


def cmd_export(args) -> int:
    set_nf(args.nf)
    dumps, gen = load_dumps(args.dir, args.gen)
    stems = [s for s in dumps if s in REAL] + gen
    if args.exclude:
        stems = [s for s in stems if s not in args.exclude.split(",")]
    tr = gather(dumps, stems, sub=args.sub)
    X, y, _ = split_xy(tr, args.feats)
    print(f"training on {len(X):,} rows from {stems}", flush=True)
    predict, wts = fit_mlp(X, y, hidden=tuple(int(h) for h in args.hidden.split(",")), epochs=args.epochs, log=print)
    if args.rescale:
        # (b) of `rescale`: one linear fit of the output on the tape's rows before 4,500 s, folded into the last layer
        a = dumps[args.rescale]
        early = a[:, 0] < R3_SPLIT
        slope, icpt = np.polyfit(predict(split_xy(a[early], args.feats)[0]), a[early, 2], 1)
        wts["W"][-1] = (np.array(wts["W"][-1]) * slope).tolist()
        wts["B"][-1] = (np.array(wts["B"][-1]) * slope + icpt).tolist()
        wts["rescale"] = [float(slope), float(icpt)]
        print(f"rescaled on {args.rescale} before {R3_SPLIT:.0f} s: x {slope:.4f} {icpt:+.4f}")
    wts["feats"] = args.feats
    wts["stems"] = stems
    args.out.write_text(json.dumps(wts))
    print(f"wrote {args.out}")
    return 0


def embed(weights: dict, bot: Path) -> None:
    """Write the MLP's arrays into the bot's PRE_SHAPES / PRE_BLOB block (float32, base64: mu, 1/sd, then W, b per layer)."""
    import base64
    arrays = [np.array(weights["mu"]), 1.0 / np.array(weights["sd"])]
    for w, b in zip(weights["W"], weights["B"]):
        arrays += [np.array(w), np.array(b)]
    shapes = tuple(tuple(a.shape) for a in arrays)
    blob = base64.b64encode(np.concatenate([a.ravel() for a in arrays]).astype(np.float32).tobytes()).decode()
    lines = [f"PRE_SHAPES = {shapes!r}", "PRE_BLOB = ("]
    lines += [f'    "{blob[i:i + 112]}"' for i in range(0, len(blob), 112)]
    lines.append(")")
    text = bot.read_text()
    a = text.index("# BEGIN PRETRAINED WEIGHTS")
    a = text.index("\n", a) + 1
    b = text.index("# END PRETRAINED WEIGHTS")
    bot.write_text(text[:a] + "\n".join(lines) + "\n" + text[b:])


def cmd_embed(args) -> int:
    embed(json.loads(args.weights.read_text()), args.bot)
    print(f"embedded {args.weights} into {args.bot} ({args.bot.stat().st_size:,} bytes)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="experiments.day.pretrain_forecast", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen")
    g.add_argument("--params", type=Path, required=True)
    g.add_argument("--opts")
    g.add_argument("--seeds", default="1-12")
    g.add_argument("--seconds", type=float, default=3000.0)
    g.add_argument("--dir", type=Path, required=True)
    g.add_argument("--tag")
    g.add_argument("--jobs", type=int, default=4)
    d = sub.add_parser("dump")
    d.add_argument("tapes", nargs="+")
    d.add_argument("--dir", type=Path, required=True)
    d.add_argument("--jobs", type=int, default=4)
    d.add_argument("--bot", help="the base bot (default R3-F1)")
    d.add_argument("--head-seconds", type=float, help="dump only each tape's first this many seconds (a cut copy in DIR/tapes)")
    d.add_argument("--tag-parent", action="store_true", help="with --head-seconds: prefix the copy's name with its folder's")
    r = sub.add_parser("rdump", help="dump through the Rust ridge_maker (R3-F1's settings, RIDGE_FEAT_LOG): ~10 s a tape")
    r.add_argument("tapes", nargs="+")
    r.add_argument("--dir", type=Path, required=True)
    r.add_argument("--jobs", type=int, default=3)
    r.add_argument("--head-seconds", type=float)
    r.add_argument("--tag-parent", action="store_true", help="prefix each dump's name with its tape's folder's")
    r.add_argument("--stride", type=int, default=1, help="keep every n-th row (the generated tapes: 12,000 s a tape)")
    r.add_argument("--settings", default="F1", choices=("F1", "F2"),
                   help="the bot whose features are dumped: R3-F1 (R2-L9 + FILTER, 39) or R3-F2 (R2-L8 + FILTER, 36)")
    u = sub.add_parser("run", help="bots on tapes through the starter's simulator: PnL, before / after --split, run time")
    u.add_argument("bots", nargs="+")
    u.add_argument("--tapes", nargs="+", required=True)
    u.add_argument("--dir", type=Path, required=True)
    u.add_argument("--split", type=float, default=R3_SPLIT)
    u.add_argument("--jobs", type=int, default=3)
    bl = sub.add_parser("baseline", help="R3-F1 / F2 / F3 by the Rust twin: PnL before / after --split")
    bl.add_argument("tapes", nargs="+")
    bl.add_argument("--split", type=float, default=R3_SPLIT)
    bl.add_argument("--jobs", type=int, default=1)
    t = sub.add_parser("table")
    t.add_argument("--dir", type=Path, required=True)
    t.add_argument("--gen", default="r*_*", help="the generated dumps' stems (a glob)")
    t.add_argument("--sub", type=int, default=2, help="every n-th training row")
    t.add_argument("--epochs", type=int, default=4)
    t.add_argument("--hgb", action="store_true")
    t.add_argument("--tests", help="comma-separated test stems (default round3_public,round2_public,round1)")
    t.add_argument("--only", help="comma-separated real stems to load (default every dump)")
    t.add_argument("--sources", default="real,gen,both")
    t.add_argument("--out", type=Path)
    t.add_argument("--nf", type=int, default=39, help="the dumps' feature count (36 for `rdump --settings F2`)")
    rs = sub.add_parser("rescale", help="generated-only training on round 3's last 25%: raw, rescaled on its first 75%, stacked")
    rs.add_argument("--dir", type=Path, required=True)
    rs.add_argument("--gen", default="r3b_seed*", help="the generated dumps' stems (a glob)")
    rs.add_argument("--sub", type=int, default=2, help="every n-th training row")
    rs.add_argument("--epochs", type=int, default=4)
    rs.add_argument("--hgb", action="store_true")
    rs.add_argument("--out", type=Path)
    rs.add_argument("--nf", type=int, default=39)
    e = sub.add_parser("export")
    e.add_argument("--dir", type=Path, required=True)
    e.add_argument("--gen", default="r*_*")
    e.add_argument("--exclude")
    e.add_argument("--sub", type=int, default=1)
    e.add_argument("--feats", default="all", choices=("f1", "all"))
    e.add_argument("--hidden", default="32,16")
    e.add_argument("--epochs", type=int, default=6)
    e.add_argument("--out", type=Path, required=True)
    e.add_argument("--nf", type=int, default=39)
    e.add_argument("--rescale", help="a real dump's stem: rescale the output by one linear fit on its rows before 4,500 s")
    m = sub.add_parser("embed")
    m.add_argument("--weights", type=Path, required=True)
    m.add_argument("--bot", type=Path, required=True)
    args = ap.parse_args(argv)
    return {"gen": cmd_gen, "dump": cmd_dump, "table": cmd_table, "export": cmd_export, "embed": cmd_embed,
            "rdump": cmd_rdump, "run": cmd_run, "baseline": cmd_baseline, "rescale": cmd_rescale}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
