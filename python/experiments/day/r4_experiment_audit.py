"""Read-only reproduction of three round-4 experiment measurement findings.

    uv run python -m experiments.day.r4_experiment_audit --repo . --out audit.json
    # Also inspect existing K1 and action-oracle artifacts, without refitting:
    # --pred P/pred_r4.csv --cache P/ts_r4.npz --oracle P/a1/r4

The gate check compiles the repository's actual Rust feature constructor. The
oracle check concerns the first 780 tasks (seed 4's complete stratified sample).
No strategy source, saved results, or fitted model is modified.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def gate(repo):
    src = repo / "rust/arena_sim/src"
    harness = f'''
#[path = {json.dumps(str(src / "params.rs"))}] mod params;
#[path = {json.dumps(str(src / "strategies/profit_gate.rs"))}] mod profit_gate;
fn main() {{
    let mut x = [0.2; 39]; x[24] = 0.4; x[38] = 1.2;
    let mut mirror = x.map(|v| -v); mirror[24] = x[24]; mirror[38] = x[38];
    let buy = profit_gate::ProfitGate::feats(&x, 1.0, 0.9, 0.5, 0.2, false);
    let sell = profit_gate::ProfitGate::feats(&mirror, -1.0, -0.9, 0.5, -0.2, false);
    let changed: Vec<usize> = (0..44).filter(|&i| buy[i] != sell[i]).collect();
    assert_eq!(changed, vec![24, 38]);
    println!("{{:?}}", changed);
}}
'''
    with tempfile.TemporaryDirectory(prefix="r4_gate_audit_") as tmp:
        p = Path(tmp)
        (p / "probe.rs").write_text(harness)
        subprocess.run(["rustc", "--edition=2021", "-Awarnings", str(p / "probe.rs"),
                        "-o", str(p / "probe")], check=True, capture_output=True, text=True)
        changed = json.loads(subprocess.check_output([str(p / "probe")], text=True))
    return {"mirrored_gate_columns_changed": changed,
            "columns": {24: "group volume share", 38: "posterior sd"},
            "source_sha256": digest(src / "strategies/profit_gate.rs")}


def classifier(pred_path, cache_path):
    import numpy as np
    from experiments.day.take_classes import asof, jump_state, load_pred, spaced
    x = load_pred(pred_path)
    with np.load(cache_path) as z:
        tt = np.round(z["t"] * 1e6).astype(np.int64)
        mid = (z["bb"] + z["ba"]) * 0.5
    t = x["t"]
    sig = x["pred"] - x["skew"]
    direction = np.where(sig >= 0, 1, -1)
    relevant = ((x["spread"] == 1) & (np.abs(sig) >= 0.4) & (np.abs(sig) <= 1.5)
                & (direction * x["inv"] < 100))
    boundary = t[0] + 0.7 * (t[-1] - t[0])
    ii = np.flatnonzero(relevant & (t >= boundary) & (t + 5e6 < t[-1] + 1))
    test = ii[spaced(t[ii], 400000)]
    diff = mid[asof(tt, t[test])] - x["mid"][test]
    return {"test_points": len(test),
            "f5_takes": int((np.abs(sig[test]) > np.where(jump_state(t, x["mid"])[test], 0.65, 0.75)).sum()),
            "adjacent_pairs": len(test) - 1,
            "overlapping_label_pairs": {str(h): int((np.diff(t[test]) < h * 1e6).sum()) for h in (0.4, 1.0, 5.0)},
            "initial_mid_mismatch_points": int((diff != 0).sum()),
            "max_initial_mid_error": float(np.abs(diff).max()),
            "pred_sha256": digest(pred_path), "cache_sha256": digest(cache_path)}


def oracle(path):
    from experiments.day.action_oracle import read_log, room
    decisions, partials = read_log(path / "fa_log.csv")
    base = json.loads((path / "base.json").read_text())
    t0, t1 = base["curve"][0][0], base["curve"][-1][0]
    takes = [r for r in decisions if r["kind"] == 1 and r["t"] < t1]
    near = [r for r in decisions if r["kind"] == 0 and r["t"] < t1]
    pools = {"wait": takes, "flip": [r for r in takes if r["sign"] * r["inv"] < 0],
             "take": [r for r in near if room(r) > 0],
             "reduce": [r for r in near if r["inv"] != 0],
             "complete": [r for r in partials if r["t"] < t1]}
    tasks = {t["id"]: t for t in map(json.loads, (path / "tasks.jsonl").read_text().splitlines())}
    with (path / "branches.csv").open() as f:
        rows = [{**tasks[int(r["id"])], "A300": float(r["A300"])} for r in csv.DictReader(f)]
    result = {}
    for cls, n in {"wait": 260, "flip": 110, "take": 170, "reduce": 110, "complete": 130}.items():
        pool = pools[cls]
        width = (t1 - t0) / n
        def bucket(r):
            return min(n - 1, int((r["t"] - t0) / width))
        sizes = Counter(bucket(r) for r in pool)
        sample = [r for r in rows if r["cls"] == cls and r["id"] < 780]
        counts = Counter(bucket(r) for r in sample)
        if len(sample) != n or len(sizes) != n or set(counts.values()) != {1}:
            raise ValueError("Requires the complete original seed-4 sample, one row per nonempty time stratum")
        # Inclusion probability in stratum h is 1/N_h, not n/N.
        weighted_sum = sum(r["A300"] * sizes[bucket(r)] for r in sample)
        result[cls] = {"pool": len(pool), "sample": n,
                       "stratum_size_min_max": [min(sizes.values()), max(sizes.values())],
                       "unweighted_mean": sum(r["A300"] for r in sample) / n,
                       "weighted_mean": weighted_sum / len(pool),
                       "unweighted_positive_pool": sum(max(0, r["A300"]) for r in sample) * len(pool) / n,
                       "weighted_positive_pool": sum(max(0, r["A300"]) * sizes[bucket(r)] for r in sample)}
    return {"first_780_only": True, "classes": result,
            "hashes": {name: digest(path / name) for name in ("base.json", "fa_log.csv", "tasks.jsonl", "branches.csv")}}


def warm_controls(repo):
    import ast
    import types
    base = repo / "python/bots/qminers/candidates"
    result = []
    for name, overrides in (("r4_W2_warm10k.py", {}), ("r4_W3_flow_depth.py", {}),
                            ("r4_W3_flow_depth.py", {"FLOW2": 0}),
                            ("r4_W3_flow_depth.py", {"FLOW2": 0, "TAKE_DEPTH_K": 0}),
                            ("r4_W3_flow_depth.py", {"PRIOR_MASS": 0})):
        tree = ast.parse((base / name).read_text())
        found = set()
        for node in tree.body:
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name) and node.targets[0].id in overrides):
                key = node.targets[0].id
                node.value = ast.Constant(overrides[key])
                found.add(key)
        assert found == set(overrides)
        module = types.ModuleType("warm_control_audit")
        exec(compile(ast.fix_missing_locations(tree), name, "exec"), module.__dict__)
        bot = module.PassiveStrategy()
        result.append({"bot": name, "overrides": overrides, "features": bot.FEATURE_COUNT,
                       "mass": bot._mass, "labels": bot._labels,
                       "flow2": getattr(module, "FLOW2", 0), "depth": getattr(module, "TAKE_DEPTH_K", 0)})
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, default=Path("."))
    p.add_argument("--pred", type=Path)
    p.add_argument("--cache", type=Path)
    p.add_argument("--oracle", type=Path)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if bool(a.pred) != bool(a.cache):
        p.error("--pred and --cache must be supplied together")
    result = {"profit_gate": gate(a.repo.resolve()), "warm_controls": warm_controls(a.repo.resolve())}
    if a.pred:
        result["classifier"] = classifier(a.pred, a.cache)
    if a.oracle:
        result["oracle"] = oracle(a.oracle)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
