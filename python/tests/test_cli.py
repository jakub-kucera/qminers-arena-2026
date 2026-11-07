from pathlib import Path

from arena import backtest
from arena.cli import Requote, participant_names
from arena.engine import EngineConfig, run_market
from arena.model import Book, Day, Order, Tick
from tests.test_grid import BOT


def test_participant_names_number_repeated_files():
    names = participant_names(Path("python/bots/template.py"), [Path("x/template.py"), Path("other.py"), Path("template.py")])
    assert names == ["template", "template#2", "other", "template#3"]


def test_the_mark_and_the_limit_penalty_reach_the_engine_config(tmp_path, data_dir):
    import argparse

    from arena.cli import add_common_arguments, setup
    from arena.engine import Mark

    parser = argparse.ArgumentParser()
    add_common_arguments(parser)
    s = setup(parser.parse_args(["bot.py", "1", "--data", str(data_dir), "--mark", "touch", "--limit-penalty", "2"]))
    assert s.config.mark is Mark.TOUCH and s.config.limit_penalty == 2.0
    s = setup(parser.parse_args(["bot.py", "1", "--data", str(data_dir)]))
    assert s.config.mark is Mark.MID and s.config.limit_penalty is None



def test_a_formats_engine_settings_are_every_tools_defaults_and_flags_override_them(monkeypatch, data_dir):
    # The rules fix the queue, a taker fee, the mark and the matching: the plug-in says so once (ENGINE), and a
    # flag given on the command line still wins (the 2026-10-28 rehearsal needed four flags on every command).
    import argparse

    import pytest

    from arena.cli import add_common_arguments, format_config, setup
    from arena.engine import Mark, QueueModel, TradeMatching
    from arena.formats import prosperity

    monkeypatch.setattr(prosperity, "ENGINE", {"queue": "prob", "fee": 1.0, "maker_fee": 0.0, "mark": "touch", "trade_matching": "worse"}, raising=False)
    parser = argparse.ArgumentParser()
    add_common_arguments(parser)
    s = setup(parser.parse_args(["bot.py", "1", "--data", str(data_dir)]))
    assert (s.config.queue, s.config.fee, s.config.maker_fee, s.config.mark, s.config.trade_matching) == \
        (QueueModel.PROB, 1.0, 0.0, Mark.TOUCH, TradeMatching.WORSE)
    s = setup(parser.parse_args(["bot.py", "1", "--data", str(data_dir), "--mark", "mid", "--fee", "0", "--match-trades", "all"]))
    assert (s.config.mark, s.config.fee, s.config.trade_matching, s.config.queue) == (Mark.MID, 0.0, TradeMatching.ALL, QueueModel.PROB)
    assert format_config("prosperity", resting=True).resting and format_config("prosperity").queue is QueueModel.PROB
    monkeypatch.setattr(prosperity, "ENGINE", {"queues": "prob"})
    with pytest.raises(ValueError, match="names no engine setting: queues"):
        format_config("prosperity")


def test_without_an_engine_dict_a_format_runs_under_prosperitys_settings():
    from arena.cli import format_config
    from arena.engine import EngineConfig

    assert format_config("prosperity") == EngineConfig() and format_config("drill").resting

def test_backtest_reports_rivals(capsys, tmp_path, data_dir):
    path = tmp_path / "bot.py"
    path.write_text(BOT)
    code = backtest.main([str(path), "1", "--data", str(data_dir), "--vs", str(path)])
    out = capsys.readouterr().out
    assert code == 0
    assert "vs bot#2: pnl" in out
    assert "rivals: bot#2" in out


class _NeverCancels:
    """A bot written for orders that live one tick: the same bid every tick, never a cancel."""

    def __init__(self):
        self.seen_open = []

    def step(self, tick, positions, own_fills, market_trades, open_orders):
        self.seen_open.append(list(open_orders))
        return [Order("X", 90, 1)]


def test_requote_cancels_a_rivals_resting_orders_every_tick():
    d = Day("d", ["X"], {"X": 2}, [Tick(t, {"X": Book(((89, 5),), ((111, 5),))}, {}, {}) for t in range(0, 500, 100)])
    plain, wrapped = _NeverCancels(), _NeverCancels()
    (piled,) = run_market(d, [("rival", plain)], EngineConfig(resting=True))
    (requoted,) = run_market(d, [("rival", Requote(wrapped))], EngineConfig(resting=True))
    assert piled.limit_breaches  # the bids pile up past the limit of 2
    assert not requoted.limit_breaches and len(requoted.cancels) == 4
    assert all(seen == [] for seen in wrapped.seen_open)  # it never sees its own resting orders


def test_the_experiments_backtests_run_under_the_formats_rules_but_keep_their_modes(monkeypatch):
    # cli.backtest is the experiments' (no CLI tool calls it): the rules' fees, queue and mark fill in, while the
    # matching, resting and delay an experiment varies as its modes stay its own.
    from arena.cli import describe, under_rules
    from arena.engine import EngineConfig, Mark, QueueModel, TradeMatching
    from arena.formats import prosperity

    monkeypatch.setattr(prosperity, "ENGINE", {"fee": 1.0, "mark": "touch", "queue": "prob", "trade_matching": "worse"}, raising=False)
    config = under_rules(EngineConfig(resting=True), "prosperity")
    assert (config.fee, config.mark, config.queue, config.trade_matching, config.resting) == (1.0, Mark.TOUCH, QueueModel.PROB, TradeMatching.ALL, True)
    assert under_rules(EngineConfig(queue=QueueModel.FRONT), "prosperity").queue is QueueModel.FRONT  # set away from the default: kept
    assert describe(config) == "resting True, queue prob, mark touch, fee 1.0" and describe(EngineConfig()) == "Prosperity's"
