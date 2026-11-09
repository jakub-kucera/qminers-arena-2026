"""python/experiments/rounds/standings.py: the scorings, the field read from the leaderboards, the
simulation's answers on fields whose answer is known, and the CLI on a synthetic field."""

import json

import pytest

from experiments.rounds import standings as st


def two_teams(lead: float, rounds: int = 1) -> st.Board:
    return st.Board(["us", "rival"], [[lead, 0.0]] + [[0.0, 0.0]] * (rounds - 1), [{} for _ in range(rounds)])


def field(median: float, sd: float, common: float = 0.0, loading=(1.0, 1.0)) -> st.Field:
    return st.Field(median, sd, 0.0, common, [0.0] * len(loading), list(loading))


def test_the_scorings_weigh_and_normalise_each_round():
    board = st.Board(["a", "b", "c"], [[10.0, -20.0, 5.0], [100.0, 50.0, 0.0]], [{}, {}])
    named = {s.name: s for s in st.scorings((0.1, 0.2, 0.3), names=("summed", "weighted", "max-weighted"))}
    assert st.totals(board, named["pnl summed"]) == [110.0, 30.0, 5.0]
    assert st.totals(board, named["pnl 10/20/30"]) == [21.0, 8.0, 0.5]
    score = st.totals(board, named["score 10/20/30"])  # round 1 over 20, round 2 over 100
    assert [round(x, 9) for x in score] == [0.25, 0.0, 0.025]
    assert st.rank_of([3.0, 5.0, 3.0], 0) == 2 and st.rank_of([3.0, 5.0, 3.0], 1) == 1


def test_the_real_rule_standardises_over_the_positive_teams_and_floors_a_loss_at_zero():
    # a team below zero and one at zero: out of the mean (20) and sd (10), each scored (0 - 20) / 10
    assert st.positive_z([30.0, 10.0, -5.0, 0.0]) == [1.0, -1.0, -2.0, -2.0]
    # every team but one positive: the loser doesn't drag the mean down (20, not 2.5)
    z = st.positive_z([-50.0, 10.0, 20.0, 30.0])
    sigma = (200 / 3) ** 0.5
    assert z == pytest.approx([-20 / sigma, -10 / sigma, 0.0, 10 / sigma])
    assert st.positive_z([-1e9, 10.0, 20.0, 30.0]) == z  # however large the loss
    # sd 0 (equal PnLs, or a single positive team) or no positive team: the round scores 0 for everyone
    assert st.positive_z([5.0, 5.0, 5.0]) == [0.0, 0.0, 0.0]
    assert st.positive_z([7.0, 7.0, -3.0]) == [0.0, 0.0, 0.0]
    assert st.positive_z([-5.0, 0.0, 40.0]) == [0.0, 0.0, 0.0]
    assert st.positive_z([-5.0, 0.0]) == [0.0, 0.0]


def test_the_real_rule_weighs_three_known_rounds_and_simulates_the_fourth():
    board = st.Board(["us", "a", "b"], [[30.0, 10.0, -5.0], [5.0, 5.0, 5.0], [-1.0, 20.0, 10.0]], [{}, {}, {}])
    (real,) = st.scorings((1.0, 1.0, 1.0))
    assert real.name == "real z 0.8/1/1" and real.weights == (0.8, 1.0, 1.0) and real.kind == "z"
    # round 1: mu 20, sd 10 -> 1, -1, -2; round 2: all equal -> 0; round 3: mu 15, sd 5 -> -3, 1, -1
    assert st.totals(board, real) == pytest.approx([0.8 - 3, -0.8 + 1, -1.6 - 1])
    with pytest.raises(ValueError, match="real rule has 4 weights"):
        st.scorings((1.0,) * 5)
    result = st.simulate(board, 0, (1_000.0, 0.0), field(100.0, 1.0, loading=(1.0, 1.0, 1.0)), sims=200)
    assert [s.name for s in result.scorings] == ["real z 0.8/1/1/1.2"] and result.now["real z 0.8/1/1/1.2"] == 2
    assert all(t.first == t.sims for t in result.risk.values())  # 1,000 against two ~100s: z +1.41 against -0.71, times 1.2, closes the 2.4 gap


def test_under_the_real_rule_a_bigger_loss_costs_nothing_more():
    board = st.Board(["us", "a", "b", "c"], [[10.0, 12.0, 8.0, 11.0]], [{}])
    rivals = field(100.0, 50.0, loading=(1.0, 1.0, 1.0, 1.0))
    small = st.simulate(board, 0, (-1.0, 0.0), rivals, sims=500, seed=2, names=("real", "summed"))
    huge = st.simulate(board, 0, (-1e6, 0.0), rivals, sims=500, seed=2, names=("real", "summed"))
    key = ("real z 0.8/1", 1.0)
    assert (small.risk[key].rank_sum, small.risk[key].first) == (huge.risk[key].rank_sum, huge.risk[key].first)
    assert small.risk[("pnl summed", 1.0)].rank_sum < huge.risk[("pnl summed", 1.0)].rank_sum


def test_a_lead_no_round_can_close_is_never_lost():
    result = st.simulate(two_teams(1_000.0), 0, (0.0, 0.0), field(0.0, 1.0), (1.0, 1.0), sims=500, names=("summed",))
    assert all(t.lost == 0 and t.first == t.sims for t in result.risk.values())
    assert result.now["pnl summed"] == 1 and result.gap["pnl summed"] == (1_000.0, 0.0)


