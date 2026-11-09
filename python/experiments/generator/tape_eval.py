"""Our candidates on tapes drawn from tape_gen's fitted generator, against the real tape (7 Nov, round 1).

Generates SEEDS tapes from PARAMS (cached in --dir), runs each candidate on them and on the REAL tape (the Rust
exchange simulator for the maker families: a candidate's knobs are its file's module constants that differ from its
family's; `exchange-simulator --no-logs` for the rest), and prints per candidate the real PnL, the generated mean, sd,
5th percentile and the ratio, then the pairwise win rates over the seeds. `--profile` adds round_start's profile of
the first generated tape. `--grid NAME=V1,V2 ...` instead grids a family around a base candidate over the seeds,
choosing the cell by the mean over the generated seeds only; the chosen cell is then run once on the real tape.

    uv run python -m experiments.generator.tape_eval --params P.json --real data/arena/round1/round1.csv --seeds 1-30
    uv run python -m experiments.generator.tape_eval --params P.json --real D --seeds 1-30 --base F7 --grid DYING_DEEP=0,40,80
"""

from __future__ import annotations

import argparse
import ast
import itertools
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from arena import qsim_rust
from experiments.generator import tape_gen

ROOT = Path(__file__).resolve().parents[3]
CAND = ROOT / "python" / "bots" / "qminers" / "candidates"
FAM = ROOT / "python" / "bots" / "qminers" / "families"
# id -> (candidate file, Rust strategy or None for the Python simulator, extra overrides)
CANDIDATES = {
    "F3": (CAND / "r1_F3_full_room.py", "room_maker", {}),
    "F5": (CAND / "r1_F5_shrink_react.py", "shrink_maker", {}),
    "F6": (CAND / "r1_F6_two_levels.py", "shrink_maker", {}),
    "F7": (CAND / "r1_F7_signal.py", "signal_maker", {}),
    "F1": (CAND / "r0_F1_fallback.py", "fallback_maker", {"SESSION_S": 1_000_000_000}),
    "M2": (CAND / "r0_M2_runner_safe.py", None, {"SESSION_S": 1_000_000_000}),
}


def constants(path: Path) -> dict:
    out = {}
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                pass
    return out


def knobs(cid: str) -> tuple[str | None, dict, Path]:
    file, strategy, extra = CANDIDATES[cid]
    if strategy is None:
        return None, dict(extra), file
    family = ROOT / qsim_rust.STRATEGIES[strategy]
    base = constants(family)
    mine = constants(file)
    over = {k: v for k, v in mine.items() if k in base and base[k] != v and isinstance(v, (int, float)) and k.isupper()}
    over.update(extra)
    return strategy, over, file


def tapes(params: Path, seeds: list[int], out_dir: Path, jobs: int) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    todo = [(params, s, out_dir / f"gen_{s}.csv") for s in seeds if not (out_dir / f"gen_{s}.csv").exists()]
    with ProcessPoolExecutor(max(1, min(jobs, len(todo) or 1))) as ex:
        list(ex.map(_gen, todo))
    return [out_dir / f"gen_{s}.csv" for s in seeds]


def _gen(task):
    params, seed, out = task
    p = json.loads(params.read_text())
    tmp = out.with_suffix(".tmp")
    tape_gen.generate(p, seed, p["duration_s"], tmp)
    tmp.rename(out)


def _python_run(task) -> float:
    file, over, data = task
    with tempfile.TemporaryDirectory() as d:
        bot = Path(d) / file.name
        text = file.read_text()
        for k, v in over.items():
            lines = text.splitlines()
            lines = [f"{k} = {v!r}" if l.startswith(f"{k} = ") else l for l in lines]
            text = "\n".join(lines) + "\n"
        bot.write_text(text)
        subprocess.run(["uv", "run", "exchange-simulator", "--strategy", str(bot), "--backtest", str(data), "--no-logs",
                        "--log-dir", str(Path(d) / "logs")], check=True, capture_output=True, cwd=ROOT)
        return json.loads((Path(d) / "logs" / "result.json").read_text())["pnl"]


def run(cid: str, files: list[Path], threads: int, overrides_list: list[dict] | None = None) -> list[list[float]]:
    """PnL[task][file] for the candidate (with each extra override set, default one task)."""
    strategy, over, file = knobs(cid)
    sets = [dict(over, **o) for o in (overrides_list or [{}])]
    if strategy is None:
        tasks = [(file, s, f) for s in sets for f in files]
        with ProcessPoolExecutor(threads) as ex:
            flat = list(ex.map(_python_run, tasks))
        return [flat[i * len(files):(i + 1) * len(files)] for i in range(len(sets))]
    res = qsim_rust.run_batch(strategy, sets, files, threads)
    return [[row.get("pnl", float("nan")) for row in task] for task in res]


