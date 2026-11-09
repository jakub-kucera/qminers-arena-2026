"""Audit W2's saved prior, causal learning, order accounting and saved validation curves.

    uv run python -m experiments.audits.r4_warm_audit --repo . --out data/arena/gen/w2_audit/audit.json

Read-only with respect to bots and existing results. This runs small deterministic
checks, not a market replay. The result folders must contain the downloaded portal
results; their metadata does not bind them to a submitted source hash.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import math
import os
import statistics
import subprocess
import sys
from pathlib import Path

from experiments.rounds.warm_embed import check, read_stats
from experiments.pnl_segments import segments
from simulator.models import OrderStatus, PrivateOrderEvent
from simulator.strategy import StrategyContext


WARM_KEYS = {"PRIOR_MASS", "WARM_MASS", "WARM_XX", "WARM_XY"}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def normalized(source):
    """Exclude only the module docstring, warm constants and warm init guard."""
    tree = ast.parse(source)
    if isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant):
        tree.body.pop(0)
    tree.body = [node for node in tree.body if not (
        isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in WARM_KEYS)]
    for cls in tree.body:
        if isinstance(cls, ast.ClassDef):
            for method in cls.body:
                if isinstance(method, ast.FunctionDef) and method.name == "__init__":
                    method.body = [node for node in method.body if not (
                        isinstance(node, ast.If) and any(isinstance(n, ast.Name) and n.id == "PRIOR_MASS"
                                                       for n in ast.walk(node.test)))]
    return ast.dump(tree, include_attributes=False)


def cholesky_solve(matrix, rhs):
    """Independent positive-definite solver, unlike the bot's Gauss-Jordan."""
    n = len(rhs)
    lower = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            residual = matrix[i][j] - sum(lower[i][k] * lower[j][k] for k in range(j))
            lower[i][j] = math.sqrt(residual) if i == j else residual / lower[j][j]
    y = [0.0] * n
    for i in range(n):
        y[i] = (rhs[i] - sum(lower[i][j] * y[j] for j in range(i))) / lower[i][i]
    x = [0.0] * n
    for i in reversed(range(n)):
        x[i] = (y[i] - sum(lower[j][i] * x[j] for j in range(i + 1, n))) / lower[i][i]
    return x


def learning_checks(module):
    bot = module.PassiveStrategy()
    assert bot._mass == 10000 and bot._labels == bot.MIN_LABELS
    bot._learn(0, 10000.5)
    assert bot._last_fit_us == 0 and len(bot._observations) == 0
    ridge = max(30.0, 0.003 * bot._mass)
    matrix = [row[:] for row in bot._xx]
    for i in range(bot.FEATURE_COUNT):
        matrix[i][i] += ridge
    expected = cholesky_solve(matrix, bot._xy)
    error = max(abs(a - b) for a, b in zip(expected, bot._weights))
    assert error < 1e-10 and all(math.isfinite(x) for x in bot._weights)
    labels = bot._labels
    features = (1.0,) + (0.0,) * (bot.FEATURE_COUNT - 1)
    bot._observations.append((0, 10000.5, features, 0.0))
    bot._learn(bot.HORIZON_US - 1, 10001.5)
    assert bot._labels == labels and len(bot._observations) == 1
    old_xy, old_mass = bot._xy[0], bot._mass
    bot._learn(bot.HORIZON_US, 10001.5)
    assert bot._labels == labels + 1 and not bot._observations
    assert bot._xy[0] == old_xy + 1 and bot._mass == old_mass + 1
    bot._observations.append((0, 10000.5, features, 0.0))
    bot._learn(bot.HORIZON_US + 1_000_001, 10001.5)
    assert bot._labels == labels + 1 and not bot._observations
    return {"initial_mass": 10000, "initial_labels": labels, "initial_ridge": ridge,
            "first_fit_before_live_labels": True, "cholesky_max_weight_error": error,
            "label_maturity_and_stale_discard": "pass"}


def attached(module):
    bot, requests = module.PassiveStrategy(), []

    def submit(request):
        requests.append(request)
        return f"test-{len(requests)}"

    bot._attach_context(StrategyContext(submit, lambda _: None, lambda *_: None, lambda: 1_000_000))
    return bot, requests


