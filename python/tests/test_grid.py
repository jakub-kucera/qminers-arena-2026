import csv
import math
import random
import statistics
import textwrap
from types import SimpleNamespace

import pytest

from arena import grid, stats
from arena.engine import TradeMatching

# Buys `size` KELP at the 2032 ask on the first tick of each day; KELP is marked at 2030,
# so each day loses 2 per unit and the total over the two fixture days is -4 * size.
BOT = """
from datamodel import Order

PARAMS = {"size": 1, "unused": "x"}

class Trader:
    def run(self, state):
        if state.timestamp == 0:
            return {"KELP": [Order("KELP", 2032, PARAMS["size"])]}, 0, ""
        return {}, 0, ""
"""


@pytest.fixture
def bot(tmp_path):
    path = tmp_path / "bot.py"
    path.write_text(textwrap.dedent(BOT))
    return path


def run_main(capsys, bot, data_dir, *args):
    code = grid.main([str(bot), "1", "--data", str(data_dir), *args])
    return code, capsys.readouterr().out


@pytest.mark.parametrize(
    "text, values",
    [
        ("PARAMS.KELP.make_edge=1,2,3", [1, 2, 3]),
        ("PARAMS.KELP.make_edge=0..3", [0, 1, 2, 3]),
        ("PARAMS.KELP.smoothing=0..0.5..0.25", [0.0, 0.25, 0.5]),
        ("PARAMS.KELP.fair=mid,wall_mid", ["mid", "wall_mid"]),
        ("PARAMS.KELP.make_size=None,10", [None, 10]),
    ],
)
def test_parse_axis(text, values):
    axis = grid.parse_axis(text)
    assert axis.target == text.split("=")[0]
    assert axis.values == values


@pytest.mark.parametrize("text", ["PARAMS.X", "PARAMS.X=", "=1,2", "PARAMS.X=3..1", "PARAMS.X=1..a", "PARAMS.X=1,1"])
def test_parse_axis_rejects(text):
    with pytest.raises(ValueError):
        grid.parse_axis(text)


def test_neighborhood_mean_uses_one_step_along_each_axis():
    mode = TradeMatching.ALL
    outcomes = {}
    for i in range(3):
        for j in range(3):
            outcome = grid.Outcome((i, j), (i, j))
            outcome.day_pnl[mode] = {"d": float(10 * i + j)}
            outcomes[(i, j)] = outcome
    # (1, 1) = 11, neighbours 1, 21, 10, 12
    assert grid.neighborhood_mean(outcomes, (1, 1), (3, 3), mode) == pytest.approx((11 + 1 + 21 + 10 + 12) / 5)
    # corner (0, 0) = 0, neighbours 10 and 1
    assert grid.neighborhood_mean(outcomes, (0, 0), (3, 3), mode) == pytest.approx(11 / 3)


def _outcomes(day_pnls, failed=()):
    mode = TradeMatching.ALL
    outcomes = {}
    for i, pnls in enumerate(day_pnls):
        outcome = grid.Outcome((i,), (i,), limit_breaches=1 if i in failed else 0)
        outcome.day_pnl[mode] = dict(pnls)
        outcomes[(i,)] = outcome
    return outcomes


def test_each_day_is_scored_with_the_best_combination_on_the_other_days():
    # Combination 0 wins overall (5 against 4) only because of days d1 and d2.
    outcomes = _outcomes([{"d1": 10, "d2": 10, "d3": -15}, {"d1": 0, "d2": 0, "d3": 4}])
    picks = grid.leave_one_day_out(outcomes, TradeMatching.ALL)
    assert {day: pick.values for day, pick in picks.items()} == {"d1": (1,), "d2": (1,), "d3": (0,)}
    text = grid.format_held_out([grid.Axis("PARAMS.x", [0, 1])], [TradeMatching.ALL], outcomes, [(["d1", "d2"], ["X"])])
    assert "held out -15 against 5 for the best combination (-400%); 2 different settings chosen over 3 days" in text
    assert "! d1, d2 hold the same data for X" in text


def test_held_out_days_skip_failed_combinations_and_single_days():
    outcomes = _outcomes([{"d1": 9, "d2": 9}, {"d1": 1, "d2": 1}], failed={0})
    assert {pick.values for pick in grid.leave_one_day_out(outcomes, TradeMatching.ALL).values()} == {(1,)}
    assert grid.leave_one_day_out(_outcomes([{"d1": 1}]), TradeMatching.ALL) == {}


def test_repeated_days_are_found_per_product_without_counterparty_names():
    from arena.model import Book, Day, MarketTrade, Tick

    def day(name, buyer, price=100, extra=False):
        books = {"X": Book(((price - 1, 5),), ((price + 1, 5),))}
        if extra:  # a later round adds a product, but X's data is reused
            books["Y"] = Book(((50, 1),), ((52, 1),))
        tick = Tick(0, books, {"X": [MarketTrade("X", price, 2, buyer)]}, {})
        return Day(name, sorted(books), {p: 10 for p in books}, [tick])

    days = [day("a", ""), day("b", "Mark 22", extra=True), day("c", "", price=101)]
    assert grid.repeated_days(days) == [(["a", "b"], ["X"])]


