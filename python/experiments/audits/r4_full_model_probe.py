"""Round-4 coverage probe: full-feature regression, real prefix only, then actual replay.

    uv run python -m experiments.audits.r4_full_model_probe dump TAPE --out DIR
    uv run python -m experiments.audits.r4_full_model_probe fit --out DIR
    uv run python -m experiments.audits.r4_full_model_probe replay TAPE --out DIR

The 39 F5 inputs and its exact matured 400-ms labels come from RIDGE_FEAT_LOG.
Train before 3000 s, choose by MSE in 3000-4200 s, test after 4200 s. Purge 1.4 s
at training/calibration ends. No synthetic data. A replay-only wrapper uses the
selected frozen forecast after 4200 s, retaining F5's learning and execution.
This is an experiment, not an upload file. No candidate or Rust source is edited.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

import numpy as np

from experiments.rounds.family_rust import F5
from experiments.taker.pretrain_forecast import fit_mlp


ROOT = Path(__file__).resolve().parents[3]
BOT = ROOT / "python/bots/qminers/candidates/round3/r3_F5_jump_bar.py"


def file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dump(args):
    from arena import qsim_rust
    qsim_rust.build()
    tokens = shlex.split(F5)
    params = dict(token.split("=", 1) for token in tokens[1::2])
    params = {k: float(v) for k, v in params.items()}
    args.out.mkdir(parents=True, exist_ok=True)
    partial = args.out / "f5.partial.bin"
    os.environ["RIDGE_FEAT_LOG"] = str(partial.resolve())
    os.environ.pop("RIDGE_WARM", None)
    os.environ.pop("RIDGE_DUMP", None)
    result = qsim_rust.run_batch("ridge_maker", [params], [args.tape.resolve()], threads=1)[0][0]
    if result.get("error"):
        raise RuntimeError(result["error"])
    partial.replace(args.out / "f5.bin")
    (args.out / "baseline.json").write_text(json.dumps(result) + "\n")
    (args.out / "provenance.json").write_text(json.dumps({"tape": str(args.tape.resolve()),
        "tape_sha256": file_hash(args.tape), "bot_sha256": file_hash(BOT),
        "rust_binary_sha256": file_hash(qsim_rust.BINARY), "params": params,
        "rows": (args.out / "f5.bin").stat().st_size // (58 * 8)}, indent=2) + "\n")
    print({k: result[k] for k in ("pnl", "fills", "traded_volume")}, flush=True)


class Predictor:
    def __init__(self, model):
        self.model = model
        self.kind = model["kind"]
        if self.kind in ("ridge", "mlp"):
            self.mu, self.sd = np.array(model["mu"]), np.array(model["sd"])
        if self.kind == "ridge":
            self.weights = np.array(model["weights"])
        elif self.kind == "mlp":
            self.W = [np.array(w) for w in model["W"]]
            self.B = [np.array(b) for b in model["B"]]

    def one(self, row):
        if self.kind == "hgb":
            value = self.model["baseline"]
            for tree in self.model["trees"]:
                k = 0
                while not tree[k][4]:
                    node = tree[k]
                    k = node[2] if row[node[0]] <= node[1] else node[3]
                value += tree[k][5]
            return value
        h = (np.asarray(row) - self.mu) / self.sd
        if self.kind == "ridge":
            return float(h @ self.weights + self.model["intercept"])
        for w, b in zip(self.W[:-1], self.B[:-1]):
            h = np.tanh(h @ w + b)
        return float((h @ self.W[-1] + self.B[-1])[0])


def metrics(y, p):
    pc = np.clip(p, -2, 2)
    return {"n": len(y), "mse": float(np.mean((p-y)**2)),
        "r2": float(1-np.mean((p-y)**2)/np.var(y)),
        "clipped_mse": float(np.mean((pc-y)**2)),
        "corr": float(np.corrcoef(y, p)[0, 1]),
        "clipped_corr": float(np.corrcoef(y, pc)[0, 1])}


def fit(args):
    from sklearn.ensemble import HistGradientBoostingRegressor
    a = np.fromfile(args.out / "f5.bin", dtype="<f8").reshape(-1, 58)
    t, y, old = a[:, 0], a[:, 2], a[:, 3]
    X = a[:, 5:44]
    train, cal, test = t < 2998.6, (t >= 3000) & (t < 4198.6), t >= 4200
    assert train.any() and cal.any() and test.any() and np.isfinite(a).all()
    groups = {"calibration": cal, "test": test,
        **{f"test_{start}_{start+600}": (t >= start) & (t < start+600) for start in (4200, 4800, 5400)}}
    report = {"protocol": {"train_end": 3000, "calibration_end": 4200, "purge_s": 1.4,
                          "training_rows": int(train.sum()), "features": 39},
              "models": {"online_F5": {name: metrics(y[mask], old[mask]) for name, mask in groups.items()}}}
    predictions, models = {}, {}

    def save(name, predict, model):
        pred = predict(X)
        custom = Predictor(model)
        ix = np.linspace(0, len(X)-1, 100, dtype=int)
        error = max(abs(custom.one(X[i]) - pred[i]) for i in ix)
        assert error < 1e-8, (name, error)
        started = time.monotonic()
        for i in ix:
            custom.one(X[i])
        model["inference_us_per_row"] = (time.monotonic()-started)/len(ix)*1e6
        predictions[name], models[name] = pred, model
        report["models"][name] = {key: metrics(y[mask], pred[mask]) for key, mask in groups.items()}
        (args.out / (name + ".json")).write_text(json.dumps(model) + "\n")
        print(name, "cal", report["models"][name]["calibration"], flush=True)

    mu, sd = X[train].mean(0), X[train].std(0) + 1e-6
    Z = (X-mu)/sd
    Zt = np.column_stack((Z[train], np.ones(train.sum())))
    ridge = np.eye(40) * (0.003*train.sum())
    ridge[-1, -1] = 0
    beta = np.linalg.solve(Zt.T @ Zt + ridge, Zt.T @ y[train])
    save("ridge", lambda x: (x-mu)/sd @ beta[:-1] + beta[-1],
         {"kind": "ridge", "mu": mu.tolist(), "sd": sd.tolist(),
          "weights": beta[:-1].tolist(), "intercept": float(beta[-1])})
    for seed in (0, 1):
        predict, model = fit_mlp(X[train], y[train], hidden=(32, 16), epochs=32, seed=seed, delta=6.0)
        save(f"mlp{seed}", predict, dict(model, kind="mlp"))
    for count in (64, 128):
        model = HistGradientBoostingRegressor(max_iter=count, max_leaf_nodes=15,
            learning_rate=0.08, min_samples_leaf=200, l2_regularization=1.0,
            random_state=0, early_stopping=False).fit(X[train], y[train])
        trees = []
        for iteration in model._predictors:
            nodes = iteration[0].nodes
            assert not nodes["is_categorical"].any()
            trees.append([[int(n["feature_idx"]), float(n["num_threshold"]), int(n["left"]),
                int(n["right"]), int(n["is_leaf"]), float(n["value"])] for n in nodes])
        save(f"hgb{count}", model.predict, {"kind": "hgb", "trees": trees,
            "baseline": float(model._baseline_prediction[0, 0])})
    chosen = min(models, key=lambda name: report["models"][name]["calibration"]["clipped_mse"])
    report["selected_by_calibration_only"] = chosen
    selected = dict(models[chosen], start_us=4_200_000_000, selected_name=chosen,
                    feature_count=39, base_sha256=file_hash(BOT), blend=1.0)
    (args.out / "selected.json").write_text(json.dumps(selected) + "\n")
    (args.out / "fit.json").write_text(json.dumps(report, indent=2) + "\n")
    np.savez_compressed(args.out / "predictions.npz", t=t, y=y, online=old, **predictions)
    print("Selected on calibration only:", chosen, flush=True)
    for name, row in report["models"].items():
        print(name, "test", row["test"], flush=True)


def replay(args):
    root = args.repo.resolve()
    wrapper = Path(__file__).with_name("r4_full_model_bot.py")
    logdir = (args.out / "replay").resolve()
    env = dict(os.environ, R4_MODEL=str((args.out / "selected.json").resolve()),
               R4_BASE=str(BOT), PYTHONPATH=str(ROOT / "python"))
    subprocess.run([sys.executable, "-m", "simulator.main", "--strategy", str(wrapper),
        "--backtest", str(args.tape.resolve()), "--log-dir", str(logdir), "--no-logs"],
        cwd=root, env=env, check=True)
    report(args)


def report(args):
    logdir = args.out / "replay"
    from experiments.pnl_segments import segments
    blocks, total = segments(str(logdir / "pnl.csv"), 600, 10)
    baseline = json.loads((args.out / "baseline.json").read_text())
    curve = baseline["curve"]
    def at(second):
        end = curve[0][0] + second * 1e6
        return next((pnl for timestamp, pnl in reversed(curve) if timestamp <= end), 0.0)
    original = [at((i+1)*600)-at(i*600) for i in range(10)]
    diff = [a-b for a, b in zip(blocks, original)]
    report = {"total_pnl": total, "baseline_pnl": baseline["pnl"],
              "segment_differences": diff, "test_difference": sum(diff[7:]),
              "test_segments": diff[7:], "prefix_difference": sum(diff[:7])}
    (args.out / "replay_comparison.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("dump", "fit", "replay", "report"))
    parser.add_argument("tape", nargs="?", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path("."))
    args = parser.parse_args()
    if args.command in ("dump", "replay") and args.tape is None:
        parser.error("dump and replay require a tape")
    globals()[args.command](args)


if __name__ == "__main__":
    main()