def execution_checks(module):
    cases = 0
    for inventory in (-100, -80, 0, 80, 100):
        for sign in (-1, 1):
            for reserved in (0, 1, 40):
                if reserved > 100 - sign * inventory:
                    continue
                for accepted, canceling in ((False, False), (True, False), (True, True)):
                    bot, sent = attached(module)
                    bot.inventory = inventory
                    if reserved:
                        bot._orders["existing"] = [sign, 100, reserved, accepted, canceling, 0, 0, 0]
                    bot._take(1_000_000, sign * 2.0, 1, 100, 101)
                    want = min(200, 100 - sign * inventory - reserved)
                    assert sum(order.quantity for order in sent) == want
                    assert sign * inventory + sum(r[2] for r in bot._orders.values() if r[0] == sign) <= 100
                    cases += 1
    for sign in (-1, 1):
        bot, sent = attached(module)
        bot._take(1_000_000, sign * 2.0, 1, 100, 101)
        oid = "test-1"

        def event(status, filled=0, remaining=0, price=None):
            bot.on_private_order_update(PrivateOrderEvent(timestamp_us=1_000_000, order_id=oid, status=status,
                filled_quantity=filled, remaining_quantity=remaining, fill_price=price))

        event(OrderStatus.ACCEPTED, remaining=100)
        event(OrderStatus.PARTIALLY_FILLED, 25, 75, 101)
        event(OrderStatus.PARTIALLY_FILLED, 35, 40, 102)
        assert bot.inventory == sign * 60 and bot.cash == -sign * (25 * 101 + 35 * 102)
        assert bot._orders[oid][2] == 40
        event(OrderStatus.CANCELED)
        event(OrderStatus.REJECTED)  # late failed cancel after removal is harmless
        assert not bot._orders
        bot, sent = attached(module)
        bot._take(1_000_000, sign * 2.0, 1, 100, 101)
        event(OrderStatus.REJECTED)
        assert not bot._orders and bot.inventory == 0 and bot.cash == 0
    bot, sent = attached(module)
    bot._take(1_000_000, 5.0, 2, 100, 102)
    bot._take(1_000_000, 0.70, 1, 100, 101)
    assert not sent
    bot._jump_until = 2_000_000
    bot._take(1_000_000, 0.70, 1, 100, 101)
    assert len(sent) == 1 and sent[0].quantity == 100
    return {"all_live_reservation_cases": cases, "incremental_fills_and_ioc_cancel_both_sides": "pass",
            "new_reject_and_late_cancel_reject": "pass", "spread_and_jump_gates": "pass"}


def validation(repo):
    base = repo / "data/arena/round4"
    folders = {"F5": "r4_W1_warm_res", "W2": "r4_W2_warm10k_res", "MH3": "r4_MH3_res",
               "X1R3": "r4_X1R3_res"}
    curves = {name: segments(str(base / folder / "pnl.csv"), 1000, 12) for name, folder in folders.items()}
    results = {}
    engine_keys = ("latency", "position_limit", "max_potential_position", "position_breach_penalty_per_second")
    baseline_meta = json.loads((base / folders["F5"] / "metadata.json").read_text())
    for name, folder in folders.items():
        path = base / folder
        result = json.loads((path / "result.json").read_text())
        meta = json.loads((path / "metadata.json").read_text())
        assert all(meta[k] == baseline_meta[k] for k in engine_keys)
        assert result["pnl"] == result["cash"] + result["inventory"] * result["mark_price"] - result["breach_penalty"]
        blocks, total = curves[name]
        assert total == result["pnl"]
        diff = [a - b for a, b in zip(blocks, curves["F5"][0])]
        sd = statistics.stdev(diff)
        results[name] = {"pnl": total, "difference": total - curves["F5"][1],
            "segments": blocks, "segment_differences": diff, "segments_ahead": sum(x > 0 for x in diff),
            "descriptive_paired_t": statistics.mean(diff) / (sd / math.sqrt(12)) if sd else None,
            "hashes": {f: sha(path / f) for f in ("result.json", "metadata.json", "pnl.csv")},
            "pnl_accounting": "pass", "breach_penalty": result["breach_penalty"], "engine": {k: meta[k] for k in engine_keys}}
    return results


