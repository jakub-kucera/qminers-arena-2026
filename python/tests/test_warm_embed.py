"""experiments.rounds.warm_embed: a RIDGE_DUMP file into r4_W1_warm.py's WARM START block, the values bit for bit."""

import ast
from pathlib import Path

import pytest

from experiments.rounds import warm_embed

ROOT = Path(__file__).parents[2]
BOT = ROOT / "python" / "bots" / "qminers" / "candidates" / "r4_W1_warm.py"
STATS = "M 0 2 254787.78489259825 263452\n1e-7 -0.1\n-0.1 1e16\n0.30000000000000004 -0.0\nM 1 1 3.0 3\n2.0\n5.0\n"


def constants(source: str) -> dict:
    return {n.targets[0].id: ast.literal_eval(n.value) for n in ast.parse(source).body
            if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id in
            ("PRIOR_MASS", "WARM_MASS", "WARM_XX", "WARM_XY")}


def test_embed_keeps_every_value_and_the_rest_of_the_bot(tmp_path):
    (tmp_path / "s.txt").write_text(STATS)
    out = tmp_path / "out.py"
    assert warm_embed.main([str(tmp_path / "s.txt"), str(BOT), str(out), "--prior-mass", "1000"]) == 0
    got = constants(out.read_text())
    assert got == {"PRIOR_MASS": 1000.0, "WARM_MASS": 254787.78489259825, "WARM_XX": ((1e-7, -0.1), (-0.1, 1e16)),
                   "WARM_XY": (0.30000000000000004, -0.0)}
    before, after = BOT.read_text().split(warm_embed.BEGIN), out.read_text().split(warm_embed.BEGIN)
    assert before[0] == after[0] and before[1].split(warm_embed.END)[1] == after[1].split(warm_embed.END)[1]


def test_the_bot_as_committed_is_off():
    assert constants(BOT.read_text())["PRIOR_MASS"] == 0.0


def test_a_non_finite_number_is_refused(tmp_path):
    (tmp_path / "s.txt").write_text("M 0 1 1.0 1\ninf\n1.0\n")
    with pytest.raises(ValueError):
        warm_embed.read_stats(tmp_path / "s.txt")