def test_less_risk_protects_a_lead_and_more_risk_chases_one():
    # the same expected round for both teams; with the mean held (mean power 0) only our variance scales
    ahead = st.simulate(two_teams(10.0), 0, (5.0, 20.0), field(5.0, 1.0), (1.0, 1.0), multipliers=(0.25, 1.0, 1.5), sims=4_000, mean_power=0.0, names=("summed",))
    lost = {k: ahead.risk[("pnl summed", k)].lost for k in (0.25, 1.0, 1.5)}
    assert lost[0.25] < lost[1.0] < lost[1.5]
    behind = st.simulate(two_teams(-10.0), 0, (5.0, 20.0), field(5.0, 1.0), (1.0, 1.0), multipliers=(0.25, 1.0, 1.5), sims=4_000, mean_power=0.0, names=("summed",))
    first = {k: behind.risk[("pnl summed", k)].first for k in (0.25, 1.0, 1.5)}
    assert first[0.25] < first[1.0] < first[1.5]


def test_holding_the_fields_bet_keeps_a_place_when_the_rivals_all_hold_it():
    board = st.Board(["us", "a", "b", "c"], [[10.0, 0.0, 0.0, 0.0]], [{}])
    strong = st.simulate(board, 0, (0.0, 1.0), field(0.0, 10.0, common=0.9, loading=(0.0, 1.0, 1.0, 1.0)), (1.0, 1.0), hedges=(0.0, 0.5, 1.0),
                         sims=4_000, names=("summed",))
    lost = {h: strong.hedge[("pnl summed", h)].lost for h in (0.0, 0.5, 1.0)}
    assert lost[1.0] < lost[0.5] < lost[0.0]
    none = st.simulate(board, 0, (0.0, 1.0), field(0.0, 10.0, common=0.0, loading=(0.0, 1.0, 1.0, 1.0)), (1.0, 1.0), hedges=(0.0, 1.0), sims=500, names=("summed",))
    assert none.hedge[("pnl summed", 0.0)].lost == none.hedge[("pnl summed", 1.0)].lost  # no field's bet: nothing to hedge


def test_the_field_is_read_from_a_synthetic_field_whose_answer_is_known(tmp_path):
    boards = st.synthetic_rounds(teams=40, seed=3, common=0.5, rho=0.8)
    paths = []
    for r, rows in enumerate(boards, 1):
        paths.append(tmp_path / f"round{r}.json")
        paths[-1].write_text(json.dumps(rows))
    board = st.load_rounds(paths)
    assert board.teams[0] in {"us"} | {f"team{k:02d}" for k in range(40)} and len(board.teams) == 40 and len(board.pnl) == 3
    model = st.field_model(board)
    assert model.persistence > 0.4  # rho 0.8 between a team's rounds
    assert 0.2 < model.common < 0.8  # half of a team's variance
    assert abs(sum(model.loading) / len(model.loading) - 1) < 1e-9  # loadings average 1 by construction
    us = board.teams.index("us")
    assert abs(model.loading[us]) < 0.5  # ours is 0


def test_ours_from_numbers_a_file_and_a_grid_csv(tmp_path):
    assert st.read_ours("1,2.5,-3") == [1.0, 2.5, -3.0]
    numbers = tmp_path / "days.txt"
    numbers.write_text("10\n20, 30\n")
    assert st.read_ours(str(numbers)) == [10.0, 20.0, 30.0]
    grid = tmp_path / "grid.csv"
    grid.write_text("PARAMS.KELP.make_edge,pnl_all,min_day_all,nbhd_all,pnl_all_d1,pnl_all_d2,pnl_all_KELP,pnl_all_RESIN,fills\n"
                    "1,30,10,25,10,20,12,18,5\n"
                    "2,40,15,35,15,25,30,10,4\n")
    assert st.read_ours(str(grid)) == [15.0, 25.0]  # the best row's days, not its products
    assert st.read_ours(str(grid), ["PARAMS.KELP.make_edge=1"]) == [10.0, 20.0]
    assert st.our_round([1.0, 3.0], 4) == (8.0, 2 ** 0.5 * 2)


def test_the_cli_runs_on_a_synthetic_field(capsys):
    assert st.main(["--synthetic", "--sims", "300"]) == 0
    text = capsys.readouterr().out
    assert "30 teams, 3 rounds so far" in text and "risk multiplier k" in text and "relative hedge h" in text
    assert "real z 0.8/1/1/1.2" in text and "least chance of losing a place at k" in text and "pnl summed" not in text
    assert st.main(["--synthetic", "--sims", "100", "--scorings", "all"]) == 0
    text = capsys.readouterr().out
    assert all(name in text for name in ("real z 0.8/1/1/1.2", "pnl summed", "pnl 10/20/30/40", "score 10/20/30/40", "score equal"))
    with pytest.raises(SystemExit):
        st.main(["--synthetic", "--scorings", "real,ranked"])
    assert "unknown scorings" in capsys.readouterr().err


def test_proxy_growth_is_the_ratio_of_the_proxy_fields_spreads(data_dir):
    from pathlib import Path

    bots = [Path("python/bots/template.py"), Path("python/tests/fixtures/parity_bot.py")]
    assert st.proxy_growth((str(data_dir), ["1"]), (str(data_dir), ["1"]), bots) == pytest.approx(1.0)


def test_growth_from_on_another_format_asks_for_its_proxy_bots(capsys):
    with pytest.raises(SystemExit):
        st.main(["--synthetic", "--growth-from", "a:1", "b:2", "--format", "drill"])
    assert "needs --proxy-bots" in capsys.readouterr().err
