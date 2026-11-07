import textwrap

import pytest

from arena import compare, grid
from arena.engine import EngineConfig, Mark, QueueModel, TradeMatching
from arena.scenario import Rival, Scenario, config_for, parse_scenario, plain, rivals_for, scenarios_from

RIVAL = "python/bots/rivals/sniper.py"


def test_a_scenario_changes_only_the_settings_it_names():
    s = parse_scenario(f"tight:match=worse,resting,queue=prob,power=2,fill=0.7,seed=3,vs={RIVAL}@EDGE=2,vs={RIVAL}")
    base = EngineConfig(resting=False, queue=QueueModel.BACK)
    assert config_for(base, s) == EngineConfig(TradeMatching.WORSE, True, QueueModel.PROB, 2.0, 0.7, 3)
    assert [r.overrides for r in s.rivals] == [{"EDGE": 2}, {}] and str(s.rivals[0]) == f"{RIVAL}@EDGE=2"
    assert f"{s}" == "tight" and f"{s:>6}" == " tight" and s.value == "tight" and not s.plain
    off = parse_scenario("calm:resting=no,vs=none")
    assert config_for(EngineConfig(resting=True), off) == EngineConfig() and rivals_for(["x"], off) == []
    assert rivals_for(["x"], parse_scenario("half:fill=0.5")) == ["x"]
    assert parse_scenario("match=none").name == "match=none"  # named by its items
    scored = parse_scenario("portal:mark=touch,penalty=2.5")
    assert config_for(EngineConfig(seed=4), scored) == EngineConfig(seed=4, mark=Mark.TOUCH, limit_penalty=2.5)
    assert config_for(EngineConfig(mark=Mark.LAST, limit_penalty=1.0), parse_scenario("x:fill=0.5")) == EngineConfig(fill_ratio=0.5, mark=Mark.LAST, limit_penalty=1.0)
    assert config_for(EngineConfig(), parse_scenario("fees:fee=0.5,bps=2")) == EngineConfig(fee=0.5, fee_bps=2.0)
    assert config_for(EngineConfig(), parse_scenario("rtg:bps=2,mbps=-1")) == EngineConfig(fee_bps=2.0, maker_fee_bps=-1.0)  # a maker's rebate
    assert config_for(EngineConfig(), parse_scenario("varde:ofee=0.005")) == EngineConfig(order_fee=0.005)  # a fee an order placed
    assert config_for(EngineConfig(), parse_scenario("half:share=0.5")) == EngineConfig(print_share=0.5)  # half of each print
    assert config_for(EngineConfig(), parse_scenario("kept:deplete")) == EngineConfig(deplete=True)
    assert config_for(EngineConfig(), parse_scenario("capped:cap=8")) == EngineConfig(max_orders=8)
    assert config_for(EngineConfig(), parse_scenario("caps:acap=10,rcap=4")) == EngineConfig(max_actions=10, max_resting=4)


def test_modes_are_plain_scenarios_and_names_are_unique():
    assert scenarios_from("all,worse", [], TradeMatching.ALL) == [plain(TradeMatching.ALL), plain(TradeMatching.WORSE)]
    assert all(s.plain for s in scenarios_from(None, [], TradeMatching.NONE))
    found = scenarios_from(None, ["half:fill=0.5"], TradeMatching.WORSE)
    assert [str(s) for s in found] == ["worse", "half"]  # --match-trades first
    with pytest.raises(ValueError, match="twice"):
        scenarios_from("all", ["all:fill=0.5"], TradeMatching.ALL)
    assert config_for(EngineConfig(), TradeMatching.WORSE) == EngineConfig(TradeMatching.WORSE)


@pytest.mark.parametrize("text", ["x:fill=0", "x:fill=1.5", "x:queue=middle", "x:match=some", "x:speed=2", "x:seed=1,seed=2",
                                  "x:resting=maybe", "x:fill", "x:vs=no/such/bot.py", "x:", "x:mark=close", "x:penalty=-1", "x:penalty=a", "x:penalty", "x:fee=-1", "x:bps=a", "x:ofee=-1", "x:share=0", "x:share=1.5"])
def test_a_bad_scenario_is_refused(text):
    with pytest.raises(ValueError):
        parse_scenario(text)


def test_a_rival_is_told_apart_by_its_settings():
    a, b = Rival("p.py", {"EDGE": 1}, "p.py@EDGE=1"), Rival("p.py", {"EDGE": 2}, "p.py@EDGE=2")
    assert a != b and len({a, b, Rival("p.py", {"EDGE": 1}, "p.py@EDGE=1")}) == 2


BOT = """
from datamodel import Order

PARAMS = {"size": 1}

class Trader:
    def run(self, state):
        if state.timestamp == 0:
            return {"KELP": [Order("KELP", 2032, PARAMS["size"])]}, 0, ""
        return {}, 0, ""
"""


def test_the_grid_scores_each_scenario_and_the_worst_case(capsys, tmp_path, data_dir):
    bot = tmp_path / "bot.py"
    bot.write_text(textwrap.dedent(BOT))
    rival = f"{bot}@PARAMS.size=2"
    code = grid.main([str(bot), "1", "--data", str(data_dir), "--grid", "PARAMS.size=1..3", "--modes", "all", "--jobs", "1",
                      "--scenario", f"crowd:match=worse,vs={rival}", "--sort", "worst", "--out", str(tmp_path / "grid.csv")])
    text = capsys.readouterr().out
    assert code == 0
    assert "scenarios:\n  crowd: match worse, per tick; against " in text and "@PARAMS.size=2" in text
    header = next(line for line in text.splitlines() if line.lstrip().startswith("rank")).split()
    assert header[header.index("pnl(crowd)") + 1] == "worst" and header[-1] == "fills" and "best by worst" in text
    header = (tmp_path / "grid.csv").read_text().splitlines()[0].split(",")
    assert "pnl_crowd" in header and "worst" in header
    # under --modes alone, nothing new is printed
    grid.main([str(bot), "1", "--data", str(data_dir), "--grid", "PARAMS.size=1..3", "--modes", "all,worse", "--jobs", "1"])
    plain_text = capsys.readouterr().out
    assert "scenarios:" not in plain_text and "worst" not in plain_text


def test_compare_scores_each_scenario_and_the_worst_case(capsys, tmp_path, data_dir):
    bot = tmp_path / "bot.py"
    bot.write_text(textwrap.dedent(BOT))
    code = compare.main([str(bot), "1", "--data", str(data_dir), "--bot", f"{bot}@PARAMS.size=2", "--jobs", "1", "--scenario", "thin:fill=0.5"])
    text = capsys.readouterr().out
    assert code == 0 and "pnl(thin)" in text and "best by worst" in text and "  thin: match all, per tick, fill 0.5; no rivals" in text