@pytest.mark.parametrize("jobs", ["1", "2"])
def test_grid_ranks_combinations_and_writes_csv(capsys, bot, data_dir, tmp_path, jobs):
    out = tmp_path / "grid.csv"
    code, text = run_main(capsys, bot, data_dir, "--grid", "PARAMS.size=1..3", "--modes", "all,worse", "--jobs", jobs, "--out", str(out))
    assert code == 0
    assert "baseline (bot as is): pnl(all) -4" in text
    assert "best by pnl      size=1  (-4)" in text
    assert "all measures agree" in text
    assert "held out -4 against -4 for the best combination (+0%); 1 different settings chosen over 2 days" in text

    rows = list(csv.DictReader(out.open()))
    assert [row["PARAMS.size"] for row in rows] == ["1", "2", "3"]
    assert [float(row["pnl_all"]) for row in rows] == [-4, -8, -12]
    assert [float(row["nbhd_all"]) for row in rows] == [-6, -8, -10]
    assert float(rows[0]["pnl_worse_r1d0"]) == -2
    assert float(rows[2]["pnl_all_KELP"]) == -12


def test_typos_fail_before_the_grid_runs(capsys, tmp_path, data_dir):
    path = tmp_path / "bot.py"
    path.write_text(TEMPLATE_LIKE)
    with pytest.raises(SystemExit):
        grid.main([str(path), "1", "--data", str(data_dir), "--grid", "PARAMS.KELP.make_egde=1,2"])
    assert "unknown params for KELP: make_egde" in capsys.readouterr().err


def test_the_same_target_cant_be_set_twice(capsys, bot, data_dir):
    with pytest.raises(SystemExit):
        grid.main([str(bot), "1", "--data", str(data_dir), "--grid", "PARAMS.size=1,2", "--set", "PARAMS.size=3"])
    assert "set more than once" in capsys.readouterr().err


# A bot that validates its parameter names, like python/bots/template.py does.
TEMPLATE_LIKE = textwrap.dedent(
    """
    PARAMS = {"KELP": {"make_edge": 1}}

    class Trader:
        def run(self, state):
            unknown = set(PARAMS["KELP"]) - {"make_edge"}
            if unknown:
                raise ValueError(f"unknown params for KELP: {', '.join(sorted(unknown))}")
            return {}, 0, ""
    """
)


def test_grid_runs_against_rivals(capsys, bot, data_dir):
    code, text = run_main(capsys, bot, data_dir, "--grid", "PARAMS.size=1,2", "--vs", str(bot), "--jobs", "1")
    assert code == 0
    assert "each against bot#2 in the same market" in text


def test_neighbourhood_mean_leaves_out_failed_neighbours():
    outcomes = _outcomes([{"d": 10}, {"d": 20}, {"d": 900}], failed=(2,))
    assert grid.neighborhood_mean(outcomes, (1,), (3,), TradeMatching.ALL) == pytest.approx((20 + 10) / 2)


def test_grid_exits_1_when_every_combination_fails(capsys, data_dir, tmp_path):
    path = tmp_path / "bot.py"
    path.write_text(
        textwrap.dedent(
            """
            from datamodel import Order

            PARAMS = {"size": 1}

            class Trader:
                def run(self, state):
                    return {"KELP": [Order("KELP", 1, 1000 * PARAMS["size"])]}, 0, ""
            """
        )
    )
    code, text = run_main(capsys, path, data_dir, "--grid", "PARAMS.size=1,2", "--jobs", "1")
    assert code == 1 and "every combination failed" in text


def test_blocks_are_an_even_number_over_the_days_and_sum_to_the_day():
    assert [grid.blocks_per_day(days) for days in (1, 2, 3, 6, 7)] == [16, 8, 6, 3, 4]
    assert grid.block_pnl([1, 2, 3, 4, 5, 6], 3) == [2, 2, 2]
    assert sum(grid.block_pnl([0, -1, 4, 2, 7], 2)) == 7
    assert grid.block_pnl([1, 2], 3) == []


def test_cscv_finds_no_information_in_noise_and_finds_a_planted_edge():
    import random

    def matrix(seed, edge):
        rng = random.Random(seed)
        columns = [[rng.gauss(0, 1) for _ in range(12)] for _ in range(20)]
        columns[3] = [x + edge for x in columns[3]]
        return columns

    noise = [grid.cscv(matrix(seed, 0)) for seed in range(10)]
    assert 0.35 < sum(r.pbo for r in noise) / 10 < 0.65  # the pick is a coin flip out of sample
    assert 0.4 < sum(r.rank for r in noise) / 10 < 0.6
    planted = [grid.cscv(matrix(seed, 1.5)) for seed in range(10)]
    assert sum(r.pbo for r in planted) / 10 < 0.1
    assert planted[0].splits == planted[0].of == 924  # C(12, 6), all of them


