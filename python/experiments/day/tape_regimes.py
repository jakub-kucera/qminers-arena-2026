"""Which round-1 strategy survives which change of tape: tape_gen's fitted model, altered one regime at a time (7 Nov, before round 2).

Fits (or loads) tape_gen's params, draws SEEDS tapes of each regime below (the baseline, then one change each to the
fitted params), runs R1-C1, R1-C5 and its variants, never-learning controls and R1-F8 on each in the Rust simulator,
and prints regime x strategy mean PnL (net of the breach penalty, as the simulator reports it) and mean penalty, plus
the real tape's row with --real. Tapes are deleted once run unless --keep.

    uv run python -m experiments.day.tape_regimes --fit data/arena/round1/round1.csv --dir DIR --seeds 1-3 --threads 4 [--real data/arena/round1/round1.csv]
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from arena import qsim_rust
from experiments.day import tape_gen

C5 = {"POSITION_LIMIT": 1000, "EXPOSURE": 100, "CANCEL_FREE": 1.0, "HEDGE": 1, "MODEL_MEMORY_US": 100_000_000_000,
      "HORIZON_US": 400_000, "DEAD_ZONE": 0.18}
NEVER = {"MIN_LABELS": 1_000_000_000}
# name -> (Rust strategy, overrides)
STRATS = {
    "C1": ("ridge_maker", {}),
    "C1_nolearn": ("ridge_maker", dict(NEVER)),
    "C5": ("ridge_maker", dict(C5)),
    "C5_dz10": ("ridge_maker", {**C5, "DEAD_ZONE": 0.1}),
    "C5_dz25": ("ridge_maker", {**C5, "DEAD_ZONE": 0.25}),
    "C5_h100k": ("ridge_maker", {**C5, "HORIZON_US": 100_000}),
    "C5_nohedge": ("ridge_maker", {**C5, "HEDGE": 0, "EXPOSURE": 100, "CANCEL_FREE": 0.0}),
    "C5_nolearn": ("ridge_maker", {**C5, **NEVER}),
    "F8": ("take_maker", {}),
}


def scale_values(table, factor):
    return [[max(1, int(round(v * factor))), c] for v, c in table]


def regimes(base: dict) -> dict:
    """Each regime: the fitted params with one change."""
    out = {"base": copy.deepcopy(base)}

    def alt(name, fn):
        p = copy.deepcopy(base)
        fn(p)
        out[name] = p

    alt("wide2", lambda p: p["latent"].update(spread2=True))  # a 2-tick book around the latent mid

    def touch(f):
        def fn(p):
            for c in ("inside", "touch"):
                p["sizes"][c] = scale_values(p["sizes"][c], f)
        return fn
    alt("thin_touch", touch(0.25))
    alt("deep_touch", touch(4.0))
    alt("f_rate_x2", lambda p: p.update(f_rate=2 * p["f_rate"]))

    def sweep(p):  # aggressors 4x the lots, limits 2 ticks further through; impact per order kept (bins scaled too)
        p["f_sizes"] = scale_values(p["f_sizes"], 4.0)
        p["f_offsets"] = [[o + 2, c] for o, c in p["f_offsets"]]
        p["latent"]["impact"] = [[e * 4 if e < 10**9 else e, v] for e, v in p["latent"]["impact"]]
    alt("sweep", sweep)

    def trend(p):
        p["latent"]["impact"] = [[e, min(1.0, 2 * v)] for e, v in p["latent"]["impact"]]
        p["latent"]["f_buy_share"] = 0.52
    alt("trend", trend)
    alt("weak_impact", lambda p: p["latent"].update(impact=[[e, 0.2 * v] for e, v in p["latent"]["impact"]]))
    alt("informed", lambda p: p["latent"].update(informed=0.5))
    return out


def _gen(args):
    params, seed, out = args
    if not out.exists():
        tape_gen.generate(params, seed, params["duration_s"], out)
    return str(out)


def run_all(files: list[Path], threads: int) -> dict:
    """name -> list over files of (pnl, penalty)."""
    res = {}
    by_strategy = {}
    for name, (strategy, over) in STRATS.items():
        by_strategy.setdefault(strategy, []).append((name, over))
    for strategy, items in by_strategy.items():
        rows = qsim_rust.run_batch(strategy, [over for _, over in items], files, threads)
        for (name, _), per_file in zip(items, rows):
            res[name] = [(r.get("pnl", float("nan")), r.get("breach_penalty", float("nan"))) for r in per_file]
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="experiments.day.tape_regimes", description=__doc__.split("\n")[0])
    ap.add_argument("--fit", type=Path)
    ap.add_argument("--params", type=Path)
    ap.add_argument("--dir", type=Path, required=True)
    ap.add_argument("--seeds", default="1-3")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--real", type=Path)
    ap.add_argument("--only", help="comma-separated regimes")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args(argv)
    args.dir.mkdir(parents=True, exist_ok=True)
    if args.params:
        base = json.loads(args.params.read_text())
    else:
        base = tape_gen.fit(args.fit)
        (args.dir / "params.json").write_text(json.dumps(base))
    lo, _, hi = args.seeds.partition("-")
    seeds = list(range(int(lo), int(hi or lo) + 1))
    table = {}
    if args.real:
        table["REAL"] = run_all([args.real], args.threads)
    regs = regimes(base)
    if args.only:
        regs = {k: v for k, v in regs.items() if k in args.only.split(",")}
    for name, params in regs.items():
        files = [args.dir / f"{name}_{s}.csv" for s in seeds]
        with ProcessPoolExecutor(min(args.threads, len(files))) as ex:
            list(ex.map(_gen, [(params, s, f) for s, f in zip(seeds, files)]))
        table[name] = run_all(files, args.threads)
        if not args.keep:
            for f in files:
                f.unlink()
        line = "  ".join(f"{k} {np.mean([p for p, _ in v]):,.0f}" for k, v in table[name].items())
        print(f"{name}: {line}", flush=True)
    (args.dir / "results.json").write_text(json.dumps(table))
    names = list(STRATS)
    print("\nmean PnL (net of penalty) [mean penalty if > 0]; n =", len(seeds), "seeds")
    print(f"{'regime':12s}" + "".join(f"{n:>13s}" for n in names))
    for reg, res in table.items():
        cells = []
        for n in names:
            pnl = np.mean([p for p, _ in res[n]])
            pen = np.mean([q for _, q in res[n]])
            cells.append(f"{pnl/1000:,.1f}k" + (f"[{pen/1000:.0f}k]" if pen > 0 else ""))
        print(f"{reg:12s}" + "".join(f"{c:>13s}" for c in cells))
    return 0


if __name__ == "__main__":
    sys.exit(main())
