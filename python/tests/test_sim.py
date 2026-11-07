import pytest

from arena import diagnose, sim
from arena.formats import prosperity
from arena.model import Cancel, Order
from arena.sim import Fundamental, LimitTraders, Maker, MarketSpec, NoiseTakers, ProductSpec


class ScriptedBot:
    """Sends preset orders per timestamp and records what the market showed it."""

    def __init__(self, script=None, cancel_at=None):
        self.script = script or {}
        self.cancel_at = cancel_at  # cancels every open order at this timestamp
        self.books, self.open_orders = [], []

    def step(self, tick, positions, own_fills, market_trades, open_orders):
        self.books.append(tick.books.get("X"))
        self.open_orders.append(open_orders)
        if tick.timestamp == self.cancel_at:
            return [Cancel(order.id) for order in open_orders]
        return self.script.get(tick.timestamp, [])


def market(ticks=3, maker=Maker(half_spread=2, size=(10, 10)), noise=NoiseTakers(), limit=10, **product):
    return MarketSpec((ProductSpec("X", limit, Fundamental(100), maker, noise=noise, **product),), ticks=ticks, step=100)


def test_the_same_seed_repeats_and_another_differs():
    spec = sim.preset_market(["KELP"], ticks=300)
    a, b, c = sim.run(spec, 1).day, sim.run(spec, 1).day, sim.run(spec, 2).day
    assert [(t.books, t.trades) for t in a.ticks] == [(t.books, t.trades) for t in b.ticks]
    assert [t.books for t in a.ticks] != [t.books for t in c.ticks]


def test_a_bot_does_not_change_the_agents_draws():
    spec = sim.preset_market(["KELP"], ticks=300)
    alone = sim.run(spec, 0)
    with_bot = sim.run(spec, 0, [("me", ScriptedBot({100: [Order("KELP", 3000, 20)]}))])
    assert alone.fundamentals == with_bot.fundamentals
    assert with_bot.results[0].positions["KELP"][-1] == 20


def test_the_maker_quotes_walls_around_the_fundamental():
    bot = ScriptedBot()
    sim.run(market(), 0, [("me", bot)])
    assert bot.books[0].bids == ((98, 10),) and bot.books[0].asks == ((102, 10),)


def test_a_take_moves_the_skewing_maker():
    bot = ScriptedBot({0: [Order("X", 102, 4)]})
    result = sim.run(market(maker=Maker(half_spread=2, size=(10, 10), skew=0.5)), 0, [("me", bot)]).results[0]
    assert [(f.price, f.quantity, f.source) for f in result.fills] == [(102, 4, "book")]
    # It sold 4, so its centre moves up 2 and it quotes 100 / 104.
    assert bot.books[1].bids == ((100, 10),) and bot.books[1].asks == ((104, 10),)


def test_takers_fill_a_quote_inside_the_walls_then_it_is_cancelled():
    sellers = NoiseTakers(rate=3.0, size=(1, 1), buy_share=0.0)
    bot = ScriptedBot({0: [Order("X", 101, 50)]})
    result = sim.run(market(noise=sellers, limit=100), 0, [("me", bot)]).results[0]
    tick0 = [f for f in result.fills if f.timestamp == 0]
    assert tick0 and all(f.price == 101 and f.source == "trade" and f.counterparty == "" for f in tick0)
    assert bot.open_orders[1] == []  # default mode: it lived for tick 0's takers only
    assert all(f.timestamp == 0 for f in result.fills)


def test_in_resting_mode_a_quote_stays_until_cancelled():
    bot = ScriptedBot({0: [Order("X", 99, 3)]}, cancel_at=200)
    result = sim.run(market(ticks=4), 0, [("me", bot)], resting=True).results[0]
    assert [(o.price, o.quantity) for o in bot.open_orders[1]] == [(99, 3)]
    assert bot.books[1].bids == ((98, 10),)  # its own order is hidden from it
    assert bot.open_orders[3] == [] and [i for _, i in result.cancels] == [o.id for o in bot.open_orders[2]]


def test_a_bot_never_trades_with_itself():
    bot = ScriptedBot({0: [Order("X", 101, -2)], 100: [Order("X", 101, 2)]})
    result = sim.run(market(), 0, [("me", bot)], resting=True).results[0]
    assert result.fills == []


def test_orders_that_could_breach_the_limit_are_rejected():
    bot = ScriptedBot({0: [Order("X", 102, 6), Order("X", 101, 6)]})
    result = sim.run(market(limit=10), 0, [("me", bot)]).results[0]
    assert result.limit_breaches == [(0, "X")] and result.fills == []