def replay_checks(repo, out):
    """Optional full public replay; sequential, one worker, existing build reused."""
    from arena import qsim_rust
    from experiments.rounds.family_rust import F5
    import shlex

    repo, out = repo.resolve(), out.resolve()
    qsim_rust.ROOT = repo
    qsim_rust.MANIFEST = repo / "rust/Cargo.toml"
    qsim_rust.BINARY = repo / "rust/target/release/arena-sim"
    tokens = shlex.split(F5)
    params = {}
    for i in range(0, len(tokens), 2):
        assert tokens[i] == "--set"
        key, value = tokens[i + 1].split("=", 1)
        params[key] = float(value)
    original_env = os.environ.copy()
    os.environ["CARGO_BUILD_JOBS"] = "1"
    try:
        qsim_rust.build()
        os.environ["RIDGE_DUMP"] = str(out / "reproduced_r4_stats.txt")
        os.environ.pop("RIDGE_WARM", None)
        tape = repo / "data/arena/round4/round4_public.csv"
        print("Replaying cold F5 and regenerating public statistics (Rust, one worker).", flush=True)
        cold = qsim_rust.run_batch("ridge_maker", [params], [tape], threads=1)[0][0]
        os.environ.pop("RIDGE_DUMP")
        os.environ["RIDGE_WARM"] = str(repo / "data/arena/round4/r4_stats.txt")
        print("Replaying W2 (Rust, one worker).", flush=True)
        warm = qsim_rust.run_batch("ridge_maker", [dict(params, PRIOR_MASS=10000)], [tape], threads=1)[0][0]
        (out / "rust_replays.json").write_text(json.dumps({"F5": cold, "W2": warm}) + "\n")
        assert cold["pnl"] == 1029443 and warm["pnl"] == 1029781
        print("Replaying the unmodified W2 Python upload on the full public tape.", flush=True)
        subprocess.run([sys.executable, "-m", "simulator.main", "--strategy",
            str(repo / "python/bots/qminers/candidates/round4/r4_W2_warm10k.py"), "--backtest", str(tape),
            "--log-dir", str(out / "python_w2"), "--no-logs"], cwd=repo, check=True)
        python = json.loads((out / "python_w2/result.json").read_text())
        keys = ("pnl", "fills", "traded_volume", "inventory", "breach_penalty", "pnl_se")
        assert all(python[k] == warm[k] for k in keys), {k: (python[k], warm[k]) for k in keys}
        original = repo / "data/arena/round4/r4_stats.txt"
        reproduced = out / "reproduced_r4_stats.txt"
        return {"F5_pnl": cold["pnl"], "W2_python_rust_exact": {k: python[k] for k in keys},
                "public_stats_reproduced_byte_for_byte": original.read_bytes() == reproduced.read_bytes(),
                "reproduced_stats_sha256": sha(reproduced), "rust_source_sha256": sha(
                    repo / "rust/arena_sim/src/strategies/ridge_maker.rs"),
                "tape_sha256": sha(tape)}
    finally:
        os.environ.clear()
        os.environ.update(original_env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--replay", action="store_true", help="also rebuild Rust and replay F5/W2 on the full public tape")
    args = parser.parse_args()
    candidates = args.repo / "python/bots/qminers/candidates"
    names = ("r3_F5_jump_bar.py", "r4_W1_warm.py", "r4_W2_warm10k.py", "r4_MH3.py", "r4_X1R3.py")
    paths = {name: candidates / name for name in names}
    hashes = {name: sha(path) for name, path in paths.items()}
    normalized_f5 = normalized(paths[names[0]].read_text())
    assert all(normalized(paths[name].read_text()) == normalized_f5 for name in names[1:3])
    module = load(paths["r4_W2_warm10k.py"])
    stats_path = args.repo / "data/arena/round4/r4_stats.txt"
    model = read_stats(stats_path)[0]
    check(paths["r4_W2_warm10k.py"].read_text(), model, 10000.0)
    report = {"source_hashes": hashes, "stats_sha256": sha(stats_path),
        "stats_match_bit_for_bit": True, "stats_mass": float(model["mass"]), "stats_labels": model["labels"],
        "w1_w2_match_f5_except_warm_start": True, "learning": learning_checks(module),
        "execution": execution_checks(module), "validation": validation(args.repo),
        "limitations": ["No fresh market replay or W2-specific Rust/Python parity run.",
                        "Downloaded result metadata has no submitted-source hash.",
                        "Segment t values are descriptive, not an independent-tape significance test.",
                        "W2 uses whole-public-tape statistics; its public replay is in sample."]}
    assert hashes == {name: sha(path) for name, path in paths.items()}, "candidate changed during audit"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    if args.replay:
        report["replay"] = replay_checks(args.repo, args.out.parent)
        report["limitations"].pop(0)
        assert hashes == {name: sha(path) for name, path in paths.items()}, "candidate changed during replay"
        args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"out": str(args.out), "learning": report["learning"], "execution": report["execution"],
        "validation": {name: {k: row[k] for k in ("pnl", "difference", "segments_ahead", "descriptive_paired_t")}
                       for name, row in report["validation"].items()}}, indent=2))


if __name__ == "__main__":
    main()