def test_cscv_samples_the_halvings_when_there_are_many():
    columns = [[float(i == j) for i in range(20)] for j in range(3)]
    result = grid.cscv(columns, max_splits=500)
    assert (result.splits, result.of) == (500, 184_756)


def test_deflated_sharpe_ratio_reproduces_the_papers_example():
    # Bailey and Lopez de Prado, p. 9-10: annualised SR 2.5 over 1,250 days, 100 trials with an
    # annualised SR variance of 1/2, skew -3, kurtosis 10: SR0 0.1132 a day, DSR 0.9004.
    sharpe = 2.5 / 250**0.5
    sharpe0 = grid.expected_max_sharpe(0.5 / 250, 100)
    assert sharpe0 == pytest.approx(0.1132, abs=1e-4)
    assert grid.deflated_sharpe(sharpe, sharpe0, 1250, -3, 10) == pytest.approx(0.9004, abs=1e-4)
    assert grid.deflated_sharpe(sharpe, grid.expected_max_sharpe(0.5 / 250, 46), 1250, -3, 10) == pytest.approx(0.9505, abs=1e-4)
    assert grid.expected_max_sharpe(1.0, 1) == 0.0


def test_independent_trials_discount_correlated_cells():
    assert grid.independent_trials([[1, 2, 3], [2, 4, 6], [3, 6, 9]]) == pytest.approx(1)
    assert grid.independent_trials([[1, -1, 1, -1], [1, 1, -1, -1]]) == pytest.approx(2)
    assert grid.independent_trials([[1, 1, 1], [1, 2, 3]]) == 2  # a constant cell has no correlation


def test_grid_reports_trials_and_overfitting(capsys, bot, data_dir):
    code, text = run_main(capsys, bot, data_dir, "--grid", "PARAMS.size=1..3", "--modes", "all,worse")
    assert code == 0
    assert "overfitting: 3 cells × 2 modes = 6 trials on 2 days" in text


def test_omega_is_the_plain_variance_without_blocks():
    d = [1.0, -2.0, 0.5, 3.0, -1.0]
    assert grid.omega2(d, 1.0) == pytest.approx(statistics.pvariance(d))


def _gains(seed, cells, n, edge=0.0, planted=3):
    rng = random.Random(seed)
    columns = [[rng.gauss(0, 1) for _ in range(n)] for _ in range(cells)]
    columns[planted] = [x + edge for x in columns[planted]]
    return columns


def test_spa_and_stepm_find_no_edge_in_noise_and_find_a_planted_one():
    nulls = [grid.snooping(_gains(seed, 15, 120), 0.1, 200, seed=seed) for seed in range(10)]
    assert 0.2 < statistics.fmean(p["c"] for p, _ in nulls) < 0.8
    assert all(p["l"] <= p["c"] <= p["u"] for p, _ in nulls)
    assert sum(len(winners) for _, winners in nulls) <= 1  # with the original's omega in every resample: 4
    for studentize in stats.STUDENTIZE:
        p, winners = grid.snooping(_gains(0, 15, 120, edge=0.5), 0.1, 200, studentize=studentize)
        assert p["c"] < 0.01
        assert winners == [3]


def test_each_resample_is_studentized_by_its_own_omega():
    d = _gains(4, 4, 40)
    means, scales = stats.bootstrap(d, 0.1, 20, 7)
    assert means == stats.bootstrap_means(d, 0.1, 20, 7)
    for idx, row in zip(stats.resamples(40, 0.1, 20, 7), scales):
        assert row == [math.sqrt(stats.omega2([column[i] for i in idx], 0.1)) for column in d]
    with pytest.raises(ValueError, match="studentize"):
        stats.stepm(d, 0.1, 20, studentize="mixed")


def test_spa_is_not_hidden_by_poor_cells():
    # Hansen's point: adding clearly worse cells shouldn't sink a real gain under the consistent p.
    good = _gains(1, 5, 200, edge=0.2, planted=0)
    poor = [[x - 1.0 for x in column] for column in _gains(2, 40, 200)]
    with_poor = grid.spa(good + poor, 0.1, 300)
    assert with_poor["c"] <= grid.spa(good, 0.1, 300)["c"] + 0.02
    assert with_poor["c"] <= with_poor["u"]


def _outcome(index, fine, pnl):
    o = grid.Outcome(index, index)
    for mode, value in pnl.items():
        o.fine_pnl[mode] = fine
        o.day_pnl[mode] = {"d": value}
    return o