def summary(values) -> dict:
    a = np.array(values, dtype=float)
    return {"mean": a.mean(), "sd": a.std(ddof=1) if len(a) > 1 else 0.0, "p5": np.percentile(a, 5), "se": a.std(ddof=1) / np.sqrt(len(a)) if len(a) > 1 else 0.0}


def parse_seeds(text: str) -> list[int]:
    if "-" in text:
        lo, hi = text.split("-")
        return list(range(int(lo), int(hi) + 1))
    return [int(x) for x in text.split(",")]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="experiments.generator.tape_eval", description=__doc__.split("\n")[0])
    ap.add_argument("--params", type=Path, required=True)
    ap.add_argument("--real", type=Path, required=True)
    ap.add_argument("--seeds", default="1-5")
    ap.add_argument("--dir", type=Path, help="where the generated tapes are cached (default: next to --params)")
    ap.add_argument("--candidates", default=",".join(CANDIDATES))
    ap.add_argument("--threads", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    ap.add_argument("--profile", action="store_true")
    ap.add_argument("--base", help="grid mode: the candidate the grid starts from")
    ap.add_argument("--grid", action="append", default=[], help="NAME=V1,V2,...")
    ap.add_argument("--out", type=Path, help="write the table as JSON")
    args = ap.parse_args(argv)
    seeds = parse_seeds(args.seeds)
    qsim_rust.build()
    files = tapes(args.params, seeds, args.dir or args.params.parent / "tapes", args.threads)
    report = {"seeds": seeds}
    if args.profile:
        from experiments.rounds import round_start
        print(round_start.format_profile(round_start.profile(str(files[0]))))
    if args.grid:
        axes = [(g.split("=")[0], [ast.literal_eval(v) for v in g.split("=")[1].split(",")]) for g in args.grid]
        cells = [dict(zip([a for a, _ in axes], vals)) for vals in itertools.product(*[v for _, v in axes])]
        pnl = np.array(run(args.base, files, args.threads, [{}] + cells))
        base = pnl[0]
        rows = []
        for cell, p in zip([{}] + cells, pnl):
            diff = p - base
            rows.append({"cell": cell, "mean": p.mean(), "p5": np.percentile(p, 5), "diff": diff.mean(),
                         "diff_se": diff.std(ddof=1) / np.sqrt(len(diff)) if len(diff) > 1 else 0.0, "wins": float((diff > 0).mean())})
        rows.sort(key=lambda r: -r["mean"])
        print(f"grid on {args.base} over {len(seeds)} generated seeds ({len(cells)} cells), by the generated mean:")
        for r in rows[:15]:
            print(f"  {json.dumps(r['cell']):60s} mean {r['mean']:>10,.0f}  p5 {r['p5']:>10,.0f}  vs base {r['diff']:+9,.0f} (se {r['diff_se']:,.0f}, wins {r['wins']:.2f})")
        best = rows[0]
        real = run(args.base, [args.real], args.threads, [{}, best["cell"]])
        print(f"chosen {json.dumps(best['cell'])}: real {real[1][0]:,.0f} against the base's {real[0][0]:,.0f}")
        report.update({"grid": rows, "chosen": best["cell"], "real_chosen": real[1][0], "real_base": real[0][0]})
    else:
        names = args.candidates.split(",")
        table = {}
        for cid in names:
            real = run(cid, [args.real], args.threads)[0][0]
            gen = run(cid, files, args.threads)[0]
            table[cid] = {"real": real, "gen": gen, **summary(gen)}
            s = table[cid]
            print(f"{cid:4s} real {real:>11,.0f}  generated mean {s['mean']:>11,.0f}  sd {s['sd']:>9,.0f}  p5 {s['p5']:>11,.0f}  ratio {s['mean'] / real if real else float('nan'):.2f}", flush=True)
        print("pairwise: share of seeds the row beats the column")
        print("      " + "".join(f"{c:>6s}" for c in names))
        for a in names:
            print(f"{a:6s}" + "".join(f"{np.mean(np.array(table[a]['gen']) > np.array(table[b]['gen'])):6.2f}" for b in names))
        report["table"] = table
    if args.out:
        args.out.write_text(json.dumps(report, indent=1, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())
