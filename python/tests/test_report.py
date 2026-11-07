import statistics

import pytest

from arena import backtest, grid, report
from arena.engine import DayResult, EngineConfig, run_day
from arena.model import Order
from tests.test_engine import ScriptedBot, day, tick
from tests.test_grid import BOT


def test_the_portal_metrics_add_up_to_the_pnl():
    d = day(tick(0, asks=[(101, 20)], mark=100), tick(1, mark=100), tick(2, bids=[(99, 20)], mark=100), limits={"X": 10})
    script = {0: [Order("X", 101, 6), Order("X", 101, 6)], 2: [Order("X", 99, -12)]}
    result = run_day(d, ScriptedBot(script), EngineConfig(limit_penalty=2.5))
    (row,) = [line.split() for line in report.format_metrics(result, 2.5).splitlines() if line.strip().startswith("X ")]
    se = statistics.stdev([-17, -5, -12]) * 3**0.5  # the PnL's changes: -17, -22, -34
    # fills (orders), volume, position, cash, mark, penalty, s.e. ticks, s.e. blocks, quantiles, pnl
    assert row == ["X", "3", "(3)", "24", "0", "-24.00", "100.00", "10.00", f"{se:.2f}", "-", "12", "/", "12", "/", "12", "/", "12",
                   "-34.00"]  # cash -24 (bought 12 at 101, sold at 99) - penalty 10 = pnl -34


def test_the_portal_metrics_without_a_penalty_and_with_two_products():
    d = day(tick(0, asks=[(101, 5)], mark=100), tick(1, bids=[(102, 5)], mark=103))
    result = run_day(d, ScriptedBot({0: [Order("X", 101, 2)]}))
    text = report.format_metrics(result)
    assert "penalty" in text and "total" not in text  # one product: no total row
    (row,) = [line.split() for line in text.splitlines() if line.strip().startswith("X ")]
    assert row[1:8] == ["1", "(1)", "2", "2", "-202.00", "103.00", "0.00"] and row[-1] == "4.00"
    assert report.format_metrics(run_day(d, ScriptedBot())) == "  portal metrics: no trades"


def test_the_standard_errors_and_quantiles():
    assert report._quantiles([4, 1, 3, 2], (0.5, 0.25, 1.0)) == [2.5, 1.75, 4]  # as numpy.quantile
    pnl = [float(k % 2) for k in range(1, 41)]  # changes +1, -1, ...: every block of two sums to 0
    ticks, blocks = report._standard_errors(pnl)
    assert ticks == f"{statistics.stdev([1, -1] * 20) * 40**0.5:,.2f}" and blocks == "0.00"
    assert report._standard_errors([5.0]) == ["-", "-"]


def test_two_products_get_a_total_row():
    result = DayResult("d", ["A", "B"], {"A": 10, "B": 10}, timestamps=[0, 1], positions={"A": [1, 2], "B": [0, -1]},
                       marks={"A": [10.0, 11.0], "B": [5.0, 5.0]}, pnl={"A": [0.0, 1.0], "B": [0.0, 0.5]})
    (total,) = [line.split() for line in report.format_metrics(result).splitlines() if line.strip().startswith("total")]
    # no fills recorded: 0 (0); cash A 1 - 22, B 0.5 + 5
    assert total[1:4] == ["0", "(0)", "0"] and total[5] == "-15.50" and total[-1] == "1.50"


def test_the_portal_metrics_total_sums_the_days():
    first = DayResult("d0", ["X"], {"X": 10}, timestamps=[0, 1], positions={"X": [1, 2]},
                      marks={"X": [10.0, 11.0]}, pnl={"X": [0.0, 1.0]})
    second = DayResult("d1", ["X"], {"X": 10}, timestamps=[0, 1], positions={"X": [3, 4]},
                       marks={"X": [12.0, 13.0]}, pnl={"X": [0.0, 2.0]})
    text = report.format_metrics_total([first, second])
    (row,) = [line.split() for line in text.splitlines() if line.strip().startswith("X ")]
    # cash: day 0's end position counted at its last mark, so cash + position x mark = pnl: 3 - 4 x 13 = -49
    assert row[1:8] == ["0", "(0)", "0", "4", "-49.00", "13.00", "0.00"] and row[-1] == "3.00"
    assert "s.e. days" in text and "days: 2" in text and "sum 3.00" in text and "mean 1.50" in text
    empty = DayResult("d", ["X"], {"X": 1}, positions={"X": []}, marks={"X": []}, pnl={"X": []})
    assert report.format_metrics_total([empty]) == "  portal metrics over 1 day: no trades"