def test_snooping_names_the_cells_and_checks_them_under_the_other_modes():
    all_, worse = TradeMatching.ALL, TradeMatching.WORSE
    axes = [grid.Axis("PARAMS.edge", [0, 1, 2])]
    columns = _gains(3, 3, 100, edge=0.5, planted=1)
    baseline = _outcome((), [0.0] * 100, {all_: 0.0, worse: 0.0})
    outcomes = {(k,): _outcome((k,), columns[k], {all_: sum(columns[k]), worse: -1.0}) for k in range(3)}
    text = grid.format_snooping(axes, baseline, outcomes, [all_, worse], dsr=0.5)
    assert "100 blocks of 100 ticks, 3 distinct cells" in text
    assert "StepM at 4%: 1 cells beat the bot as is: edge=1" in text
    assert "SPA finds a gain the DSR doesn't" in text
    assert "under worse: 0 of StepM's 1 cells beat the bot as is" in text
    assert "only beat the bot as is under all" in text
    assert "pick: the bot as is" in text
    outcomes[(1,)].day_pnl[worse] = {"d": 1.0}
    text = grid.format_snooping(axes, baseline, outcomes, [all_, worse], dsr=0.5)
    assert "pick: edge=1 (all +" in text and "worse +1)" in text


def test_gate_first_lets_the_first_mode_decide():
    all_, worse = TradeMatching.ALL, TradeMatching.WORSE
    axes = [grid.Axis("PARAMS.edge", [0, 1, 2])]
    columns = _gains(3, 3, 100, edge=0.5, planted=1)
    baseline = _outcome((), [0.0] * 100, {all_: 0.0, worse: 0.0})
    outcomes = {(k,): _outcome((k,), columns[k], {all_: sum(columns[k]), worse: -1.0}) for k in range(3)}
    text = grid.format_snooping(axes, baseline, outcomes, [all_, worse], dsr=0.5, gate="first")
    assert "under worse: 0 of StepM's 1 cells" in text  # still shown, as a column to read
    assert "pick: edge=1 (all +" in text and "worse -1)" in text and "--gate first" in text


def test_parse_holdout():
    days = [SimpleNamespace(name=name) for name in ("r1d0", "r1d1")]
    assert grid.parse_holdout("last", days) == ("day r1d1", 1)
    assert grid.parse_holdout("r1d0", days) == ("day r1d0", 0)
    assert grid.parse_holdout("25%", days) == ("the last 25% of the data", 0.25)
    assert grid.parse_holdout("0.1", days)[1] == 0.1
    for bad in ("r9", "0", "100%", "1.5"):
        with pytest.raises(ValueError, match="--holdout"):
            grid.parse_holdout(bad, days)
    with pytest.raises(ValueError, match="two or more days"):
        grid.parse_holdout("last", days[:1])


def test_a_held_out_share_splits_the_fine_blocks():
    all_ = TradeMatching.ALL
    o = _outcome((0,), [1.0] * 6 + [-1.0] * 2, {all_: 4.0})
    kept, held = grid.split_holdout(o, [], 0.25)
    assert list(kept.fine_pnl[all_]) == [1.0] * 6 and kept.pnl(all_) == 6.0
    assert list(held.fine_pnl[all_]) == [-1.0] * 2 and held.pnl(all_) == -2.0


def test_the_pick_must_also_win_on_the_held_out_data():
    all_ = TradeMatching.ALL
    axes = [grid.Axis("PARAMS.edge", [0, 1, 2])]
    columns = _gains(3, 3, 100, edge=0.5, planted=1)
    baseline = _outcome((), [0.0] * 120, {all_: 0.0})
    # cell 1 wins on the first 100 blocks; on the last 20 (held out) it either keeps winning or loses
    for tail, kept in ((1.0, True), (-1.0, False)):
        outcomes = {(k,): _outcome((k,), columns[k] + [tail if k == 1 else 0.0] * 20, {all_: 0.0}) for k in range(3)}
        text = grid.format_holdout(axes, baseline, outcomes, [all_], [], ("the last 20 blocks", 20 / 120))
        assert "StepM at 4%: 1 cells beat the bot as is: edge=1" in text
        assert ("pick, held out: edge=1: it also beats" in text) is kept
        assert ("pick, held out: the bot as is: edge=1 doesn't beat it" in text) is not kept


def test_snooping_skips_short_days(capsys, bot, data_dir):
    code, text = run_main(capsys, bot, data_dir, "--grid", "PARAMS.size=1..3")
    assert "SPA, StepM: skipped" in text


def test_grid_runs_a_permutation_test(capsys, bot, data_dir):
    code, text = run_main(capsys, bot, data_dir, "--grid", "PARAMS.size=1..3", "--permute", "3", "--jobs", "1")
    assert code == 0
    assert "permutation test: the whole grid on 3 copies of the days, their ticks shuffled in runs of 1" in text
    assert "best cell's PnL:" in text and "lift of the best cell over the median one:" in text
    assert "(smallest possible 0.250)" in text


