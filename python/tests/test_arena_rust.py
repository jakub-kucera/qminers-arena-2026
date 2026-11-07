"""rust/arena_sim against the Arena's own simulator (simulator/ at the repo root) on data/sample.csv.gz: the CLI's
lines, result.json and pnl.csv byte for byte for trend_follower and the F1 fallback maker as written, and every
result field, the PnL curve and the reject counts for parameter variants and the probe strategy
(python/tests/fixtures/qsim_probe.py), which drives the paths the two don't (modifies, cancels that lose, the
cap, the penalty). Skipped without cargo."""

from __future__ import annotations

import gzip
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from arena import qgrid, qsim_rust
from arena.botfile import BotFile

ROOT = qsim_rust.ROOT
pytestmark = pytest.mark.skipif(shutil.which("cargo") is None, reason="needs cargo (brew install rust)")

FIELDS = ["fills", "traded_volume", "inventory", "cash", "mark_price", "breach_penalty", "pnl", "pnl_se",
          "abs_inventory_q50", "abs_inventory_q68", "abs_inventory_q95", "abs_inventory_q997"]


@pytest.fixture(scope="module")
def sample(tmp_path_factory) -> Path:
    qsim_rust.build()
    path = tmp_path_factory.mktemp("qsim") / "sample.csv"
    with gzip.open(ROOT / "data" / "sample.csv.gz", "rb") as source, path.open("wb") as sink:
        shutil.copyfileobj(source, sink)
    return path


def python_run(bot: str, overrides: dict, data: Path) -> dict:
    """Their ExchangeSimulator at the rules' settings, counting rejects as arena.qgrid.run_one does."""
    from simulator.models import OrderStatus
    from simulator.simulator import ExchangeSimulator

    module = BotFile(ROOT / bot, {}, overrides).load()
    sim = ExchangeSimulator(strategy=qgrid.strategy_class(module)(), config=qgrid.config())
    counts = {"order": 0, "cancel": 0}
    notify = sim._private_notify

    def counted(event):
        if event.status == OrderStatus.REJECTED:
            counts["cancel" if event.message and "cancel" in event.message or event.remaining_quantity else "order"] += 1
        notify(event)

    sim._private_notify = counted
    result = sim.run(data).model_dump()
    result.update(rejected=counts["order"], cancel_rejected=counts["cancel"], curve=[list(p) for p in sim.pnl_curve(result["pnl"])])
    return result


@pytest.mark.parametrize("name, pnl, fills", [("trend_follower", "1878.00", 305), ("fallback_maker", "-5877.00", 303)])
def test_cli_byte_for_byte(sample, tmp_path, name, pnl, fills):
    bot = ROOT / qsim_rust.STRATEGIES[name]
    theirs = subprocess.run([sys.executable, "-m", "simulator.main", "--strategy", str(bot), "--backtest", str(sample),
                             "--log-dir", str(tmp_path / "py"), "--no-logs"], capture_output=True, text=True, check=True, cwd=ROOT)
    ours = subprocess.run([str(qsim_rust.BINARY), "--backtest", str(sample), "--strategy", name, "--log-dir", str(tmp_path / "rs")],
                          capture_output=True, text=True, check=True)
    lines = [line for line in theirs.stdout.splitlines() if not line.startswith("log_dir=")]
    assert [line for line in ours.stdout.splitlines() if not line.startswith("log_dir=")] == lines
    assert f"pnl={pnl}" in lines and f"fills={fills}" in lines
    for file in ("result.json", "pnl.csv"):
        assert (tmp_path / "rs" / file).read_bytes() == (tmp_path / "py" / file).read_bytes(), file


VARIANTS = [
    ("fallback_maker", {"QUOTE": 60, "LIMIT": 1500, "SKEW": 1500}),  # over 100 lots: the penalty, and the cap
    ("fallback_maker", {"QUOTE": 3, "WIND_DOWN_S": 1800, "SKEW": 5}),
    ("probe", {}),
    ("probe", {"QMAX": 400, "EVERY": 2, "SEED": 3}),
    ("probe", {"QMAX": 6, "EVERY": 1, "SEED": 11}),
]


def test_variants_every_field(sample):
    rust_runs = [qsim_rust.run_batch(name, [overrides], [sample])[0][0] for name, overrides in VARIANTS]
    hit = {"penalty": False, "rejected": False, "cancel_rejected": False}
    for (name, overrides), ours in zip(VARIANTS, rust_runs):
        theirs = python_run(qsim_rust.STRATEGIES[name], overrides, sample)
        assert ours.get("error") is None, ours
        for key in FIELDS + ["rejected", "cancel_rejected"]:
            assert ours[key] == theirs[key], (name, overrides, key, ours[key], theirs[key])
        assert ours["curve"] == theirs["curve"], (name, overrides)
        hit["penalty"] |= theirs["breach_penalty"] > 0
        hit["rejected"] |= theirs["rejected"] > 0
        hit["cancel_rejected"] |= theirs["cancel_rejected"] > 0
    assert all(hit.values()), hit  # the variants reach the paths they are here for


def test_grid_table(sample, capsys):
    assert qsim_rust.main(["fallback_maker", str(sample), "--grid", "QUOTE=3,5", "--grid", "LIMIT=30,50", "--threads", "2"]) == 0
    out = capsys.readouterr().out
    assert "out 25%" in out and "best by pnl" in out
    assert "-5,877" in out  # the baseline: F1 as written