def test_two_bots_trade_with_each_other():
    a = ScriptedBot({0: [Order("X", 101, -3)]})
    b = ScriptedBot({100: [Order("X", 101, 3)]})
    results = sim.run(market(), 0, [("a", a), ("b", b)], resting=True).results
    assert [(f.quantity, f.counterparty) for f in results[1].fills] == [(3, "a")]
    assert [(f.quantity, f.counterparty, f.source) for f in results[0].fills] == [(-3, "b", "trade")]


def test_written_days_load_through_the_prosperity_format(tmp_path):
    spec = MarketSpec((ProductSpec("ZZZ", 7, Fundamental(500, sd=0.3), Maker(), LimitTraders(rate=1.0, life=1), NoiseTakers(rate=0.5)),), ticks=50)
    made = sim.run(spec, 4)
    sim.write_day(made, tmp_path, 1, 0)
    (loaded,) = prosperity.load_days(tmp_path, ["1-0"])
    assert loaded.limits == {"ZZZ": 7}
    assert [t.books for t in loaded.ticks] == [t.books for t in made.day.ticks]
    assert [t.trades for t in loaded.ticks] == [t.trades for t in made.day.ticks]
    assert [t.marks for t in loaded.ticks] == [t.marks for t in made.day.ticks]
    assert (tmp_path / "round1" / "fundamental_round_1_day_0.csv").exists()


def test_overrides_reach_nested_settings_and_reject_typos():
    spec = sim.with_override(sim.preset_market(["KELP"]), "KELP.maker.size", [5, 6])
    assert spec.products[0].maker.size == (5, 6)
    assert sim.with_override(spec, "ticks", 20).ticks == 20
    with pytest.raises(ValueError, match="no product"):
        sim.with_override(spec, "NOPE.maker.skew", 1)
    with pytest.raises(ValueError, match="no field"):
        sim.with_override(spec, "KELP.maker.skwe", 1)


# The acceptance test (Get Real, adapted): three generated days look like P3 round 1 to
# arena.diagnose. The bands hold P3 round 1's own value (in the comment) with some room.
BANDS = {
    "KELP": {  # P3: spread 3, AC1 -0.48, mid signature 17.9, wall signature 2.8, jumps 0%
        "spread_ticks_median": (2, 4),
        "mid_lag1_autocorr": (-0.6, -0.35),
        "mid_signature": (10, 30),
        "wall_signature": (1.5, 5),
        "jump_share": (0, 0.02),
    },
    "RAINFOREST_RESIN": {  # P3: spread 8, AC1 -0.50, wall sd 0.35, jumps 3%
        "spread_ticks_median": (4, 10),
        "mid_lag1_autocorr": (-0.6, -0.4),
        "wall_sd": (0, 1),
        "jump_share": (0, 0.08),
    },
    "SQUID_INK": {  # P3: spread 3, AC1 -0.17, mid signature 1.5, jumps 16%
        "spread_ticks_median": (2, 4),
        "mid_lag1_autocorr": (-0.3, 0),
        "mid_signature": (1, 2.5),
        "jump_share": (0.08, 0.25),
    },
}


# P4 rounds 3-4's Hydrogel (four distinct days): spread 16, slow-reversion ratio 2.37, wall sd 32.6
# around 9,996.5, 336 trades a day, jumps 0.1%. The preset's mid is less noisy at one tick than the
# real one (lag-1 autocorrelation about 0 against -0.13), so that isn't banded.
HYDROGEL_BANDS = {
    "spread_ticks_median": (12, 20),
    "wall_reversion": (1.8, 3.2),
    "wall_sd": (20, 45),
    "jump_share": (0, 0.03),
}


def test_the_hydrogel_preset_looks_like_prosperity_4s_hydrogel():
    row = diagnose.diagnose([sim.run(sim.preset_market(["HYDROGEL_PACK"]), seed).day for seed in range(3)])["HYDROGEL_PACK"]
    misses = [f"{key} {row[key]:.3f} not in {band}" for key, band in HYDROGEL_BANDS.items() if not band[0] <= row[key] <= band[1]]
    assert not misses
    assert "reverts to a level" in row["notes"]
    assert 250 <= row["trades"] / 3 <= 450


@pytest.mark.parametrize("regime, end", [("shift_up", 5), ("shift_down", -5), ("trend_up", 10), ("trend_down", -10)])
def test_a_regime_changes_every_fundamental_from_mid_day_by_the_products_spread(regime, end):
    base = sim.preset_market(["KELP", "HYDROGEL_PACK"], ticks=400)
    plain, changed = sim.run(base, 3), sim.run(sim.with_regime(base, regime), 3)
    for product, spread in (("KELP", 3.5), ("HYDROGEL_PACK", 16)):
        a, b = plain.fundamentals[product], changed.fundamentals[product]
        assert a[:200] == b[:200]  # the same draws, so the morning is the same day
        assert b[-1] - a[-1] == pytest.approx(end * spread)  # a level product follows: its level moves too


