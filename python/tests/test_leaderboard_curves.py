"""python/experiments/day/leaderboard_curves.py: the rule on curves whose case is known, the
leaderboard reader, and the calibration on a small field."""

import itertools
import json
import random
import sys

import pytest

from arena import sim
from experiments.day import leaderboard_curves as lc

T = 400


def walk(changes):
    return list(itertools.accumulate(changes, initial=0.0))


def noise(rng):
    return [rng.gauss(0, 1) for _ in range(T)]


def test_independent_curves_read_as_data_of_each_teams_own():
    rng = random.Random(1)
    r = lc.read_curves({f"t{k}": walk(noise(rng)) for k in range(8)})
    assert r.co_movement < lc.CO_MOVEMENT and r.verdict.startswith("alone, each on data of its own")


def test_curves_moved_by_one_common_driver_read_as_the_same_data():
    rng = random.Random(2)
    common = noise(rng)
    r = lc.read_curves({f"t{k}": walk([c + 0.8 * e for c, e in zip(common, noise(rng))]) for k in range(8)})
    assert r.mean > lc.MEAN and r.together > lc.SIGNS * r.against
    assert r.verdict == "alone, on the same data (co-movement of one sign)"


def test_curves_that_split_the_fills_read_as_one_shared_market():
    """Half the teams gain what the other half miss: strong pairs of both signs, a mean near 0."""
    rng = random.Random(3)
    flow = noise(rng)
    r = lc.read_curves({f"t{k}": walk([(1 if k % 2 else -1) * f + 0.8 * e for f, e in zip(flow, noise(rng))]) for k in range(8)})
    assert r.mean < lc.MEAN and r.co_movement > lc.CO_MOVEMENT and r.together > 0.3 and r.against > 0.4
    assert r.verdict == "one shared market (co-movement of both signs)"


def test_identical_moving_curves_mean_the_same_bot_alone_on_the_same_data_and_flat_ones_dont_count():
    rng = random.Random(4)
    curves = {f"t{k}": walk(noise(rng)) for k in range(5)} | {"copy": None, "idle": [0.0] * (T + 1), "idle 2": [0.0] * (T + 1)}
    curves["copy"] = list(curves["t0"])
    r = lc.read_curves(curves)
    assert r.teams == 6 and r.twins == [("t0", "copy")]
    assert r.verdict == "alone, on the same data (identical curves)"


def test_too_few_curves_or_points_say_so():
    rng = random.Random(5)
    assert lc.read_curves({"a": walk(noise(rng)), "b": walk(noise(rng))}).verdict.startswith("too few")
    assert lc.read_curves({k: walk(noise(rng)[:5]) for k in "abcd"}).verdict.startswith("too few")


def leaderboard(rng):
    """Five teams as the page receives them, on uneven elapsedS points; Gamma has no curve."""
    rows = []
    for k, name in enumerate(["Alpha", "Beta", "Delta", "Epsilon"]):
        pnl, points = 0.0, []
        for s in range(0, 600, 2 + k % 2):
            pnl += rng.gauss(10 - k, 30)
            points.append({"elapsedS": s, "pnl": pnl})
        rows.append({"teamId": f"id{k}", "teamName": name, "rank": None, "isTie": False, "pnl": pnl, "pnlSeries": points})
    rows.append({"teamId": "id9", "teamName": "Gamma", "rank": None, "isTie": False, "pnl": 0.0, "pnlSeries": []})
    for k, row in enumerate(sorted(rows, key=lambda r: -r["pnl"]), 1):
        row["rank"] = k
    return rows


def test_the_leaderboard_is_aligned_on_every_time_with_the_last_value_carried(tmp_path):
    path = tmp_path / "board.json"
    path.write_text(json.dumps({"rows": [
        {"teamName": "A", "rank": 1, "isTie": False, "pnl": 3, "pnlSeries": [{"elapsedS": 0, "pnl": 1}, {"elapsedS": 10, "pnl": 3}]},
        {"teamName": "B", "rank": 2, "isTie": True, "pnl": 2, "pnlSeries": [{"elapsedS": 5, "pnl": 2}]},
    ]}))
    teams = lc.load_leaderboard(path)
    assert [t.name for t in teams] == ["A", "B"] and teams[1].tie
    assert lc.aligned(teams) == {"A": [1.0, 1.0, 3.0], "B": [0.0, 2.0, 2.0]}