def test_axis_products_are_the_products_the_axes_set():
    axes = [grid.Axis("PARAMS.KELP.make_edge", [1]), grid.Axis("PARAMS.KELP.take_edge", [1])]
    assert grid.axis_products(axes, ["KELP", "RESIN"]) == ["KELP"]
    assert grid.axis_products([grid.Axis("PARAMS.size", [1])], ["KELP", "RESIN"]) == ["KELP", "RESIN"]
    # an axis that can tie a product to another runs on full days: the restricted check saw only the bot as is
    assert grid.axis_products([grid.Axis("PARAMS.KELP.follow", [None, "RESIN"])], ["KELP", "RESIN"]) == ["KELP", "RESIN"]
    assert grid.axis_products([grid.Axis("DEFAULTS.make_edge", [1])], ["KELP"]) == ["KELP"]


def test_permute_needs_sensible_arguments(capsys, bot, data_dir):
    with pytest.raises(SystemExit):
        run_main(capsys, bot, data_dir, "--grid", "PARAMS.size=1,2", "--permute-block", "0")


TWO_PRODUCTS = """
from datamodel import Order

PARAMS = {"KELP": {"size": 1}, "RAINFOREST_RESIN": {"size": 1}}
PRICES = {"KELP": 2032, "RAINFOREST_RESIN": 10004}

class Trader:
    def run(self, state):
        if state.timestamp != 0 and state.timestamp != 100:
            return {}, 0, ""
        orders = {}
        for product, params in PARAMS.items():
            depth = state.order_depths.get(product)
            if depth and (not DEPENDENT or "RAINFOREST_RESIN" in state.order_depths):
                orders[product] = [Order(product, PRICES[product] if state.timestamp == 0 else PRICES[product] - 4, params["size"])]
        return orders, 0, ""
"""


def _two_product_bot(tmp_path, dependent):
    path = tmp_path / f"two_{dependent}.py"
    path.write_text(textwrap.dedent(TWO_PRODUCTS) + f"\nDEPENDENT = {dependent}\n")
    return path


def _summary(text):
    return [line for line in text.splitlines() if "done in" not in line and "workers" not in line]


def test_a_grid_on_one_product_runs_it_alone_and_adds_the_others_back(capsys, tmp_path, data_dir):
    bot = _two_product_bot(tmp_path, False)
    code, restricted = run_main(capsys, bot, data_dir, "--grid", "PARAMS.KELP.size=1..3", "--modes", "all,worse", "--jobs", "1")
    assert code == 0 and "the combinations ran on KELP only" in restricted
    _, full = run_main(capsys, bot, data_dir, "--grid", "PARAMS.KELP.size=1..3", "--modes", "all,worse", "--jobs", "1", "--all-products")
    assert "ran on KELP only" not in full
    assert _summary(restricted) == _summary(full)


def test_a_grid_runs_every_product_when_the_bot_as_is_needs_them(capsys, tmp_path, data_dir):
    bot = _two_product_bot(tmp_path, True)
    code, text = run_main(capsys, bot, data_dir, "--grid", "PARAMS.KELP.size=1..3", "--jobs", "1")
    assert code == 0 and "the combinations ran on every product" in text


def test_the_grid_gives_the_same_summary_on_one_worker_and_on_several(capsys, tmp_path, data_dir):
    bot = _two_product_bot(tmp_path, False)
    args = ["--grid", "PARAMS.KELP.size=1..3", "--grid", "PARAMS.RAINFOREST_RESIN.size=1,2", "--modes", "all,worse"]
    _, serial = run_main(capsys, bot, data_dir, *args, "--jobs", "1")
    _, parallel = run_main(capsys, bot, data_dir, *args, "--jobs", "3")
    assert _summary(serial) == _summary(parallel)


def _csv_rows(path):
    with path.open() as file:
        return {row["PARAMS.size"]: row for row in csv.DictReader(file)}


def test_the_screen_keeps_the_best_share_with_the_full_runs_numbers(capsys, bot, data_dir, tmp_path):
    args = ["--grid", "PARAMS.size=1..4", "--modes", "all,worse", "--jobs", "1"]
    code, text = run_main(capsys, bot, data_dir, *args, "--screen", "0.5", "--out", str(tmp_path / "screened.csv"))
    assert code == 0
    assert "4 combinations screened on" in text and "the best 2 then × 2 days × 2 modes (14 backtests)" in text
    assert "screen: all 4 cells on" in text and "the best 2 (50%) kept" in text and "best dropped size=3" in text
    assert "on the days the screen didn't see" in text
    run_main(capsys, bot, data_dir, *args, "--out", str(tmp_path / "full.csv"))
    screened, full = _csv_rows(tmp_path / "screened.csv"), _csv_rows(tmp_path / "full.csv")
    assert list(screened) == ["1", "2"]  # the bot loses 4 per unit: the smallest sizes are best
    same = lambda row: {c: v for c, v in row.items() if not c.startswith("nbhd")}  # nbhd only sees the kept neighbours
    assert all(same(screened[k]) == same(full[k]) for k in screened)


