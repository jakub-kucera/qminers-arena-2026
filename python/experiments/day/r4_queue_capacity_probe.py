"""Check whether long-horizon ridge experiments retained their training labels.

    uv run python -m experiments.day.r4_queue_capacity_probe TAPE --out DIR --jobs 3

Uses the existing OBS_CAP knob only. Each isolated Rust process writes its own
statistics dump; counts, PnL and temporal splits are recorded, without source edits.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shlex
import subprocess

from arena import qsim_rust
from experiments.day.family_rust import F5
from experiments.day.warm_embed import read_stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tape", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=3)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    qsim_rust.build()
    tokens = shlex.split(F5)
    base = {k: float(v) for k, v in (t.split("=", 1) for t in tokens[1::2])}
    specs = [(horizon, cap) for horizon in (400000, 1000000, 1500000, 2000000, 5000000) for cap in (64, 512)]

    def run(spec):
        horizon, cap = spec
        name = f"h{horizon}_cap{cap}"
        params = dict(base, HORIZON_US=horizon, OBS_CAP=cap, FT_EDGE=0.25 if horizon == 400000 else 0.9)
        task = args.out / (name + ".task.jsonl")
        stats = args.out / (name + ".stats.txt")
        task.write_text(json.dumps(params) + "\n")
        env = dict(os.environ, RIDGE_DUMP=str(stats.resolve()))
        for key in ("RIDGE_WARM", "RIDGE_FEAT_LOG", "RIDGE_PRED_LOG"):
            env.pop(key, None)
        result = subprocess.run([str(qsim_rust.BINARY), "batch", "--strategy", "ridge_maker",
            "--tasks", str(task.resolve()), "--threads", "1", "--public-depth", "20",
            "--backtest", str(args.tape.resolve())], env=env, capture_output=True, text=True, check=True)
        row = json.loads(result.stdout.splitlines()[0])
        if row.get("error"):
            raise RuntimeError(row["error"])
        models = read_stats(stats)
        model = models.get(0, {"labels": 0, "mass": 0})
        curve = row["curve"]
        split = curve[0][0] + 0.75 * (curve[-1][0]-curve[0][0])
        before = next(p for t, p in reversed(curve) if t <= split)
        summary = {"horizon_us": horizon, "cap": cap, "labels": model["labels"], "mass": float(model["mass"]),
            "pnl": row["pnl"], "first75": before, "last25": row["pnl"]-before,
            "fills": row["fills"], "traded_volume": row["traded_volume"], "params": params}
        (args.out / (name + ".json")).write_text(json.dumps(row) + "\n")
        print({k: summary[k] for k in ("horizon_us", "cap", "labels", "pnl", "first75", "last25")}, flush=True)
        return summary

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        rows = list(pool.map(run, specs))
    (args.out / "report.json").write_text(json.dumps(rows, indent=2) + "\n")


if __name__ == "__main__":
    main()