def test_backtest_prints_the_portal_metrics_on_request(capsys, tmp_path, data_dir):
    path = tmp_path / "bot.py"
    path.write_text(BOT)
    assert backtest.main([str(path), "1", "--data", str(data_dir)]) == 0
    assert "portal metrics" not in capsys.readouterr().out
    assert backtest.main([str(path), "1", "--data", str(data_dir), "--metrics"]) == 0
    out = capsys.readouterr().out
    assert "portal metrics (--metrics):" in out
    assert "portal metrics over 2 days" in out
    assert "in the portal's credits" not in out  # Prosperity's prices are credits


def test_metrics_turn_into_credits_by_the_formats_multiplier(capsys, tmp_path, data_dir, monkeypatch):
    # The 2026-10-30 rehearsal: prices in points worth 2 credits a lot, which only the rules said.
    from arena import cli
    from arena.formats import FORMATS

    monkeypatch.setattr(FORMATS["prosperity"], "CREDITS", 2.0, raising=False)
    path = tmp_path / "bot.py"
    path.write_text(BOT)
    assert backtest.main([str(path), "1", "--data", str(data_dir), "--metrics"]) == 0
    out = capsys.readouterr().out
    assert "days: 2 · sum -4.00 · mean -2.00" in out  # the tables stay in price units
    assert "in the portal's credits (2 a price unit" in out and "pnl sum -8.00 · mean -4.00" in out
    info = [type("D", (), {"info": {"A": {"tick": 0.5, "unit": 0.01}, "B": {"tick": 0.01, "unit": 0.01}}})()]
    assert cli.credits_per_unit("prosperity", info) == 0.02 and cli.credits_per_unit("drill", info) == 0.01
    mixed = [type("D", (), {"info": {"A": {"unit": 0.01}, "B": {"unit": 1}}})()]
    with pytest.raises(ValueError, match="different price units"):  # one CREDITS can't convert both
        cli.credits_per_unit("drill", mixed)


def test_a_late_reversal_is_flagged_and_steady_gains_are_not():
    # heyman7913's case: underwater for most of the day, then 80%+ of the PnL in the last 500 ticks
    late = [-0.01 * k for k in range(9_000)] + [-90 + 0.2 * k for k in range(1, 1_001)]
    risk = report.path_risk(late, report.WINDOW_TICKS)
    assert risk.pnl == late[-1] > 0 and risk.share > 0.8 and risk.best_end >= 9_499
    assert risk.longest >= 9_000 and abs(risk.drawdown - 89.99) < 1e-9 and risk.late
    steady = [0.01 * k for k in range(1, 10_001)]
    risk = report.path_risk(steady, report.WINDOW_TICKS)
    assert abs(risk.share - 0.05) < 1e-9 and risk.underwater == risk.longest == 0 and risk.drawdown == 0 and not risk.late
    # an early window, then a long bleed: concentrated and long underwater, but not a late reversal
    early = [0.5 * k for k in range(1, 501)] + [250 - 0.01 * k for k in range(1, 9_501)]
    risk = report.path_risk(early, report.WINDOW_TICKS)
    assert risk.share > 1 and risk.longest == 9_500 and not risk.late
    # sampled at the grid's 100-tick blocks, the same day is still a late reversal
    fine = [b - a for a, b in zip([0.0, *late[99::100]], late[99::100])]
    assert grid.fine_risk(fine).late and grid.fine_risk(fine).steps == 100
    assert report.path_risk([], 5) is None


def test_the_sharpes_pool_the_steps_and_the_days():
    a, b = report.path_risk([1.0, 3.0], 1), report.path_risk([2.0, 2.0], 1)  # changes 1, 2 and 2, 0
    changes = [1, 2, 2, 0]
    assert abs(report.sharpe([a, b]) - statistics.fmean(changes) / statistics.pstdev(changes)) < 1e-12
    assert abs(report.day_sharpe([3.0, 2.0, 4.0]) - 3 / 1) < 1e-12
    assert report.day_sharpe([3.0]) is None and report.sharpe([report.path_risk([0.0, 0.0], 1)]) is None


def test_backtest_prints_the_pnl_path(capsys, tmp_path, data_dir):
    path = tmp_path / "bot.py"
    path.write_text(BOT)
    assert backtest.main([str(path), "1", "--data", str(data_dir)]) == 0
    text = capsys.readouterr().out
    assert "pnl path: " in text and "below the running high" in text and "risk: Sharpe of the days' pnl" in text