def test_screened_puts_failed_cells_last_and_keeps_at_least_one():
    piece = lambda pnl, errors=0: grid.Piece(pnl, [], [], {}, 0, errors, 0, "")
    cells = [((0,), (0,)), ((1,), (1,)), ((2,), (2,))]
    found = {(0,): piece(5.0, errors=1), (1,): piece(1.0), (2,): piece(3.0)}
    kept, pnl, failed = grid.screened(cells, found, 0.6)
    assert [index for index, _ in kept] == [(2,), (1,)] and failed == {(0,)} and pnl[(0,)] == 5.0
    assert len(grid.screened(cells, found, 0.01)[0]) == 1


def test_neighbourhood_mean_skips_cells_the_screen_dropped():
    made = _outcomes([[("d", 1.0)], [("d", 2.0)], [("d", 3.0)]])
    outcomes = {(0,): made[(0,)], (2,): made[(2,)]}  # (1,) was dropped
    assert grid.neighborhood_mean(outcomes, (0,), (3,), TradeMatching.ALL) == 1.0


def test_the_screen_works_with_the_permutation_test_and_rejects_a_bad_share(capsys, bot, data_dir):
    code, text = run_main(capsys, bot, data_dir, "--grid", "PARAMS.size=1..4", "--screen", "0.5", "--permute", "2", "--jobs", "1")
    assert code == 0 and "permutation test: the whole grid on 2 copies" in text
    for share in ("0", "1", "1.5"):
        with pytest.raises(SystemExit):
            run_main(capsys, bot, data_dir, "--grid", "PARAMS.size=1,2", "--screen", share)


def test_a_sample_draws_distinct_cells_by_their_place_in_the_whole_grid():
    import itertools
    sizes = [3, 4, 5]
    assert [grid._unrank(k, sizes) for k in range(60)] == list(itertools.product(range(3), range(4), range(5)))
    axes = [grid.Axis(f"PARAMS.{n}", tuple(range(size))) for n, size in zip("abc", sizes)]
    sample = grid._cells(axes, 7, seed=3)
    assert len({index for index, _ in sample}) == 7 and sample == sorted(sample) and sample == grid._cells(axes, 7, seed=3)
    assert set(sample) <= set(grid._cells(axes)) and sample != grid._cells(axes, 7, seed=4)
    assert grid._cells(axes, 1000) == grid._cells(axes)


def test_the_cli_samples_the_grid(capsys, bot, data_dir):
    code, text = run_main(capsys, bot, data_dir, "--grid", "PARAMS.size=1..4", "--sample", "2", "--jobs", "1")
    assert code == 0 and "2 of 4 combinations, drawn at random (--sample-seed 0)" in text and "2 combinations × 2 days" in text


def test_halving_keeps_a_share_at_each_step_with_the_full_runs_numbers(capsys, bot, data_dir, tmp_path):
    args = ["--grid", "PARAMS.size=1..4", "--modes", "all,worse", "--jobs", "1"]
    code, text = run_main(capsys, bot, data_dir, *args, "--halving", "0.5", "--out", str(tmp_path / "halved.csv"))
    assert code == 0
    assert "4 combinations, one day under one mode at a time (4 steps), keeping 50% after each but the last: 1 at the end (12 backtests)" in text
    assert "halving: 4 cells, keeping 50% at each of 2 steps" in text
    assert "1. through r1d-1 under all: 4 cells, kept 2; best dropped size=3 (-6)" in text  # each day loses 2 per unit
    assert "2. through r1d0 under all: 2 cells, kept 1; best dropped size=2 (-8)" in text
    assert "! every day was ranked on by a halving step" in text  # both days, under all
    run_main(capsys, bot, data_dir, *args, "--out", str(tmp_path / "full.csv"))
    halved, full = _csv_rows(tmp_path / "halved.csv"), _csv_rows(tmp_path / "full.csv")
    same = lambda row: {c: v for c, v in row.items() if not c.startswith("nbhd")}
    assert list(halved) == ["1"] and same(halved["1"]) == same(full["1"])
    # Under one mode the last step ranks the first day only, so the second stays unseen.
    _, text = run_main(capsys, bot, data_dir, "--grid", "PARAMS.size=1..4", "--halving", "0.5", "--jobs", "1")
    assert "on the days the halving didn't see (r1d0), so free of its choice:" in text


def test_halving_rejects_a_bad_share_a_screen_and_a_permutation_test(capsys, bot, data_dir):
    for extra in (["--halving", "1"], ["--halving", "0.5", "--screen", "0.5"], ["--halving", "0.5", "--permute", "2"], ["--sample", "0"]):
        with pytest.raises(SystemExit):
            run_main(capsys, bot, data_dir, "--grid", "PARAMS.size=1,2", *extra)


