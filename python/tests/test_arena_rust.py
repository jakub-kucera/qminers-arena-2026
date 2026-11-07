"""rust/arena_sim against the Arena's own simulator (simulator/ at the repo root) on data/sample.csv.gz: the CLI's
lines, result.json and pnl.csv byte for byte for trend_follower and the F1 fallback maker as written, and every
result field, the PnL curve and the reject counts for parameter variants and the probe strategy
(python/tests/fixtures/qsim_probe.py), which drives the paths the two don't (modifies, cancels that lose, the
cap, the penalty). The room maker (python/bots/qminers/families/room_maker.py) on a synthetic tape with one- and
two-tick spreads and thin touches, so every knob's path runs; and, with ARENA_SIM_FULL=1 and the playground's
sample_v2.csv and round 1's tape present (data/arena/, or ARENA_SIM_DATA), F3 and knob settings on them byte for
byte (about 30 s a Python run). The shrink maker (python/bots/qminers/families/shrink_maker.py, the same Rust struct
with DEPL_FRAC, REACT_CANCEL and MOM_LOTS) the same two ways, and family 12's alloc_maker.py and signal_maker.py
(the same struct at R1-F6's defaults, with their knobs; R1-F6b and R1-F7 among the real-tape cases), and R1-F8
(candidates/r1_F8_take_join.py, the same struct at its own defaults, as `take_maker`). The ridge maker at R1-C1,
the codex candidates on round 1 and round 2's forecast takers (R2-T2, L1, L3, L8, L9) on round2_public.csv. Skipped
without cargo."""

from __future__ import annotations

import gzip
import json
import os
import random
import re
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


@pytest.mark.parametrize("name, pnl, fills", [("trend_follower", "1878.00", 305), ("fallback_maker", "-5877.00", 303),
                                             ("ridge_maker", "-91974.00", 1316)])
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


