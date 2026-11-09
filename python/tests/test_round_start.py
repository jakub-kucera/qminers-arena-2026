"""experiments.rounds.round_start: the round's first look, end to end on a tiny synthetic backtest."""

import csv

from experiments.rounds import round_start
from test_qgrid import write_backtest


def test_round_start_end_to_end(tmp_path, capsys):
    data = write_backtest(tmp_path / "round.csv", seconds=120)
    out = tmp_path / "out"
    assert round_start.main([str(data), "--jobs", "1", "--candidates", "runner,A0", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "== profile" in printed and "trade (all)" in printed and "verdict" in printed
    assert "== candidates" in printed and "runner" in printed and "A0" in printed
    assert "uv run python -m arena.qgrid python/bots/qminers/families/momentum_runner.py" in printed
    assert "--holdout 0.25" in printed and "SESSION_S=120" in printed
    rows = list(csv.DictReader((out / "candidates.csv").open()))
    assert {r["candidate"] for r in rows} == {"runner", "A0"} and all(not r["error"] for r in rows)
    profile = {r["metric"]: r["value"] for r in csv.DictReader((out / "profile.csv").open())}
    assert int(profile["rows"]) == sum(1 for _ in data.open()) - 1
    assert float(profile["length_s"]) > 100
    assert (out / "markouts.csv").exists() and (out / "report.txt").read_text().startswith("== profile")


def test_session_overrides():
    assert round_start.candidate_overrides("runner", 3_599_000_003) == {"SESSION_S": 3600}
    over = round_start.candidate_overrides("A0", 3_599_000_003)
    assert over["SESSION_US"] == 3_599_000_003 and over["PARAMS.ASSET"]["limit"] == 50