def test_search_runs_its_budget_from_the_bot_as_is_and_reports_its_best(capsys, bot, data_dir, tmp_path):
    # size loses 2 a unit a day; the bot's own size (1) isn't on the axis, so coord starts mid-axis (6)
    args = ["--grid", "PARAMS.size=2..9", "--grid", "PARAMS.unused=x,y,z", "--modes", "all,worse", "--jobs", "1"]
    code, text = run_main(capsys, bot, data_dir, *args, "--search", "coord", "--budget", "12", "--out", str(tmp_path / "coord.csv"))
    assert code == 0 and "coord search: at most 12 of 24 combinations (50.00%) × 2 days × 2 modes (52 backtests at most)" in text
    assert "search: coordinate descent from size=6, unused=x (seed 0), 12 of 24 cells" in text
    assert "maximising the smaller gain over the bot as is under all, worse" in text
    assert ": size=2, unused=" in text.split("its best, found at cell")[1].splitlines()[0]
    assert "! the tests below see the 12 cells the search ran" in text
    assert len(list(csv.DictReader(open(tmp_path / "coord.csv")))) == 12
    for method in ("coord", "tpe"):  # the reported best is the best of the cells it ran, by its objective
        _, text = run_main(capsys, bot, data_dir, *args, "--search", method, "--budget", "6", "--search-seed", "3", "--out", str(tmp_path / "s.csv"))
        rows = list(csv.DictReader(open(tmp_path / "s.csv")))
        best = max(rows, key=lambda r: min(float(r["pnl_all"]), float(r["pnl_worse"])))
        assert len(rows) == 6 and f"size={best['PARAMS.size']}, unused={best['PARAMS.unused']}" in text.split("its best")[1].splitlines()[0]
    _, text = run_main(capsys, bot, data_dir, "--grid", "PARAMS.size=0..3", "--jobs", "1", "--search", "coord", "--budget", "2")
    assert "coordinate descent from size=1 (seed 0)" in text  # the bot's own value, on the axis


def test_the_search_objective_leaves_out_the_held_out_data_and_failed_cells():
    piece = lambda pnl, fine=(), errors=0: SimpleNamespace(pnl=pnl, fine=list(fine), errors=errors, breaches=0)
    keys = [(0, TradeMatching.ALL), (1, TradeMatching.ALL), (0, TradeMatching.WORSE), (1, TradeMatching.WORSE)]
    base = {k: piece(0.0, [0.0, 0.0]) for k in keys}
    modes = [TradeMatching.ALL, TradeMatching.WORSE]
    cell = [piece(5, [2, 3]), piece(100, [0, 100]), piece(4, [1, 3]), piece(-50, [0, -50])]
    whole, text = grid.search_objective(keys, base, modes, "every", None)
    assert whole(cell) == -46 and text == "the smaller gain over the bot as is under all, worse"
    day, text = grid.search_objective(keys, base, modes, "every", ("day r1d0", 1))
    assert day(cell) == 4 and text.endswith(", without day r1d0")
    share, _ = grid.search_objective(keys, base, modes, "every", ("the last 25% of the data", 0.25))
    assert share(cell) == 4  # the last of four blocks a mode held out: 2 + 3 + 0 under all, 1 + 3 + 0 under worse
    first, text = grid.search_objective(keys, base, modes, "first", None)
    assert first(cell) == 105 and text == "the gain over the bot as is under all"
    assert whole([*cell[:3], piece(-50, errors=1)]) == -math.inf


def test_search_needs_a_budget_and_no_other_screen(capsys, bot, data_dir):
    for extra in (["--search", "coord"], ["--search", "tpe", "--budget", "0"], ["--budget", "5"], ["--search", "tpe", "--budget", "5", "--halving", "0.5"],
                  ["--search", "tpe", "--budget", "5", "--screen", "0.5"], ["--search", "tpe", "--budget", "5", "--sample", "2"],
                  ["--search", "tpe", "--budget", "5", "--permute", "2"], ["--search", "anneal", "--budget", "5"]):
        with pytest.raises(SystemExit):
            run_main(capsys, bot, data_dir, "--grid", "PARAMS.size=1,2", *extra)


def test_without_days_drops_the_days_pnl_and_fine_blocks():
    day = lambda name, ticks: SimpleNamespace(name=name, ticks=[None] * ticks)
    days = [day("a", 200), day("b", 300), day("c", 100)]
    outcome = grid.Outcome((), (), day_pnl={TradeMatching.ALL: {"a": 1.0, "b": 2.0, "c": 3.0}}, fine_pnl={TradeMatching.ALL: [1, 2, 3, 4, 5, 6]})
    trimmed = grid.without_days(outcome, days, {1})
    assert trimmed.day_pnl[TradeMatching.ALL] == {"a": 1.0, "c": 3.0} and trimmed.fine_pnl[TradeMatching.ALL] == [1, 2, 6]
    assert grid.without_days(outcome, days, {0}).fine_pnl[TradeMatching.ALL] == [3, 4, 5, 6]