def write_tape(path: Path, seconds: int = 900, seed: int = 7) -> Path:
    """The starter's format: each second the market's book is requoted around a random-walk mid, two levels a side,
    the spread one tick in odd minutes and two in even ones, the touch's lots from 5 to 60 (thin touches for
    DEPLETE_LOTS, MIN_QUEUE, IMB); three times a second a fill-and-kill order of 1 to 70 lots takes one side."""
    rng = random.Random(seed)
    rows, next_id, live, mid = [], 1_000_001, [], 20_000
    for second in range(seconds):
        t = float(second)
        for order_id in live:
            rows.append([f"{t:.6f}", "Cancel", order_id, "", "", "", ""])
            t += 1e-6
        mid += rng.choice((-1, 0, 0, 0, 1))
        half = 0 if (second // 60) % 2 else 1
        live = []
        for side, touch, away in (("B", mid - half, -1), ("A", mid + 1, 1)):
            for level in range(2):
                rows.append([f"{t:.6f}", "Insert", next_id, side, rng.randint(5, 60), touch + away * level, "G"])
                live.append(next_id)
                next_id += 1
                t += 1e-6
        for quarter in range(1, 4):
            side = rng.choice("BA")
            price = mid + 4 if side == "B" else mid - 4
            rows.append([f"{second + quarter / 4:.6f}", "Insert", next_id, side, rng.randint(1, 70), price, "F"])
            next_id += 1
    with path.open("w") as f:
        f.write("Time,Operation,OrderId,Side,Volume,Price,Lifespan\n")
        f.write("".join(",".join(str(x) for x in row) + "\n" for row in rows))
    return path


# The room maker's knobs, each setting a different path (F3 as written first); the synthetic tape is 900 s.
ROOM = [
    {},
    {"SESSION_S": 700, "WIND_DOWN_S": 60, "FLAT_S": 120},
    {"LEVELS": 2, "SIZE_DEEP": 30, "KEEP_DEPTH": 2},
    {"DEPLETE_LOTS": 20},
    {"DEPLETE_LOTS": 30, "DEPLETE_SIZE": 40},
    {"BACK_POS": 60},
    {"SIZE_NARROW": 150, "SHRINK_NARROW": 1},
    {"SIZE_NARROW": 40, "SHRINK_NARROW": 1, "TOPUP": 0},
    {"UNWIND": 60, "UNWIND_TO": 30},
    {"IMB": 0.5, "MIN_QUEUE": 10, "REBALANCE": 1, "LEVELS": 3, "CANCEL_ALONE": 0, "SKEW": 60, "SKEW_CANCEL": 0,
     "INSIDE_POS": 40, "INSIDE_SPREAD": 2, "SESSION_S": 800, "WIND_DOWN_S": 200, "FLAT_S": 50, "UNWIND": 70, "UNWIND_TO": 30},
]


# The shrink maker's two knobs (off: the room maker), alone and with the knobs they act through.
SHRINK = [
    {},
    {"DEPLETE_LOTS": 40, "DEPL_FRAC": 0.5},
    {"DEPLETE_LOTS": 50, "DEPL_FRAC": 0.3, "DEPLETE_SIZE": 20},
    {"REACT_CANCEL": 1},
    {"REACT_CANCEL": 1, "DEPLETE_LOTS": 40, "DEPL_FRAC": 0.5, "SIZE_NARROW": 40, "SHRINK_NARROW": 1},
    {"MOM_LOTS": 40, "MOM_MS": 500},
]

# Family 12 (the same struct at R1-F6's defaults): alloc_maker.py's knobs, then signal_maker.py's, each path once.
ALLOC = [
    {},
    {"ALLOC_K": -0.5},
    {"ALLOC_K": 0.8, "ALLOC_UP": 0, "ALLOC_DEEP": 0},
    {"INV_K": 0.5},
    {"ALLOC_K": -0.5, "ALLOC_KU": -0.2, "ALLOC_TH": 0.2, "ALLOC_HI": 1.3},
    {"ADV_TH": 0.6, "ADV_MIN": 50, "ADV_MS": 500},
    {"ADV_TH": 1.0, "ADV_MIN": 50, "ADV_MS": 2000, "ADV_SCOPE": 2},
]
SIGNAL = [
    {},
    {"MOM_LOTS": 40, "MOM_MS": 300, "MOM_BLOCK": 0, "MOM_JOIN": 1, "DYING_DEEP": 80, "DEPL_FRAC": 0.12},
    {"MOM_LOTS": 40, "MOM_MS": 500},
    {"MOM_LOTS": 30, "MOM_MS": 500, "MOM_SIZE": 10, "MOM_BLOCK": 0},
    {"IMB_TRIM": 0.5, "IMB_SIZE": 10},
    {"DYING_DEEP": 40, "DEPLETE_LOTS": 40, "DEPL_FRAC": 0.5},
    {"SIZE_SKEW": 0.6},
    {"SIZE_SKEW": 0.6, "SKEW_TRIM": 1},
]
# R1-F8 (candidates/r1_F8_take_join.py, the same struct at its own defaults): the take, the join, ANY_CLEAR, the
# follower-depth gates and SIZE_SKEW after ALLOC_K; the synthetic tape's touches hold 5-60 lots, so the gates come down.
TAKE = [
    {},
    {"TAKE_OWN": 0, "TAKE_DEPLETE": 40, "DEPL_FRAC": 0.5},
    {"TAKE_OWN": 0, "TAKE_DEPLETE": 0, "DEPLETE_LOTS": 40, "DEPL_FRAC": 0.5, "TAKE_MAX": 10, "TAKE_MS": 1000},
    {"TAKE_OWN": 10, "TAKE_DEPLETE": 40, "DEPL_FRAC": 0.5, "TAKE_RATIO": 0.5, "TAKE_LOTS": 30},
    {"MOM_LOTS": 40, "MOM_MS": 300, "MOM_JOIN": 0, "JOIN_OWN": 0, "JOIN_LOTS": 20, "JOIN_MS": 400},
    {"MOM_LOTS": 40, "MOM_MS": 300, "JOIN_OWN": 30},
    {"ANY_CLEAR": 1, "MOM_MS": 300, "JOIN_OWN": 20},
    {"SIZE_SKEW": 0.6, "ALLOC_K": -0.3, "ALLOC_UP": 0, "ALLOC_HI": 1.5},
]


@pytest.mark.parametrize("name, settings", [("room_maker", ROOM), ("shrink_maker", SHRINK), ("alloc_maker", ALLOC),
                                            ("signal_maker", SIGNAL), ("take_maker", TAKE)])
def test_room_maker_synthetic(tmp_path, name, settings):
    qsim_rust.build()
    tape = write_tape(tmp_path / "tape.csv")
    rust_runs = qsim_rust.run_batch(name, settings, [tape], threads=4)
    pnls = set()
    for overrides, [ours] in zip(settings, rust_runs):
        theirs = python_run(qsim_rust.STRATEGIES[name], overrides, tape)
        assert ours.get("error") is None, ours
        for key in FIELDS + ["rejected", "cancel_rejected"]:
            assert ours[key] == theirs[key], (overrides, key, ours[key], theirs[key])
        assert ours["curve"] == theirs["curve"], overrides
        pnls.add(theirs["pnl"])
    assert len(pnls) == len(settings), pnls  # every setting changes the run: its path is taken


ARENA_DATA = Path(os.environ.get("ARENA_SIM_DATA", ROOT / "data" / "arena"))
FULL = [  # (strategy, file, overrides, pnl, fills): F3 and knob settings on the real tapes (SESSION_S 1e9: round 1 never winds down)
    ("room_maker", "playground/sample_v2.csv", {}, "263282.00", 7764),
    ("room_maker", "playground/sample_v2.csv", {"LEVELS": 2, "SIZE_DEEP": 30, "KEEP_DEPTH": 2}, "220177.00", 8300),
    ("room_maker", "playground/sample_v2.csv", {"DEPLETE_LOTS": 30, "DEPLETE_SIZE": 40}, "264775.00", 8537),
    ("room_maker", "playground/sample_v2.csv", {"SIZE_NARROW": 150, "SHRINK_NARROW": 1}, "257145.00", 9467),
    ("room_maker", "playground/sample_v2.csv", {"UNWIND": 60, "UNWIND_TO": 30}, "45646.67", 19536),
    ("room_maker", "round1/round1.csv", {"SESSION_S": 1000000000}, "425553.00", 30452),
    ("room_maker", "round1/round1.csv", {"SESSION_S": 1000000000, "DEPLETE_LOTS": 20}, "399672.00", 26527),
    ("room_maker", "round1/round1.csv", {"SESSION_S": 1000000000, "BACK_POS": 95}, "425216.00", 29646),
    ("room_maker", "round1/round1.csv", {"SESSION_S": 5700, "FLAT_S": 30, "WIND_DOWN_S": 10}, "184793.35", 14353),
    # the shrink maker: R1-F5's settings (python/bots/qminers/candidates/r1_F5_shrink_react.py), then two others
    ("shrink_maker", "round1/round1.csv", {"SESSION_S": 1000000000, "DEPLETE_LOTS": 100, "DEPL_FRAC": 0.06, "REACT_CANCEL": 1}, "455822.00", 37847),
    ("shrink_maker", "round1/round1.csv", {"SESSION_S": 1000000000, "DEPLETE_LOTS": 60, "DEPL_FRAC": 0.2, "DEPLETE_SIZE": 30}, "437654.00", 32131),
    ("shrink_maker", "round1/round1.csv", {"SESSION_S": 1000000000, "REACT_CANCEL": 1, "SIZE_NARROW": 150, "SHRINK_NARROW": 1, "BACK_POS": 95},
     "393824.00", 53530),
    # family 12 at R1-F6's defaults: R1-F6b (candidates/r1_F6b_alloc.py) and R1-F7 (candidates/r1_F7_signal.py), two others each
    ("alloc_maker", "round1/round1.csv", {"ALLOC_K": -0.5}, "489844.00", 60487),
    ("alloc_maker", "round1/round1.csv", {"INV_K": 0.5, "ALLOC_K": -0.3, "ALLOC_UP": 0}, "486179.00", 54344),
    ("alloc_maker", "round1/round1.csv", {"ADV_TH": 0.0, "ADV_MIN": 200, "ADV_SCOPE": 2}, "482413.00", 49097),
    ("signal_maker", "round1/round1.csv", {"MOM_LOTS": 400, "MOM_MS": 50, "MOM_BLOCK": 0, "MOM_JOIN": 1, "DYING_DEEP": 80, "DEPL_FRAC": 0.12},
     "496564.00", 53919),
    ("signal_maker", "round1/round1.csv", {"MOM_LOTS": 300, "MOM_MS": 100, "MOM_SIZE": 20, "MOM_BLOCK": 0}, "473635.00", 53169),
    ("signal_maker", "round1/round1.csv", {"MOM_LOTS": 400, "MOM_MS": 200, "MOM_BLOCK": 1, "IMB_TRIM": 0.2, "IMB_SIZE": 10, "SIZE_SKEW": 0.5,
                                           "SKEW_TRIM": 1}, "378914.00", 57080),
    # R1-F8 (candidates/r1_F8_take_join.py) as written
    ("take_maker", "round1/round1.csv", {}, "519027.00", 66371),
    ("take_maker", "playground/sample_v2.csv", {}, "234661.00", 28134),
    # R1-C1 (candidates/r1_C1_codex_ridge.py) as written: ridge_maker.rs
    ("ridge_maker", "round1/round1.csv", {}, "554347.00", 37087),
]


@pytest.mark.skipif(os.environ.get("ARENA_SIM_FULL") != "1", reason="ARENA_SIM_FULL=1: about 30 s a Python run")
@pytest.mark.parametrize("name, file, overrides, pnl, fills", FULL)
def test_room_maker_full_byte_for_byte(tmp_path, name, file, overrides, pnl, fills):
    data = ARENA_DATA / file
    if not data.exists():
        pytest.skip(f"no {data}")
    qsim_rust.build()
    source = (ROOT / qsim_rust.STRATEGIES[name]).read_text()
    for key, value in overrides.items():
        source, n = re.subn(rf"^{key} = \S+", f"{key} = {value!r}", source, flags=re.M)
        assert n == 1, key
    bot = tmp_path / f"{name}.py"
    bot.write_text(source)
    theirs = subprocess.run([sys.executable, "-m", "simulator.main", "--strategy", str(bot), "--backtest", str(data),
                             "--log-dir", str(tmp_path / "py"), "--no-logs"], capture_output=True, text=True, check=True, cwd=ROOT)
    ours = subprocess.run([str(qsim_rust.BINARY), "--backtest", str(data), "--strategy", name, "--params", json.dumps(overrides),
                           "--log-dir", str(tmp_path / "rs")], capture_output=True, text=True, check=True)
    lines = [line for line in theirs.stdout.splitlines() if not line.startswith("log_dir=")]
    assert [line for line in ours.stdout.splitlines() if not line.startswith("log_dir=")] == lines
    assert f"pnl={pnl}" in lines and f"fills={fills}" in lines
    for name in ("result.json", "pnl.csv"):
        assert (tmp_path / "rs" / name).read_bytes() == (tmp_path / "py" / name).read_bytes(), name


# strategy_codex_best_v2_571k.py (the user's v2 of R1-C1, run by the Arena's simulator into logs/codex_v2_571k):
# ridge_maker with the v2 knobs on, every result line as v2's run printed it (its pnl.csv and result.json matched
# byte for byte, 2026-11-07)
V2 = {"POSITION_LIMIT": 1000, "EXPOSURE": 100, "CANCEL_FREE": 1.0, "HEDGE": 1}
V2_LINES = ["fills=24015", "traded_volume=2247040", "inventory=100", "cash=-429793.00", "breach_penalty=1869.75",
            "pnl=571237.25", "pnl_se=11199.08"]


def test_ridge_maker_v2(tmp_path):
    data = ARENA_DATA / "round1" / "round1.csv"
    if not data.exists():
        pytest.skip(f"no {data}")
    qsim_rust.build()
    ours = subprocess.run([str(qsim_rust.BINARY), "--backtest", str(data), "--strategy", "ridge_maker", "--params",
                           json.dumps(V2), "--log-dir", str(tmp_path / "rs")], capture_output=True, text=True, check=True)
    lines = ours.stdout.splitlines()
    for line in V2_LINES:
        assert line in lines


# The codex v4-v6 candidates (R1-C9..C12, each R1-C5 plus features): ridge_maker with C5's knobs and the feature
# knobs, every result line as each Python file's run printed it (pnl.csv and result.json matched byte for byte,
# 2026-11-07)
C5 = {**V2, "MODEL_MEMORY_US": 100000000000, "HORIZON_US": 400000, "DEAD_ZONE": 0.18}
CODEX = [
    ("C5", {}, "595441.83", 21120),
    ("C9", {"FLOWGRP": 1}, "605752.82", 21371),
    ("C10", {"FLOWGRP": 2, "FLOWGRP_CAP": 100}, "616534.83", 21436),
    ("C11", {"QUOTEFEAT": 1, "FLOWGRP": 2, "FLOWGRP_CAP": 1}, "619281.99", 21460),
    ("C12", {"QUOTEFEAT": 1, "FLOWGRP": 2, "FLOWGRP_CAP": 20, "FLOWGRP_US": 1000000}, "622920.99", 21462),
    # R2-Q1 (r2_Q1_keep_slice.py): C12 keeping a touch order's queue place, shrunk to 20 lots, on a step-back
    ("Q1", {"QUOTEFEAT": 1, "FLOWGRP": 2, "FLOWGRP_CAP": 20, "FLOWGRP_US": 1000000, "KEEP_LOTS": 20, "KEEP_TH": 0.3},
     "634748.99", 34167),
]


@pytest.mark.parametrize("name, knobs, pnl, fills", CODEX)
def test_ridge_maker_codex_features(tmp_path, name, knobs, pnl, fills):
    data = ARENA_DATA / "round1" / "round1.csv"
    if not data.exists():
        pytest.skip(f"no {data}")
    qsim_rust.build()
    ours = subprocess.run([str(qsim_rust.BINARY), "--backtest", str(data), "--strategy", "ridge_maker", "--params",
                           json.dumps({**C5, **knobs}), "--log-dir", str(tmp_path / "rs")], capture_output=True, text=True,
                          check=True)
    lines = ours.stdout.splitlines()
    assert f"pnl={pnl}" in lines and f"fills={fills}" in lines


# Round 2's forecast takers (R2-T2 -> L1 -> L3 / L8, L3 -> L9; each the step before plus knobs, all off by default):
# ridge_maker on round2_public.csv, every result line as each Python file's run printed it (pnl.csv and result.json
# matched byte for byte, 2026-11-08); with ARENA_SIM_FULL=1 the Python file runs too and the two are compared byte for
# byte (about 3 min a Python run). The --set line of each: ridge_maker.rs's doc comment, rust/README.md.
T2 = {"POSITION_LIMIT": 1000, "EXPOSURE": 100, "HEDGE": 1, "MODEL_MEMORY_US": 100000000000, "HORIZON_US": 400000,
      "DEAD_ZONE": 0.18, "QUOTEFEAT": 1, "FLOWGRP": 2, "FLOWGRP_CAP": 20, "FLOWGRP_US": 1000000, "FT_EDGE": 0.15,
      "FT_SZ": 200, "FT_GAP_MS": 50, "QUOTE_SIZE": 1, "KEEP_LOTS": 20, "KEEP_TH": 0.3, "FT_MAXSPREAD": 1,
      "FT_ROOM_LIVE": 1}
L1 = {**T2, "LIQ": 1}
L3 = {**L1, "QUOTE_SIZE": 0}
TAKERS = [
    ("r2_T2_take_only_safe.py", T2, "194391.00", 119403),
    ("r2_L1_taker_liquidity.py", L1, "269920.00", 117072),
    ("r2_L3_taker_pure.py", L3, "294098.00", 2492),
    ("r2_L8_quote_switch.py", {**L1, "QS_RATE": 2.5}, "296181.00", 75762),
    ("r2_L9_taker_huber.py", {**L3, "POSITION_LIMIT": 100, "IMPACT_US": 500000, "HUBER": 6.0, "RIDGE_MIN": 30,
                              "RIDGE_FRAC": 0.003}, "317057.00", 2803),
]


@pytest.mark.parametrize("bot, knobs, pnl, fills", TAKERS)
def test_ridge_maker_round2_takers(tmp_path, bot, knobs, pnl, fills):
    data = ARENA_DATA / "round2" / "round2_public.csv"
    if not data.exists():
        pytest.skip(f"no {data}")
    qsim_rust.build()
    ours = subprocess.run([str(qsim_rust.BINARY), "--backtest", str(data), "--strategy", "ridge_maker", "--params",
                           json.dumps(knobs), "--log-dir", str(tmp_path / "rs")], capture_output=True, text=True, check=True)
    lines = [line for line in ours.stdout.splitlines() if not line.startswith("log_dir=")]
    assert f"pnl={pnl}" in lines and f"fills={fills}" in lines
    if os.environ.get("ARENA_SIM_FULL") != "1":
        return
    theirs = subprocess.run([sys.executable, "-m", "simulator.main", "--strategy",
                             str(ROOT / "python" / "bots" / "qminers" / "candidates" / bot), "--backtest", str(data),
                             "--log-dir", str(tmp_path / "py"), "--no-logs"], capture_output=True, text=True, check=True, cwd=ROOT)
    assert [line for line in theirs.stdout.splitlines() if not line.startswith("log_dir=")] == lines
    for name in ("result.json", "pnl.csv"):
        assert (tmp_path / "rs" / name).read_bytes() == (tmp_path / "py" / name).read_bytes(), name


def test_grid_table(sample, capsys):
    assert qsim_rust.main(["fallback_maker", str(sample), "--grid", "QUOTE=3,5", "--grid", "LIMIT=30,50", "--threads", "2"]) == 0
    out = capsys.readouterr().out
    assert "out 25%" in out and "best by pnl" in out
    assert "-5,877" in out  # the baseline: F1 as written