def test_regime_arguments_are_checked():
    with pytest.raises(ValueError, match="unknown regime"):
        sim.with_regime(sim.preset_market(), "crash")
    with pytest.raises(ValueError, match="inside the day"):
        sim.with_regime(sim.preset_market(), "shift_up", at=1.0)


def test_generated_days_look_like_prosperity_3_round_1():
    spec = sim.preset_market()
    rows = diagnose.diagnose([sim.run(spec, seed).day for seed in range(3)])
    misses = [
        f"{product} {key} {rows[product][key]:.3f} not in {band}"
        for product, bands in BANDS.items()
        for key, band in bands.items()
        if not band[0] <= rows[product][key] <= band[1]
    ]
    assert not misses


def _wall_jumps(day, product, size=50):
    walls = [tick.books[product].wall_mid for tick in day.ticks]
    walls = [w for w in walls if w is not None]
    moves = [b - a for a, b in zip(walls, walls[1:]) if abs(b - a) >= size]
    reversed_ = sum(1 for a, b in zip(moves, moves[1:]) if a * b < 0) / (len(moves) - 1)
    on_grid = sum(1 for w in walls if w % 100 == 0) / len(walls)
    return len(moves), reversed_, on_grid


def test_the_robot_dishes_preset_looks_like_prosperity_4s_jumping_day():
    # P4 round 5 day 4, from tick 1,153 (`experiments.day.p4_jumps`): 741 jumps of 50 or more, 87%
    # reversing the one before, the wall mid on a multiple of 100 on 88% of ticks, spread 8, 249
    # trades. diagnose's jump share (moves past half the spread) is 0.158 there, since its first
    # 1,153 ticks were an ordinary noisy walk that the preset leaves out.
    days = [sim.run(sim.preset_market(["ROBOT_DISHES"]), seed).day for seed in range(3)]
    for day in days:
        jumps, reversed_, on_grid = _wall_jumps(day, "ROBOT_DISHES")
        assert 550 <= jumps <= 1000 and 0.8 <= reversed_ <= 0.93 and on_grid >= 0.8
    row = diagnose.diagnose(days)["ROBOT_DISHES"]
    assert row["spread_ticks_median"] == 8 and 0.04 <= row["jump_share"] <= 0.2
    assert 180 <= row["trades"] / 3 <= 330


def test_the_noisy_maker_preset_hides_the_price_in_the_walls():
    # KELP's walls filter the mid's noise; KELP_NOISY's are as noisy as the mid, and diagnose says so.
    rows = {name: diagnose.diagnose([sim.run(sim.preset_market([name]), seed).day for seed in range(3)])[name] for name in ("KELP", "KELP_NOISY")}
    assert rows["KELP"]["wall_signature"] < rows["KELP"]["mid_signature"] / 4
    assert rows["KELP_NOISY"]["wall_signature"] > rows["KELP_NOISY"]["mid_signature"] / 2
    assert "mid and wall mid both noisy" in rows["KELP_NOISY"]["notes"] and "wall mid filters" in rows["KELP"]["notes"]


def test_the_kelp_flow_preset_has_prosperity_3s_one_sided_takers():
    # P3 round 1 Kelp: 35% of the trades at the touch are buys (42% of the volume), C(1) 0.127;
    # the rest as KELP (the same bands).
    row = diagnose.diagnose([sim.run(sim.preset_market(["KELP_FLOW"]), seed).day for seed in range(3)])["KELP_FLOW"]
    assert 0.31 <= row["buy_share"] <= 0.39 and 0.09 <= row["c1"] <= 0.17
    misses = [f"{key} {row[key]:.3f} not in {band}" for key, band in BANDS["KELP"].items() if not band[0] <= row[key] <= band[1]]
    assert not misses


def test_noise_takers_can_repeat_the_last_side():
    sticky = MarketSpec((ProductSpec("X", 10, Fundamental(100), Maker(size=(1000, 1000)), noise=NoiseTakers(rate=1.0, size=(1, 1), persistence=0.9)),), ticks=2000)
    signs = [1 if t.price > 100 else -1 for tick in sim.run(sticky, 0).day.ticks for t in tick.trades.get("X", [])]
    c1 = sum(a * b for a, b in zip(signs, signs[1:])) / (len(signs) - 1)
    assert c1 > 0.8  # 0.9 repeat the last side, the rest draw it afresh: about 0.9 + 0.1 x 0