def test_an_axis_that_never_changes_the_pnl_is_flagged(capsys, bot, data_dir):
    # `unused` is read by nothing, and `--set` accepts a new leaf such as `typo`: both axes are dead.
    code, text = run_main(capsys, bot, data_dir, "--grid", "PARAMS.size=1..2", "--grid", "PARAMS.unused=a,b", "--grid", "PARAMS.typo=1,2",
                          "--jobs", "1")
    assert code == 0
    assert "! unused never changed the PnL" in text and "! typo never changed the PnL" in text
    assert "! size never changed" not in text


def test_a_best_cell_on_an_axis_end_is_flagged_with_a_finer_grid_around_it():
    mode = TradeMatching.ALL
    axes = [grid.Axis("PARAMS.KELP.make_edge", [0.5, 1, 2]), grid.Axis("PARAMS.KELP.size", [0, 10, 20]), grid.Axis("PARAMS.KELP.fair", ["mid", "wall_mid"])]
    row = lambda values, pnl, failed=False: grid.Row(values, {mode: pnl}, pnl, pnl, 0, failed, pnl)
    rows = [row((1, 20, "mid"), 30.0), row((2, 10, "mid"), 20.0), row((0.5, 0, "wall_mid"), 99.0, failed=True)]
    text = grid.format_axis_ends(axes, [mode], rows, "pnl")
    assert "! the best cell by pnl has KELP.size=20, the axis' highest value" in text
    assert "make_edge=1" not in text.split("\n")[0] and text.count("\n! ") == 0  # make_edge=1 is inside its axis; the failed cell isn't the best
    assert text.endswith("--grid PARAMS.KELP.make_edge=0.5..2..0.25 --grid PARAMS.KELP.size=10..20..5 --set PARAMS.KELP.fair=mid")
    assert grid.parse_axis("PARAMS.KELP.make_edge=0.5..2..0.25").values == [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]
    assert "below a step of 1" not in text  # 10..20..5 stays whole
    steps = [grid.Axis("PARAMS.KELP.take_edge", [0, 1, 2])]  # whole numbers a step apart: halved, with the caveat, and no note inside the axis
    finer, caveat = grid.format_axis_ends(steps, [mode], [row((1,), 1.0)], "pnl").split("\n")
    assert finer.endswith("--grid PARAMS.KELP.take_edge=0..2..0.5") and caveat.startswith("  (KELP.take_edge below a step of 1: only if")
    assert grid.format_axis_ends(axes, [mode], [row((1, 20, "mid"), 1.0, failed=True)], "pnl") == ""


def test_the_grid_writes_the_pnl_paths_measures_and_sorts_by_them(capsys, bot, data_dir, tmp_path):
    out = tmp_path / "grid.csv"
    code, text = run_main(capsys, bot, data_dir, "--grid", "PARAMS.size=1..3", "--sort", "drawdown", "--out", str(out))
    assert code == 0 and "late reversals: none" in text
    header = next(line for line in text.splitlines() if line.lstrip().startswith("rank")).split()
    assert header[header.index("dd") + 1:][:3] == ["conc", "under", "run"]
    rows = list(csv.DictReader(out.open()))
    assert {"max_dd_all", "conc_all", "under_all", "run_all", "sharpe_day_all", "sharpe_block_all", "late_days_all"} <= set(rows[0])


def test_the_risk_measures_read_each_days_path_at_fine_blocks():
    mode, days = TradeMatching.ALL, [SimpleNamespace(name="d1"), SimpleNamespace(name="d2")]

    def piece(fine):
        return grid.Piece(sum(fine), [sum(fine)], fine, {"X": sum(fine)}, 1, 0, 0, "")

    steady = [1.0] * 100
    late = [-1.0] * 90 + [20.0] * 10  # 90 blocks down, then 200 back in the last 1,000 ticks: 110 for the day
    outcomes = {(0,): grid._assemble((0,), ("steady",), {(0, mode): piece(steady), (1, mode): piece(steady[:50] + [3.0] * 50)}, days, [mode]),
                (1,): grid._assemble((1,), ("late",), {(0, mode): piece(late), (1, mode): piece(steady)}, days, [mode])}
    risk = grid.risk_of(outcomes[(1,)], mode)
    assert risk.late == 1 and risk.drawdown == 90 and abs(risk.conc - 100 / 110) < 1e-9 and risk.run >= 0.5
    assert grid.risk_of(outcomes[(0,)], mode).late == 0 and grid.risk_of(outcomes[(0,)], mode).drawdown == 0
    assert abs(grid.risk_of(outcomes[(0,)], mode).sharpe_day - statistics.fmean([100, 200]) / statistics.stdev([100, 200])) < 1e-12
    axes = [grid.Axis("cell", ["steady", "late"])]
    rows = grid.build_rows(axes, [mode], outcomes)
    keys = grid.sort_keys([mode])
    for name in ("drawdown", "conc", "run", "sharpe-block"):
        assert max(rows, key=keys[name]).values == ("steady",), name
    late_line = grid.format_late(axes, mode, rows)
    assert "! late reversals in 1 of 2 cells" in late_line and "cell=late (1 day)" in late_line