def test_the_total_clock_and_field_readings(tmp_path):
    teams = lc.load_leaderboard(_write_board(tmp_path, leaderboard(random.Random(7))))
    total = lc.read_total(teams)
    assert total.curves == 4 and total.verdict
    assert "total PnL across 4 curves" in lc.format_total(total) and "verdict:" in lc.format_total(total)
    clock = lc.read_clock(teams)
    assert clock.curves == 4 and clock.resets == 0 and not clock.common_grid
    assert "resets 0" in lc.format_clock(clock) and "different grids" in lc.format_clock(clock)
    field = lc.read_field(teams)
    assert field.teams == 5 and len(field.top) == 5 and "field: 5 teams" in lc.format_field(field)
    assert "third place" in lc.format_field(field) and "max drawdowns" in lc.format_field(field)


def test_a_zero_sum_total_is_flat_and_a_rising_one_is_not():
    flat = [lc.Team("A", 1, False, 10.0, [(0.0, 0.0), (10.0, 10.0)]),
            lc.Team("B", 2, False, -10.0, [(0.0, 0.0), (10.0, -10.0)])]
    assert lc.read_total(flat).end == 0.0 and lc.read_total(flat).verdict.startswith("about flat")
    rising = [lc.Team("A", 1, False, 10.0, [(0.0, 0.0), (10.0, 10.0)]),
              lc.Team("B", 2, False, 10.0, [(0.0, 0.0), (10.0, 10.0)])]
    assert lc.read_total(rising).end == 20.0 and lc.read_total(rising).verdict.startswith("the total rises")


def test_a_clock_that_goes_backwards_is_flagged():
    reset = lc.Team("R", 1, False, 0.0, [(0.0, 0.0), (10.0, 1.0)], [(0.0, 0.0), (10.0, 1.0), (0.0, 2.0)])
    clock = lc.read_clock([reset])
    assert clock.resets == 1 and "goes backwards" in clock.verdict and "resets 1" in lc.format_clock(clock)


def _write_board(tmp_path, rows):
    path = tmp_path / "leaderboard.json"
    path.write_text(json.dumps(rows))
    return path


def test_read_prints_the_standing_and_the_verdict(tmp_path, capsys, monkeypatch):
    path = tmp_path / "leaderboard.json"
    path.write_text(json.dumps(leaderboard(random.Random(6))))
    monkeypatch.setattr(sys, "argv", ["leaderboard_curves", "--read", str(path), "--team", "Delta"])
    lc.main()
    out = capsys.readouterr().out
    assert out.startswith("5 teams; PnL min") and "Delta: rank " in out and "of 5, PnL" in out
    assert "4 moving curves" in out and "verdict: alone, each on data of its own" in out
    monkeypatch.setattr(sys, "argv", ["leaderboard_curves", "--read", str(path), "--team", "Nobody"])
    with pytest.raises(SystemExit, match="no team named 'Nobody'"):
        lc.main()


def test_the_calibration_runs_on_a_small_field(tmp_path, capsys, monkeypatch):
    spec = sim.preset_market(ticks=300)
    for k in range(2):
        sim.write_day(sim.run(spec, 3000 + k), tmp_path / "prosperity", 1, k)
    mm = lc.MM, {"PARAMS": {p: {"make_edge": 1, "take_edge": 1, "hold": False} for p in ("KELP", "RAINFOREST_RESIN", "SQUID_INK")}}
    small = {"template": (lc.TEMPLATE, {}), "template copy": (lc.TEMPLATE, {}), "mm 1": mm, "mm 2": (lc.MM, {"PARAMS": {"KELP": {"make_edge": 2}}})}
    monkeypatch.setattr(lc, "fields", lambda: {"small 4": small})
    for name, value in {"DATA": str(tmp_path / "prosperity"), "DAYS": ["1"], "SEEDS": (0,), "STEPS": (10,), "TICKS": 300}.items():
        monkeypatch.setattr(lc, name, value)
    lc._days.cache_clear()
    monkeypatch.setattr(sys, "argv", ["leaderboard_curves", "--jobs", "2"])
    lc.main()
    lc._days.cache_clear()
    out = capsys.readouterr().out
    assert "replay on " in out and "(2 days), sim seeds 0" in out
    assert out.count("| replay, shared | small 4 |") == 2 and out.count("| sim, own seed | small 4 | 0 | 10 | 29 |") == 1
    assert "The rule named the case right in" in out
