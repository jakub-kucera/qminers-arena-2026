"""Which property of a tape turns a round-2 candidate negative: per-segment PnL against each segment's character on a
real tape, and tape_gen draws varied one property at a time (7 Nov, round 2: R2-E2 +47k on public, -41k on validation).

`segments`: replays the tape (tape_book's Book) for the mid on a 1-s grid, and per SECONDS-long segment prints its net
move, range, volatility (sd of the 1-s and 60-s mid changes), trendiness (|net| over the sd of a random walk with the
same 1-s volatility), the 1-tick spread's time share, the big IOC orders' rate (500+ lots) and IOC lots a second,
beside each strategy's PnL over that segment (from the Rust simulator's PnL curve, one run over the whole tape).

`stitch`: 12,000-s tapes made of the real tape's own 1,000-s segments (stitch_plans and cmd_stitch: the tape twice, then
its mirror, every segment rising, a zigzag, played 1.25x / 1.5x faster, IOC lots x2 / x0.5, every other segment a tick
wider, the higher- or lower-volatility half repeated, sped up, ...), each segment's book cancelled at its end and its
prices shifted to start at the last one's mid; the same strategies on each, with the E2 footprint the server reports.

`regimes`: fits tape_gen (or loads --params), applies --jump-rate (the latent's own +-0.5-tick steps a second, beyond
the trades'), --impact-scale, --informed, draws SEEDS tapes of SECONDS per regime, runs the Rust strategies (E2, V2,
FT1) and, with --m2, R2-M2 through the starter's simulator, and prints regime x strategy mean PnL. Round 2's fit fails
its baseline (the makers far too rich, IDEAS.md "Why R2-E2 lost on round 2's validation tape"): prefer `stitch`.

`--binary`: an arena-sim build to run (R2-V2's VOL_* knobs were on another branch when this was written).

    uv run python -m experiments.day.tape_character segments data/arena/round2/round2_public.csv [--seconds 1000]
    uv run python -m experiments.day.tape_character profile TAPE.csv [TAPE2.csv ...]
    uv run python -m experiments.day.tape_character stitch data/arena/round2/round2_public.csv --dir DIR [--only hi_vol] [--m2] [--keep]
    uv run python -m experiments.day.tape_character regimes --fit data/arena/round2/round2_public.csv --dir DIR \
        --seeds 1-3 --seconds 12000 --threads 4 [--jump-rate 2] [--only base,trend480] [--m2]
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from arena import qsim_rust
from experiments.day import tape_gen
from experiments.day.tape_book import Book

ROOT = Path(__file__).resolve().parents[3]
M2_FILE = ROOT / "python/bots/qminers/candidates/r2_M2_flow_trend.py"
E2 = {"POSITION_LIMIT": 1000, "CANCEL_FREE": 1.0, "HEDGE": 1, "MODEL_MEMORY_US": 100_000_000_000, "HORIZON_US": 400_000,
      "QUOTEFEAT": 1, "FLOWGRP": 2, "FLOWGRP_CAP": 20, "FLOWGRP_US": 1_000_000, "FT_SZ": 200, "FT_GAP_MS": 50,
      "SKEW_K": 0.025, "FT_EDGE": 0.25, "QUOTE_SIZE": 200, "EXPOSURE": 30, "DEAD_ZONE": 0.18, "KEEP_LOTS": 20, "KEEP_TH": 0.3}
STRATS = {
    "E2": dict(E2),
    "V2": {**E2, "EXPOSURE": 100, "VOL_REF": 2.5, "VOL_EXP": 2, "VOL_US": 5_000_000, "VOL_MIN": 10, "VOL_MAX": 100, "VOL_NOHEDGE": 1},
    "FT1": {**E2, "EXPOSURE": 100, "DEAD_ZONE": 0.18, "KEEP_LOTS": 0},
}
BIG = 500


def replay(path: Path):
    """The mid and spread on a 1-s grid, and the IOC orders (t, side, lots)."""
    book = Book()
    grid_mid, grid_spread, f_rows = [], [], []
    nxt = 1.0
    changes = 0
    last_mid = None
    with path.open() as fh:
        next(fh)
        for line in fh:
            t, op, oid, side, vol, price, life = line.rstrip("\n").split(",")
            t = float(t)
            while t >= nxt:
                bb, ba = book.best
                if bb is not None and ba is not None:
                    grid_mid.append((bb + ba) / 2)
                    grid_spread.append(ba - bb)
                else:
                    grid_mid.append(grid_mid[-1] if grid_mid else np.nan)
                    grid_spread.append(0)
                nxt += 1.0
            if op == "Insert":
                sd = 0 if side == "B" else 1
                if life == "F":
                    f_rows.append((t, sd, int(vol)))
                book.insert(oid, sd, int(price), int(vol), life == "F")
            else:
                book.cancel(oid)
            bb, ba = book.best
            if bb is not None and ba is not None:
                m = (bb + ba) / 2
                if m != last_mid:
                    changes += 1
                    last_mid = m
    return np.array(grid_mid), np.array(grid_spread), np.array(f_rows), changes


def stats(mid, spread, f, lo, hi):
    m = mid[lo:hi]
    d1 = np.diff(m)
    d60 = m[60::60] - m[:-60:60] if len(m) > 60 else np.array([0.0])
    net = m[-1] - m[0]
    sel = (f[:, 0] >= lo) & (f[:, 0] < hi) if len(f) else np.array([], bool)
    fs = f[sel]
    n = hi - lo
    return {"net": net, "range": m.max() - m.min(), "sd1": d1.std(), "sd60": d60.std(),
            "trend": abs(net) / (d1.std() * np.sqrt(len(d1)) + 1e-9), "var_ratio": (d60.var() / 60) / (d1.var() + 1e-9),
            "one_tick": float((spread[lo:hi] == 1).mean()), "big_per_100s": 100 * float((fs[:, 2] >= BIG).sum()) / n if len(fs) else 0.0,
            "ioc_lots_s": float(fs[:, 2].sum()) / n if len(fs) else 0.0}


def run_rust(files: list[Path], threads: int, names=None) -> dict:
    names = names or list(STRATS)
    rows = qsim_rust.run_batch("ridge_maker", [STRATS[n] for n in names], files, threads)
    return {n: r for n, r in zip(names, rows)}


def curve_at(curve, t_s):
    ts = np.array([c[0] for c in curve]) / 1e6
    pnl = np.array([c[1] for c in curve])
    i = np.searchsorted(ts, t_s, side="right") - 1
    return float(pnl[i]) if i >= 0 else 0.0


def cmd_segments(args) -> int:
    mid, spread, f, changes = replay(args.tape)
    res = run_rust([args.tape], args.threads)
    n = len(mid)
    seg = args.seconds
    print(f"{args.tape}: {n} s, mid changes {changes / n:.2f}/s")
    for name, rows in res.items():
        r = rows[0]
        if "pnl" not in r:
            raise SystemExit(f"{name}: {r.get('error')}")
        print(f"  {name}: pnl {r['pnl']:,.0f} fills {r['fills']:,} volume {r['traded_volume']:,} pnl_se {r['pnl_se']:,.0f} "
              f"lots/fill {r['traded_volume'] / max(1, r['fills']):.1f} |pos| q50 {r['abs_inventory_q50']} q95 {r['abs_inventory_q95']}")
    head = f"{'seg':>9s} {'net':>6s} {'range':>6s} {'sd1':>5s} {'sd60':>6s} {'trend':>6s} {'vr':>5s} {'1tick':>6s} {'big/100s':>8s} {'ioc/s':>6s}"
    print(head + "".join(f"{k:>10s}" for k in res))
    table = []
    for lo in range(0, n, seg):
        hi = min(n, lo + seg)
        if hi - lo < seg // 2:
            break
        s = stats(mid, spread, f, lo, hi)
        pn = {k: curve_at(v[0]["curve"], hi) - curve_at(v[0]["curve"], lo) for k, v in res.items()}
        table.append((s, pn))
        print(f"{lo:>4d}-{hi:<4d} {s['net']:6.0f} {s['range']:6.0f} {s['sd1']:5.2f} {s['sd60']:6.2f} {s['trend']:6.2f} {s['var_ratio']:5.2f} "
              f"{s['one_tick']:6.3f} {s['big_per_100s']:8.2f} {s['ioc_lots_s']:6.0f}" + "".join(f"{pn[k]:10,.0f}" for k in res))
    keys = ["net", "range", "sd1", "sd60", "trend", "var_ratio", "one_tick", "big_per_100s", "ioc_lots_s"]
    print("correlation of each strategy's segment PnL with each property (n = %d)" % len(table))
    for k in res:
        y = np.array([p[k] for _, p in table])
        print(f"  {k:4s}" + "".join(f" {key} {np.corrcoef([s[key] for s, _ in table], y)[0, 1]:+.2f}" for key in keys))
    return 0


def profile(path: Path) -> dict:
    mid, spread, f, changes = replay(path)
    s = stats(mid, spread, f, 0, len(mid))
    s["changes_s"] = changes / len(mid)
    s["seconds"] = len(mid)
    return s


def cmd_profile(args) -> int:
    for p in args.tapes:
        s = profile(p)
        print(f"{p.name}: " + " ".join(f"{k} {v:.3f}" for k, v in s.items()))
    return 0


def mean_impact(p):
    sizes = np.array([v for v, _ in p["f_sizes"]], float)
    w = np.array([c for _, c in p["f_sizes"]], float)
    bins = [r[0] for r in p["latent"]["impact"]]
    probs = np.array([r[1] for r in p["latent"]["impact"]])
    imp = probs[np.clip(np.searchsorted(bins, sizes), 0, len(probs) - 1)]
    return float((imp * w).sum() / w.sum()), float((imp ** 2 * w).sum() / w.sum())


def regimes(base: dict, seconds: float) -> dict:
    out = {"base": copy.deepcopy(base)}

    def alt(name, fn):
        p = copy.deepcopy(base)
        fn(p)
        out[name] = p

    m1, m2 = mean_impact(base)
    lat = base["latent"]
    var_s = base["f_rate"] * m2 + lat["jump_rate"] * lat["jump_size"] ** 2  # the latent's variance a second
    # a sustained drift of +480 ticks over 12,000 s by the IOC flow's buy share: drift = f_rate (2s - 1) m1
    share = 0.5 + (480 / 12000) / (2 * base["f_rate"] * m1)
    alt("trend480", lambda p: p["latent"].update(f_buy_share=share))
    alt("trend960", lambda p: p["latent"].update(f_buy_share=0.5 + 2 * (share - 0.5)))
    # volatility 2x / 0.5x by the latent's own steps (uninformed): add 3x the variance; or the impact scaled (informed)
    alt("vol2_jumps", lambda p: p["latent"].update(jump_rate=p["latent"]["jump_rate"] + 3 * var_s / p["latent"]["jump_size"] ** 2))
    alt("impact2", lambda p: p["latent"].update(impact=[[e, 2 * v] for e, v in p["latent"]["impact"]]))
    alt("impact_half", lambda p: p["latent"].update(impact=[[e, 0.5 * v] for e, v in p["latent"]["impact"]]))
    if lat["jump_rate"] > 0:
        alt("vol_half", lambda p: (p["latent"].update(impact=[[e, 0.5 * v] for e, v in p["latent"]["impact"]],
                                                       jump_rate=0.25 * p["latent"]["jump_rate"])))
        alt("no_jumps", lambda p: p["latent"].update(jump_rate=0.0))

    def big(f):
        def fn(p):
            p["f_sizes"] = [[v, max(1, int(round(c * f))) if v >= 300 else c] for v, c in p["f_sizes"]]
        return fn
    alt("big_x3", big(3.0))
    alt("big_third", big(1 / 3))
    alt("f_rate_x1.3", lambda p: p.update(f_rate=1.3 * p["f_rate"]))
    alt("wide2", lambda p: p["latent"].update(spread2=True))
    alt("cancel_fast", lambda p: p.update(lifetime_quantiles=[0.5 * q for q in p["lifetime_quantiles"]]))
    alt("cancel_slow", lambda p: p.update(lifetime_quantiles=[2 * q for q in p["lifetime_quantiles"]]))
    alt("stale_fast", lambda p: p["latent"].update(stale_s=0.5 * p["latent"]["stale_s"]))
    alt("stale_slow", lambda p: p["latent"].update(stale_s=2 * p["latent"]["stale_s"]))
    return out


def _gen(job):
    params, seed, seconds, out = job
    if not out.exists():
        tape_gen.generate(params, seed, seconds, out)
    return str(out)


def run_m2(path: Path, logdir: Path) -> float:
    out = subprocess.run(["uv", "run", "exchange-simulator", "--strategy", str(M2_FILE), "--backtest", str(path),
                          "--log-dir", str(logdir), "--no-logs"], capture_output=True, text=True, cwd=ROOT)
    text = out.stdout + out.stderr
    m = re.search(r"^pnl=(-?[0-9.]+)", text, re.M)
    return float(m.group(1)) if m else float("nan")


# Stitched tapes: the real tape's own 1,000-s segments re-ordered, mirrored or repeated (each segment's book cleared at
# its end, its prices shifted so it starts at the last one's mid), so a property changes while the flow stays real.
SEG = 1000


def load_rows(path: Path) -> list[list]:
    rows = []
    with path.open() as fh:
        next(fh)
        for line in fh:
            t, op, oid, side, vol, price, life = line.rstrip("\n").split(",")
            rows.append([float(t), op, int(oid), side, int(vol) if vol else 0, int(price) if price else 0, life])
    return rows


def stitch(rows, mid, plan, out: Path, time_scale: float = 1.0, f_scale: float = 1.0) -> None:
    """plan: [(segment index, mirrored[, widen]), ...]; time_scale > 1 plays the tape that much faster; widen 1 puts
    every ask (and every IOC buy's limit) a tick higher in that segment: each spread one tick wider."""
    starts = [0]
    for i, r in enumerate(rows):
        if r[0] >= SEG * len(starts):
            starts.append(i)
    starts.append(len(rows))
    t0, level = 0.0, mid[0]
    with out.open("w") as fh:
        fh.write("Time,Operation,OrderId,Side,Volume,Price,Lifespan\n")
        for k, item in enumerate(plan):
            s, mirror, widen = (tuple(item) + (0,))[:3]
            seg = rows[starts[s]:starts[s + 1]]
            m0, m1 = mid[s * SEG], mid[min(len(mid) - 1, (s + 1) * SEG - 1)]
            if mirror:
                key = int(round(level + m0))  # p -> key - p maps m0 to level
                tr = lambda p: key - p
            else:
                off = int(round(level - m0))
                tr = lambda p: p + off
            base_id = (k + 1) * 10_000_000
            live = set()
            lines = []
            for t, op, oid, side, vol, price, life in seg:
                tt = t0 + (t - s * SEG) / time_scale
                if op == "Insert":
                    sd = ("A" if side == "B" else "B") if mirror else side
                    q = max(1, int(round(vol * f_scale))) if life == "F" else vol
                    if life != "F":
                        live.add(oid)
                    px = tr(price) + (widen if (sd == "A") == (life != "F") else 0)
                    lines.append(f"{tt:.6f},Insert,{base_id + oid},{sd},{q},{px},{life}\n")
                elif oid in live:
                    live.discard(oid)
                    lines.append(f"{tt:.6f},Cancel,{base_id + oid},,,,\n")
            t0 += SEG / time_scale
            end = t0 - 1e-6
            lines.extend(f"{end:.6f},Cancel,{base_id + oid},,,,\n" for oid in sorted(live))
            fh.writelines(lines)
            level = (key - m1) if mirror else (m1 + off)


def stitch_plans(nets: list[float]) -> dict:
    """name -> (plan, time_scale, f_scale): 12,000 s each from the public tape's six segments."""
    n = len(nets)
    order = list(range(n))
    up = [(i, nets[i] < 0) for i in order]  # each segment the way it rises
    return {
        "public_x2": ([(i, False) for i in order] * 2, 1.0, 1.0),
        "pub+mirror": ([(i, False) for i in order] + [(i, True) for i in order], 1.0, 1.0),
        "trend_up": (up * 2, 1.0, 1.0),
        "zigzag": ([(i, (nets[i] > 0) == (j % 2 == 0)) for j, i in enumerate(order)] * 2, 1.0, 1.0),
        "fast1.25": (([(i, False) for i in order] * 3)[:15], 1.25, 1.0),  # 15,000 s of tape in 12,000 s
        "big_x2": ([(i, False) for i in order] * 2, 1.0, 2.0),
        "big_half": ([(i, False) for i in order] * 2, 1.0, 0.5),
        "wide_half": ([(i, False, j % 2) for j, i in enumerate(order)] * 2, 1.0, 1.0),  # every other segment a tick wider
    }


def cmd_stitch(args) -> int:
    args.dir.mkdir(parents=True, exist_ok=True)
    rows = load_rows(args.tape)
    mid, spread, f, _ = replay(args.tape)
    n = int(round(len(mid) / SEG))
    segs = [stats(mid, spread, f, i * SEG, (i + 1) * SEG) for i in range(n)]
    nets = [s["net"] for s in segs]
    sd = [s["sd1"] for s in segs]
    hi = sorted(range(n), key=lambda i: -sd[i])[: n // 2]
    lo = sorted(range(n), key=lambda i: sd[i])[: n // 2]
    plans = stitch_plans(nets)
    plans["hi_vol"] = ([(i, False) for i in sorted(hi)] * 4, 1.0, 1.0)
    plans["lo_vol"] = ([(i, False) for i in sorted(lo)] * 4, 1.0, 1.0)
    plans["hi_vol_up"] = ([(i, nets[i] < 0) for i in sorted(hi)] * 4, 1.0, 1.0)
    for speed in (1.25, 1.5):  # the high-volatility half played faster: more volatility a second, and more flow
        k = int(round(12 * speed))
        plans[f"hi_vol_fast{speed}"] = (([(i, False) for i in sorted(hi)] * 8)[:k], speed, 1.0)
    plans["fast1.5"] = (([(i, False) for i in range(n)] * 3)[:18], 1.5, 1.0)
    plans["hi_vol_big1.5"] = ([(i, False) for i in sorted(hi)] * 4, 1.0, 1.5)
    plans["hi_vol_wide_half"] = ([(i, False, j % 2) for j, i in enumerate(sorted(hi) * 4)], 1.0, 1.0)
    if args.only:
        plans = {k: v for k, v in plans.items() if k in args.only.split(",")}
    names = list(STRATS) + (["M2"] if args.m2 else [])
    table = {}
    for name, (plan, ts, fs) in plans.items():
        path = args.dir / f"{name}.csv"
        if not path.exists():
            stitch(rows, mid, plan, path, ts, fs)
        res = run_rust([path], args.threads)
        row = {k: v[0].get("pnl", float("nan")) for k, v in res.items()}
        e2 = res["E2"][0]
        if args.m2:
            row["M2"] = run_m2(path, args.dir / f"m2_{name}")
        prof = profile(path)
        secs = prof["seconds"]
        row.update(E2_fills_s=e2.get("fills", 0) / secs, E2_lots_s=e2.get("traded_volume", 0) / secs,
                   E2_lots_fill=e2.get("traded_volume", 0) / max(1, e2.get("fills", 1)), E2_se=e2.get("pnl_se") or 0.0, **{f"p_{k}": v for k, v in prof.items()})
        table[name] = row
        print(f"{name:10s} " + " ".join(f"{k} {row[k]:>9,.0f}" for k in names)
              + f" | E2 fills/s {row['E2_fills_s']:.2f} lots/s {row['E2_lots_s']:.0f} lots/fill {row['E2_lots_fill']:.1f} se {row['E2_se']:,.0f}"
              + f" | {secs:.0f} s net {prof['net']:.0f} range {prof['range']:.0f} sd1 {prof['sd1']:.2f} sd60 {prof['sd60']:.1f}"
              + f" 1tick {prof['one_tick']:.2f} big/100s {prof['big_per_100s']:.0f} ioc/s {prof['ioc_lots_s']:.0f}", flush=True)
        if not args.keep:
            path.unlink()
    (args.dir / "stitch_results.json").write_text(json.dumps(table, default=float))
    return 0


def cmd_regimes(args) -> int:
    args.dir.mkdir(parents=True, exist_ok=True)
    base = json.loads(args.params.read_text()) if args.params else tape_gen.fit(args.fit)
    if args.jump_rate is not None:
        base["latent"]["jump_rate"] = args.jump_rate
    if args.impact_scale is not None:  # the fit clips each bin's 5-s move at 1 tick; scale it to the tape's volatility
        base["latent"]["impact"] = [[e, args.impact_scale * v] for e, v in base["latent"]["impact"]]
    if args.informed is not None:
        base["latent"]["informed"] = args.informed
    (args.dir / "params.json").write_text(json.dumps(base))
    lo, _, hi = args.seeds.partition("-")
    seeds = list(range(int(lo), int(hi or lo) + 1))
    regs = regimes(base, args.seconds)
    if args.only:
        regs = {k: v for k, v in regs.items() if k in args.only.split(",")}
    names = list(STRATS) + (["M2"] if args.m2 else [])
    table = {}
    for name, params in regs.items():
        files = [args.dir / f"{name}_{s}.csv" for s in seeds]
        with ProcessPoolExecutor(min(args.threads, len(files))) as ex:
            list(ex.map(_gen, [(params, s, args.seconds, f) for s, f in zip(seeds, files)]))
        res = run_rust(files, args.threads)
        row = {k: [r.get("pnl", float("nan")) for r in v] for k, v in res.items()}
        row["E2_fills_s"] = [r.get("fills", 0) / args.seconds for r in res["E2"]]
        row["E2_vol_s"] = [r.get("traded_volume", 0) / args.seconds for r in res["E2"]]
        if args.m2:
            with ProcessPoolExecutor(min(args.threads, len(files))) as ex:
                row["M2"] = list(ex.map(run_m2, files, [args.dir / f"m2_{f.stem}" for f in files]))
        prof = profile(files[0])
        row["profile"] = prof
        table[name] = row
        if not args.keep:
            for f in files:
                f.unlink()
        print(f"{name}: " + "  ".join(f"{k} {np.mean(row[k]):,.0f}" for k in names)
              + f"  E2 fills/s {np.mean(row['E2_fills_s']):.2f} lots/s {np.mean(row['E2_vol_s']):.0f}"
              + f" | net {prof['net']:.0f} range {prof['range']:.0f} sd1 {prof['sd1']:.2f} sd60 {prof['sd60']:.1f}"
              + f" vr {prof['var_ratio']:.2f} 1tick {prof['one_tick']:.2f} chg/s {prof['changes_s']:.2f}", flush=True)
    (args.dir / "results.json").write_text(json.dumps(table, default=float))
    print(f"\nmean PnL, k (min..max over {len(seeds)} seeds of {args.seconds:.0f} s)")
    print(f"{'regime':13s}" + "".join(f"{n:>22s}" for n in names))
    for reg, row in table.items():
        print(f"{reg:13s}" + "".join(f"{np.mean(row[n])/1000:>9,.1f} ({min(row[n])/1000:,.0f}..{max(row[n])/1000:,.0f})".rjust(22) for n in names))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="experiments.day.tape_character", description=__doc__.split("\n")[0])
    ap.add_argument("--binary", type=Path, help="the arena-sim binary to run (default: this checkout's build)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("segments")
    s.add_argument("tape", type=Path)
    s.add_argument("--seconds", type=int, default=1000)
    s.add_argument("--threads", type=int, default=4)
    p = sub.add_parser("profile")
    p.add_argument("tapes", type=Path, nargs="+")
    r = sub.add_parser("regimes")
    r.add_argument("--fit", type=Path)
    r.add_argument("--params", type=Path)
    r.add_argument("--dir", type=Path, required=True)
    r.add_argument("--seeds", default="1-3")
    r.add_argument("--seconds", type=float, default=12000.0)
    r.add_argument("--threads", type=int, default=4)
    r.add_argument("--jump-rate", type=float)
    r.add_argument("--impact-scale", type=float)
    r.add_argument("--informed", type=float)
    r.add_argument("--only")
    r.add_argument("--m2", action="store_true")
    r.add_argument("--keep", action="store_true")
    t = sub.add_parser("stitch")
    t.add_argument("tape", type=Path)
    t.add_argument("--dir", type=Path, required=True)
    t.add_argument("--threads", type=int, default=4)
    t.add_argument("--only")
    t.add_argument("--m2", action="store_true")
    t.add_argument("--keep", action="store_true")
    args = ap.parse_args(argv)
    if args.binary:  # an arena-sim build with knobs not yet on this branch (R2-V2's VOL_*)
        qsim_rust.BINARY = args.binary
    return {"segments": cmd_segments, "profile": cmd_profile, "regimes": cmd_regimes, "stitch": cmd_stitch}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
