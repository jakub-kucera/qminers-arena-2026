from dataclasses import replace

import pytest

from arena import report
from arena.engine import EngineConfig, Mark, QueueModel, TradeMatching, run_day, run_market
from arena.model import Book, Cancel, Day, Fill, MarketTrade, OpenOrder, Order, Tick


class ScriptedBot:
    """Sends preset orders per timestamp and records what the engine showed it."""

    def __init__(self, script=None, error_at=None):
        self.script = script or {}
        self.error_at = error_at
        self.seen = []
        self.open_orders = []  # per tick
        self.books = []  # per tick, as shown to the bot

    def step(self, tick, positions, own_fills, market_trades, open_orders):
        self.seen.append((positions, own_fills, market_trades))
        self.open_orders.append(open_orders)
        self.books.append(tick.books)
        if tick.timestamp == self.error_at:
            raise RuntimeError("boom")
        return self.script.get(tick.timestamp, [])


def tick(timestamp, bids=(), asks=(), trades=(), mark=None, product="X"):
    return Tick(
        timestamp,
        {product: Book(tuple(bids), tuple(asks))},
        {product: list(trades)} if trades else {},
        {product: mark} if mark is not None else {},
    )


def day(*ticks, limits=None):
    limits = limits or {"X": 10}
    return Day("test", sorted(limits), limits, list(ticks))


def fills(result):
    return [(f.price, f.quantity, f.source) for f in result.fills]


def test_buy_walks_the_book_at_the_book_prices():
    d = day(tick(0, asks=[(101, 2), (102, 5), (103, 9)]))
    result = run_day(d, ScriptedBot({0: [Order("X", 102, 4)]}))
    assert fills(result) == [(101, 2, "book"), (102, 2, "book")]


def test_sell_walks_the_bids_best_first():
    d = day(tick(0, bids=[(99, 1), (98, 5)]))
    result = run_day(d, ScriptedBot({0: [Order("X", 98, -3)]}))
    assert fills(result) == [(99, -1, "book"), (98, -2, "book")]


def test_orders_in_one_tick_share_the_book():
    d = day(tick(0, asks=[(101, 3)]))
    result = run_day(d, ScriptedBot({0: [Order("X", 101, 2), Order("X", 101, 2)]}))
    assert fills(result) == [(101, 2, "book"), (101, 1, "book")]


def test_leftover_fills_against_market_trades_at_the_order_price():
    trade = MarketTrade("X", 99, 5, buyer="B", seller="S")
    d = day(tick(0, asks=[(105, 10)], trades=[trade]))
    result = run_day(d, ScriptedBot({0: [Order("X", 100, 3)]}))
    assert result.fills == [Fill(0, "X", 100, 3, "trade", "S", order_id=1)]


@pytest.mark.parametrize(
    "matching, filled", [(TradeMatching.ALL, 3), (TradeMatching.WORSE, 0), (TradeMatching.NONE, 0)]
)
def test_trade_matching_at_the_same_price(matching, filled):
    d = day(tick(0, trades=[MarketTrade("X", 100, 5)]))
    result = run_day(d, ScriptedBot({0: [Order("X", 100, 3)]}), EngineConfig(trade_matching=matching))
    assert sum(f.quantity for f in result.fills) == filled


def test_market_trade_volume_is_used_up():
    d = day(tick(0, trades=[MarketTrade("X", 99, 4)]))
    result = run_day(d, ScriptedBot({0: [Order("X", 100, 3), Order("X", 100, 3)]}))
    assert [f.quantity for f in result.fills] == [3, 1]


def test_orders_never_rest_into_the_next_tick():
    d = day(tick(0, asks=[(105, 5)]), tick(1, asks=[(100, 5)]))
    result = run_day(d, ScriptedBot({0: [Order("X", 100, 3)]}))
    assert result.fills == []


def test_possible_limit_breach_cancels_every_order_for_that_product():
    d = day(tick(0, asks=[(101, 20)]), limits={"X": 10})
    # Each buy alone fits, but both together could take the position to 12.
    result = run_day(d, ScriptedBot({0: [Order("X", 101, 6), Order("X", 90, 6)]}))
    assert result.fills == []
    assert result.limit_breaches == [(0, "X")]


def test_breach_on_one_product_leaves_others_trading():
    d = Day(
        "test",
        ["X", "Y"],
        {"X": 1, "Y": 1},
        [Tick(0, {"X": Book(asks=((10, 5),)), "Y": Book(asks=((20, 5),))}, {}, {})],
    )
    result = run_day(d, ScriptedBot({0: [Order("X", 10, 2), Order("Y", 20, 1)]}))
    assert [(f.product, f.quantity) for f in result.fills] == [("Y", 1)]


def test_pnl_values_position_at_the_mark():
    d = day(tick(0, asks=[(101, 5)], mark=100), tick(1, mark=104))
    result = run_day(d, ScriptedBot({0: [Order("X", 101, 2)]}))
    assert result.positions["X"] == [2, 2]
    assert result.pnl["X"] == [-2, 6]


def test_mark_touch_values_a_long_at_the_bid_a_short_at_the_ask_and_else_the_mark():
    d = day(tick(0, bids=[(99, 5)], asks=[(101, 5)], mark=100), tick(1, bids=[(98, 5)], asks=[(103, 5)], mark=100),
            tick(2, asks=[(103, 5)], mark=100))  # no bids at the last tick
    touch = EngineConfig(mark=Mark.TOUCH)
    long = run_day(d, ScriptedBot({0: [Order("X", 101, 2)]}), touch)
    assert long.marks["X"] == [99, 98, 100]  # the bid while long, the mark when there is none
    assert long.pnl["X"] == [-4, -6, -2]
    short = run_day(d, ScriptedBot({0: [Order("X", 99, -2)]}), touch)
    assert short.marks["X"] == [101, 103, 103] and short.pnl["X"] == [-4, -8, -8]
    assert run_day(d, ScriptedBot(), touch).marks["X"] == [100, 100, 100]  # flat: the mark
    assert run_day(d, ScriptedBot({0: [Order("X", 101, 2)]})).marks["X"] == [100, 100, 100]  # the default


def test_mark_last_values_positions_at_the_last_market_trade_and_the_mark_before_any():
    trades = [MarketTrade("X", 103, 1, timestamp=1), MarketTrade("X", 105, 1, timestamp=1)]
    d = day(tick(0, asks=[(101, 5)], mark=100), tick(1, mark=100, trades=trades), tick(2, mark=100))
    result = run_day(d, ScriptedBot({0: [Order("X", 101, 2)]}), EngineConfig(mark=Mark.LAST))
    assert result.marks["X"] == [100, 105, 105] and result.pnl["X"] == [-2, 8, 8]


def test_fees_charge_every_fill_per_lot_and_on_its_value():
    d = day(tick(0, asks=[(100, 5)], mark=100), tick(1, bids=[(100, 5)], mark=100))
    script = {0: [Order("X", 100, 2)], 1: [Order("X", 100, -2)]}
    assert run_day(d, ScriptedBot(script)).pnl["X"] == [0, 0]
    # each fill of 2 lots at 100: 0.5 a lot is 1, 10 bps of its 200 is 0.2
    charged = run_day(d, ScriptedBot(script), EngineConfig(fee=0.5, fee_bps=10))
    assert charged.pnl["X"] == pytest.approx([-1.2, -2.4])


def test_a_lot_fee_is_in_the_datas_price_units():
    d = day(tick(0, asks=[(10_000, 5)], mark=10_000), tick(1, bids=[(10_000, 5)], mark=10_000))  # $100.00 in cents
    d.info["X"] = {"tick": 0.01, "unit": 0.01}
    script = {0: [Order("X", 10_000, 2)], 1: [Order("X", 10_000, -2)]}
    # 0.03 dollars a lot is 3 cents: 6 on each fill of 2 lots
    assert run_day(d, ScriptedBot(script), EngineConfig(fee=0.03)).pnl["X"] == pytest.approx([-6, -12])


def test_a_makers_fee_replaces_the_fee_on_passive_fills_and_can_be_a_rebate():
    d = day(tick(0, asks=[(100, 5)], trades=[MarketTrade("X", 99, 2, "", "", 0)], mark=100), tick(1, mark=100))
    script = {0: [Order("X", 100, 1), Order("X", 99, 2)]}  # takes the ask (a taker), and a bid a trade at 99 meets (a maker)
    result = run_day(d, ScriptedBot(script), EngineConfig(fee=0.5, maker_fee=-0.25))
    assert sorted(fills(result)) == [(99, 2, "trade"), (100, 1, "book")]
    assert result.pnl["X"][0] == pytest.approx((100 - 100) + 2 * (100 - 99) - 0.5 + 2 * 0.25)
    bps = run_day(d, ScriptedBot(script), EngineConfig(fee_bps=20, maker_fee_bps=-10))
    assert bps.pnl["X"][0] == pytest.approx(2 - 20 * 100 / 10_000 + 10 * 198 / 10_000)


def test_an_order_fee_charges_every_accepted_order_filled_or_not():
    d = day(tick(0, asks=[(100, 5)], mark=100), tick(1, mark=100))
    # tick 0: a take that fills, a bid nothing meets, and two orders over the limit of 10 that are rejected (not charged)
    script = {0: [Order("X", 100, 2), Order("X", 95, 3)], 1: [Order("X", 95, 6), Order("X", 94, 6)]}
    result = run_day(d, ScriptedBot(script), EngineConfig(order_fee=0.25))
    assert result.positions["X"] == [2, 2] and result.limit_breaches == [(1, "X")]
    assert result.pnl["X"] == pytest.approx([-0.5, -0.5])  # two accepted orders, 0.25 each; the rejected ones cost nothing


def test_an_order_fee_is_in_the_datas_price_units():
    d = day(tick(0, asks=[(10_000, 5)], mark=10_000))
    d.info["X"] = {"tick": 0.05, "unit": 0.01}  # prices in cents: 0.005 a unit of the rules' currency is half a cent
    assert run_day(d, ScriptedBot({0: [Order("X", 9_000, 1)]}), EngineConfig(order_fee=0.005)).pnl["X"] == pytest.approx([-0.5])


def test_a_print_share_offers_our_orders_part_of_each_trade_rounded_down_and_the_bots_see_the_rest():
    trade = MarketTrade("X", 99, 5, "", "", 0)  # a sell of 5 at 99: our bid at 99 is at its price
    d = day(tick(0, bids=[(98, 5)], asks=[(101, 5)], trades=[trade], mark=100), tick(1, mark=100))
    bot = ScriptedBot({0: [Order("X", 99, 10)]})
    full = run_day(d, bot)
    assert sum(f.quantity for f in full.fills) == 5
    half = ScriptedBot({0: [Order("X", 99, 10)]})
    shared = run_day(d, half, EngineConfig(print_share=0.5))
    assert sum(f.quantity for f in shared.fills) == 2  # half of 5, rounded down
    assert [t.quantity for t in half.seen[1][2]["X"]] == [3]  # next tick the bot sees the trade less what it took


def test_deplete_keeps_what_we_took_off_the_book_until_the_recording_goes_below_it():
    levels = ([(101, 5)], [(101, 5)], [(101, 7)], [(101, 2)], [(101, 4)], [], [(101, 5)])
    d = day(*(tick(t, asks=a, mark=100) for t, a in enumerate(levels)))
    bot = ScriptedBot({0: [Order("X", 101, 3)]})
    run_day(d, bot, EngineConfig(deplete=True))
    # 3 taken from 5: 2 left; the recording grows to 7 (4 shown); it falls to 2, what we left, and is its own
    # again (2, then 4); the level goes, and comes back as recorded
    assert [b["X"].asks for b in bot.books] == [((101, 5),), ((101, 2),), ((101, 4),), ((101, 2),), ((101, 4),), (), ((101, 5),)]
    plain = ScriptedBot({0: [Order("X", 101, 3)]})
    run_day(d, plain)
    assert [b["X"].asks for b in plain.books][1] == ((101, 5),)


def test_deplete_limits_a_second_take_to_what_was_left():
    d = day(*(tick(t, asks=[(101, 5), (102, 9)], mark=100) for t in range(2)))
    script = {0: [Order("X", 101, 3)], 1: [Order("X", 101, 3)]}
    assert [f.quantity for f in run_day(d, ScriptedBot(script)).fills] == [3, 3]
    assert [f.quantity for f in run_day(d, ScriptedBot(script), EngineConfig(deplete=True)).fills] == [3, 2]


def test_an_order_cap_drops_the_orders_past_it_in_the_order_sent():
    d = day(tick(0, asks=[(101, 5), (102, 5)], mark=100))
    script = {0: [Order("X", 101, 1), Order("X", 102, 1), Order("X", 99, 1)]}
    result = run_day(d, ScriptedBot(script), EngineConfig(max_orders=2))
    assert [o.price for _, o in result.orders] == [101, 102] and len(result.fills) == 2  # the bid at 99 never reached the book
    assert result.errors == [(0, "order cap: 1 of 3 new orders over --max-orders 2 dropped")]
    assert not run_day(d, ScriptedBot(script)).errors



def test_an_action_cap_counts_cancels_and_drops_what_is_past_it_in_the_order_sent():
    # The 2026-10-28 rehearsal's rules: 10 actions a step, pulls included (--max-orders counts new orders only).
    d = day(tick(0, asks=[(105, 5)], mark=100), tick(1, asks=[(105, 5)], mark=100))
    script = {0: [Order("X", 98, 1), Order("X", 97, 1)], 1: [Cancel(1), Order("X", 96, 1), Order("X", 95, 1)]}
    result = run_day(d, ScriptedBot(script), EngineConfig(resting=True, max_actions=2))
    assert result.errors == [(1, "action cap: 1 of 3 actions over --max-actions 2 dropped")]
    assert result.cancels == [(1, 1)] and sorted(o.price for t, o in result.orders if t == 1) == [96, 97]  # the bid at 95 never arrived


def test_a_resting_cap_counts_the_kept_orders_first_and_lets_takes_through():
    # The rehearsal's rules: 4 resting orders a product. Kept orders count first; immediate-or-cancel ones don't.
    d = day(tick(0, asks=[(105, 5)], mark=100), tick(1, asks=[(105, 5)], mark=100))
    script = {0: [Order("X", 98, 1), Order("X", 97, 1)], 1: [Order("X", 96, 1), Order("X", 105, 1, ioc=True), Order("X", 95, 1)]}
    result = run_day(d, ScriptedBot(script), EngineConfig(resting=True, max_resting=3))
    assert result.errors == [(1, "resting cap: 1 new orders for X over --max-resting 3 dropped")]
    assert sorted(o.price for t, o in result.orders if t == 1) == [96, 97, 98, 105] and [f.price for f in result.fills] == [105]
    assert not run_day(d, ScriptedBot(script), EngineConfig(resting=True)).errors

def test_limit_penalty_lets_every_order_through_and_charges_each_lot_beyond_the_limit_each_tick():
    d = day(tick(0, asks=[(101, 20)], mark=100), tick(1, mark=100), tick(2, bids=[(99, 20)], mark=100), limits={"X": 10})
    script = {0: [Order("X", 101, 6), Order("X", 101, 6)], 2: [Order("X", 99, -12)]}
    rejected = run_day(d, ScriptedBot(script))
    assert rejected.fills == [] and rejected.limit_breaches == [(0, "X"), (2, "X")]  # Prosperity's rule
    charged = run_day(d, ScriptedBot(script), EngineConfig(limit_penalty=2.5))
    assert charged.positions["X"] == [12, 12, 0]
    assert charged.limit_breaches == [(0, "X"), (1, "X")]  # the ticks it ended over the limit
    assert charged.pnl["X"] == [-12 - 5, -12 - 10, -24 - 10]  # 2 lots over, 2.5 each, on two ticks
    assert report.penalty_paid(charged, 2.5) == 10
    assert "2 ticks over a limit (--limit-penalty), first X at 0, charged 10 in all" in report.format_day(charged, 2.5)
    assert "ticks with orders cancelled for breaching a limit" in report.format_day(rejected)


def test_a_limit_penalty_is_in_the_datas_price_units():
    d = day(tick(0, asks=[(10_000, 20)], mark=10_000), tick(1, mark=10_000), limits={"X": 10})  # $100.00 in cents
    d.info["X"] = {"tick": 0.01, "unit": 0.01}
    charged = run_day(d, ScriptedBot({0: [Order("X", 10_000, 12)]}), EngineConfig(limit_penalty=0.05))
    # 0.05 dollars a lot a tick is 5 cents: 2 lots over on two ticks
    assert charged.pnl["X"] == pytest.approx([-10, -20])
    assert report.penalty_paid(charged, 0.05) == pytest.approx(20)


def test_with_a_limit_penalty_nothing_is_rejected_so_no_bot_loses_a_race():
    quiet = dict(bids=[(98, 5)], asks=[(104, 5)])
    d = day(tick(0, **quiet), tick(1, **quiet), limits={"X": 10})
    for seed in range(10):  # test_losing_a_race_is_not_a_limit_breach's case, where some seeds race
        a, b = market(
            d,
            ScriptedBot({0: [Order("X", 100, 6)], 1: [Cancel(1), Order("X", 99, 10)]}),
            ScriptedBot({1: [Order("X", 100, -6)]}),
            config=EngineConfig(resting=True, seed=seed, limit_penalty=1.0),
        )
        assert a.races == [] and a.limit_breaches == [] and b.races == []


def test_wall_mid_takes_the_largest_level_on_each_side():
    book = Book(bids=((99, 2), (98, 20), (97, 20)), asks=((101, 3), (103, 25)))
    assert book.wall_mid == (98 + 103) / 2  # a tie goes to the level nearer the touch
    assert Book(bids=((99, 2),)).wall_mid is None


def test_result_records_wall_mids_and_the_data_trades():
    trade = MarketTrade("X", 101, 4, timestamp=0)
    day = Day("d0", ["X"], {"X": 10}, [Tick(0, {"X": Book(bids=((99, 9),), asks=((101, 9),))}, {"X": [trade]}, {})])
    result = run_day(day, ScriptedBot({0: [Order("X", 101, 2)]}))
    assert result.wall_mids["X"] == [100.0]
    assert result.market_trades == [(0, trade)]  # as recorded, not reduced by the bot's fill against it


def test_mark_falls_back_to_the_book_mid():
    d = day(tick(0, bids=[(98, 1)], asks=[(101, 5)]), tick(1))
    result = run_day(d, ScriptedBot({0: [Order("X", 101, 1)]}))
    assert result.marks["X"] == [99.5, 99.5]


def test_bot_errors_are_recorded_and_the_run_continues():
    d = day(tick(0, asks=[(101, 5)]), tick(1, asks=[(101, 5)]))
    result = run_day(d, ScriptedBot({1: [Order("X", 101, 1)]}, error_at=0))
    assert len(result.errors) == 1 and "boom" in result.errors[0][1]
    assert len(result.fills) == 1


def test_orders_for_unknown_products_are_errors():
    d = day(tick(0, asks=[(101, 5)]))
    result = run_day(d, ScriptedBot({0: [Order("NOPE", 101, 1)]}))
    assert result.fills == [] and "NOPE" in result.errors[0][1]


def test_bot_sees_its_fills_and_the_leftover_market_trades_next_tick():
    d = day(tick(0, trades=[MarketTrade("X", 99, 5, timestamp=0)]), tick(1))
    bot = ScriptedBot({0: [Order("X", 100, 2)]})
    run_day(d, bot)
    positions, own_fills, market_trades = bot.seen[1]
    assert positions == {"X": 2}
    assert own_fills == [Fill(0, "X", 100, 2, "trade", "", order_id=1)]
    assert [t.quantity for t in market_trades["X"]] == [3]


def test_fill_ratio_zero_blocks_every_fill():
    d = day(tick(0, asks=[(101, 5)], trades=[MarketTrade("X", 99, 5)]))
    result = run_day(d, ScriptedBot({0: [Order("X", 101, 5)]}), EngineConfig(fill_ratio=0.0))
    assert result.fills == []


def test_fill_ratio_draws_repeat_with_the_same_seed():
    ticks = [tick(t, asks=[(101, 50)]) for t in range(50)]
    script = {t: [Order("X", 101, 1)] for t in range(50)}
    config = EngineConfig(fill_ratio=0.5, seed=7)
    first = run_day(day(*ticks, limits={"X": 100}), ScriptedBot(script), config)
    second = run_day(day(*ticks, limits={"X": 100}), ScriptedBot(script), config)
    assert first.fills == second.fills
    assert 0 < len(first.fills) <= 50


# ---------------------------------------------------------------------------- resting mode

RESTING = EngineConfig(resting=True)


def test_resting_order_fills_when_the_next_book_crosses_it():
    d = day(
        tick(0, bids=[(98, 5)], asks=[(102, 5)]),
        tick(1, bids=[(97, 5)], asks=[(99, 2), (101, 5)]),
    )
    bot = ScriptedBot({0: [Order("X", 100, 3)]})
    result = run_day(d, bot, RESTING)
    # The sellers at 99 would have hit the resting 100 bid, so it fills at 100 and the bot
    # doesn't see them.
    assert [(f.timestamp, f.price, f.quantity, f.source) for f in result.fills] == [(1, 100, 2, "cross")]
    assert bot.books[1]["X"].asks == ((101, 5),)
    assert bot.open_orders[1] == [OpenOrder(1, "X", 100, 1, 0)]
    assert bot.seen[1][1] == result.fills  # told about the fill straight away


def test_order_tags_reach_the_open_orders_and_fills_and_bots_see_the_day_first():
    d = day(
        tick(0, bids=[(98, 5)], asks=[(102, 5)]),
        tick(1, bids=[(97, 5)], asks=[(99, 2), (101, 5)]),
        tick(2, bids=[(97, 5)], asks=[(101, 5)]),
    )

    class Tagged(ScriptedBot):
        def begin_day(self, day):
            self.day = day

    bot = Tagged({0: [Order("X", 100, 3, tag="mine-1"), Order("X", 102, 1, tag="mine-2")]})
    result = run_day(d, bot, RESTING)
    assert bot.day is d
    assert {(f.source, f.tag) for f in result.fills} == {("book", "mine-2"), ("cross", "mine-1")}
    assert bot.open_orders[1] == [OpenOrder(1, "X", 100, 1, 0, "mine-1")]


def test_trades_at_a_crossed_level_dont_fill_the_order_again():
    d = day(
        tick(0, bids=[(98, 5)], asks=[(102, 5)]),
        # The 99 ask crosses the resting 100 bid. The trade at 99 was with those same sellers,
        # so it has nothing left for the bid; the trade at 97 was with other sellers.
        tick(1, bids=[(96, 5)], asks=[(99, 2), (101, 5)], trades=[MarketTrade("X", 99, 3), MarketTrade("X", 97, 4)]),
    )
    result = run_day(d, ScriptedBot({0: [Order("X", 100, 10)]}), RESTING)
    assert fills(result) == [(100, 2, "cross"), (100, 1, "trade"), (100, 4, "trade")]


@pytest.mark.parametrize("ioc, expected", [(False, [(101, 2, "book"), (101, 3, "cross")]), (True, [(101, 2, "book")])])
def test_new_orders_take_the_book_then_rest_unless_ioc(ioc, expected):
    d = day(tick(0, asks=[(101, 2)]), tick(1, asks=[(100, 5)]))
    result = run_day(d, ScriptedBot({0: [Order("X", 101, 5, ioc=ioc)]}), RESTING)
    assert fills(result) == expected


def test_new_order_queues_behind_the_visible_volume_at_its_price():
    d = day(
        tick(0, bids=[(100, 5)], asks=[(102, 5)], trades=[MarketTrade("X", 100, 3)]),
        tick(1, bids=[(100, 5)], asks=[(102, 5)], trades=[MarketTrade("X", 100, 4)]),
    )
    result = run_day(d, ScriptedBot({0: [Order("X", 100, 3)]}), RESTING)
    # 5 ahead: the first trade leaves 2 ahead, the second fills 4 - 2.
    assert [(f.timestamp, f.quantity, f.source) for f in result.fills] == [(1, 2, "trade")]


def test_cancellations_ahead_move_a_resting_order_up_the_queue():
    d = day(
        tick(0, bids=[(100, 5)], asks=[(102, 5)]),
        tick(1, bids=[(100, 1)], asks=[(102, 5)], trades=[MarketTrade("X", 100, 2)]),
    )
    result = run_day(d, ScriptedBot({0: [Order("X", 100, 3)]}), RESTING)
    assert fills(result) == [(100, 1, "trade")]


@pytest.mark.parametrize(
    "queue, power, filled",
    [
        (QueueModel.BACK, 1, 0),  # the 4 cancelled were behind it: 10 still ahead of the 8 traded
        (QueueModel.PROB, 1, 1),  # 10 of the 14 were ahead, so 4 * 10 / 14 of the cancels: 7 left
        (QueueModel.PROB, 20, 0),  # (10 / 14) ** 20: almost all behind, as back
        (QueueModel.FRONT, 1, 5),  # the 14 re-posted behind it
    ],
)
def test_queue_models_place_cancellations_ahead_or_behind(queue, power, filled):
    d = day(
        tick(0, bids=[(100, 10)], asks=[(102, 5)]),
        tick(1, bids=[(100, 14)], asks=[(102, 5)]),  # 4 more join behind the order
        tick(2, bids=[(100, 10)], asks=[(102, 5)], trades=[MarketTrade("X", 100, 8)]),  # 4 cancelled
    )
    config = EngineConfig(resting=True, queue=queue, queue_power=power)
    result = run_day(d, ScriptedBot({0: [Order("X", 100, 5)]}), config)
    assert sum(f.quantity for f in result.fills) == filled


def test_prob_queue_doesnt_count_traded_volume_as_cancelled():
    d = day(
        tick(0, bids=[(100, 10)], asks=[(102, 5)]),
        tick(1, bids=[(100, 14)], asks=[(102, 5)], trades=[MarketTrade("X", 100, 3)]),  # 3 traded from the front
        tick(2, bids=[(100, 11)], asks=[(102, 5)], trades=[MarketTrade("X", 100, 9)]),  # 14 - 3: nothing cancelled
    )
    config = EngineConfig(resting=True, queue=QueueModel.PROB)
    result = run_day(d, ScriptedBot({0: [Order("X", 100, 5)]}), config)
    assert sum(f.quantity for f in result.fills) == 2  # 7 still ahead of the 9 traded


@pytest.mark.parametrize(
    "matching, filled", [(TradeMatching.ALL, 2), (TradeMatching.WORSE, 0), (TradeMatching.NONE, 0)]
)
def test_price_better_than_the_book_is_first_in_the_queue(matching, filled):
    d = day(tick(0, bids=[(99, 5)], asks=[(102, 5)], trades=[MarketTrade("X", 100, 2)]))
    result = run_day(d, ScriptedBot({0: [Order("X", 100, 3)]}), EngineConfig(trade_matching=matching, resting=True))
    assert sum(f.quantity for f in result.fills) == filled


def test_trades_through_the_price_fill_whatever_is_queued():
    d = day(tick(0, bids=[(100, 50)], asks=[(102, 5)], trades=[MarketTrade("X", 99, 2, seller="S")]))
    result = run_day(d, ScriptedBot({0: [Order("X", 100, 3)]}), EngineConfig(trade_matching=TradeMatching.WORSE, resting=True))
    assert result.fills == [Fill(0, "X", 100, 2, "trade", "S", order_id=1)]


def test_own_orders_at_one_price_keep_time_priority():
    # A joins behind 10 at tick 0. Five more arrive, then B joins behind 15: the queue is
    # 10, A 5, 5, B 5, so a trade of 22 fills all of A and 2 of B.
    d = day(
        tick(0, bids=[(100, 10)], asks=[(102, 5)]),
        tick(1, bids=[(100, 15)], asks=[(102, 5)], trades=[MarketTrade("X", 100, 22)]),
    )
    result = run_day(d, ScriptedBot({0: [Order("X", 100, 5)], 1: [Order("X", 100, 5)]}), RESTING)
    assert [(f.order_id, f.quantity) for f in result.fills] == [(1, 5), (2, 2)]


def test_cancel_removes_a_resting_order():
    d = day(tick(0, bids=[(98, 5)], asks=[(102, 5)]), tick(1, asks=[(102, 5)]), tick(2, asks=[(99, 5)]))
    bot = ScriptedBot({0: [Order("X", 100, 3)], 1: [Cancel(1)]})
    result = run_day(d, bot, RESTING)
    assert result.fills == [] and result.errors == []
    assert result.cancels == [(1, 1)]
    assert bot.open_orders[1] == [OpenOrder(1, "X", 100, 3, 0)] and bot.open_orders[2] == []
    assert [(t, o.id) for t, o in result.orders] == [(0, 1)]  # working at tick 0 only


def test_resting_orders_are_listed_as_working_every_tick():
    d = day(tick(0, bids=[(98, 5)], asks=[(102, 5)]), tick(1, bids=[(98, 5)], asks=[(102, 5)]))
    result = run_day(d, ScriptedBot({0: [Order("X", 100, 3)]}), RESTING)
    assert [(t, o.id, o.quantity) for t, o in result.orders] == [(0, 1, 3), (1, 1, 3)]


@pytest.mark.parametrize("config, hint", [(RESTING, False), (EngineConfig(), True)])
def test_cancelling_an_order_that_isnt_open_is_an_error(config, hint):
    d = day(tick(0, asks=[(102, 5)]))
    result = run_day(d, ScriptedBot({0: [Cancel(7)]}), config)
    assert len(result.errors) == 1 and "order 7" in result.errors[0][1]
    assert ("resting mode" in result.errors[0][1]) == hint


def test_resting_orders_count_towards_the_limit():
    d = day(
        tick(0, bids=[(98, 5)], asks=[(102, 5)]),
        tick(1, bids=[(98, 5)], asks=[(102, 5)]),
        tick(2, bids=[(98, 5)], asks=[(102, 5)]),
        limits={"X": 10},
    )
    bot = ScriptedBot({0: [Order("X", 100, 8)], 1: [Order("X", 97, 3)]})
    result = run_day(d, bot, RESTING)
    # 8 resting + 3 new could take the position to 11: only the new order is rejected.
    assert result.limit_breaches == [(1, "X")]
    assert bot.open_orders[2] == [OpenOrder(1, "X", 100, 8, 0)]


# ---------------------------------------------------------------------------- shared market


def market(d, *bots, config=EngineConfig()):
    return run_market(d, [(f"b{i}", bot) for i, bot in enumerate(bots)], config)


def test_bots_compete_for_the_same_book_level():
    d = day(*[tick(t, asks=[(101, 3)]) for t in range(20)], limits={"X": 100})
    script = {t: [Order("X", 101, 3)] for t in range(20)}
    a, b = market(d, ScriptedBot(script), ScriptedBot(script))
    for t in range(20):  # the level fills one of them each tick
        assert sum(f.quantity for f in a.fills + b.fills if f.timestamp == t) == 3
    assert a.fills and b.fills  # who arrives first changes from tick to tick


@pytest.mark.parametrize("config", [EngineConfig(), EngineConfig(resting=True)], ids=["per tick", "resting"])
def test_a_market_trade_fills_the_better_priced_bot_first(config):
    """Two bots' bids wait for a sell at 98: the bid at 100 has priority over the bid at 99, whoever
    arrived first, in both modes."""
    d = day(tick(0, bids=[(90, 5)], asks=[(105, 5)], trades=[MarketTrade("X", 98, 1, "b", "s", 0)]), tick(100, bids=[(90, 5)], asks=[(105, 5)]))
    for seed in range(20):
        worse, better = market(d, ScriptedBot({0: [Order("X", 99, 1)]}), ScriptedBot({0: [Order("X", 100, 1)]}), config=replace(config, seed=seed))
        assert (fills(worse), fills(better)) == ([], [(100, 1, "trade")])


def test_a_market_trade_fills_bots_at_one_price_in_their_arrival_order():
    d = day(tick(0, bids=[(90, 5)], asks=[(105, 5)], trades=[MarketTrade("X", 98, 1, "b", "s", 0)]), tick(100, bids=[(90, 5)], asks=[(105, 5)]))
    winners = set()
    for seed in range(20):
        a, b = market(d, ScriptedBot({0: [Order("X", 100, 1)]}), ScriptedBot({0: [Order("X", 100, 1)]}), config=EngineConfig(seed=seed))
        assert len(a.fills) + len(b.fills) == 1
        winners.add("a" if a.fills else "b")
    assert winners == {"a", "b"}  # the arrival order is drawn each tick


def test_one_bots_leftover_orders_meet_the_trades_in_its_own_order():
    """prosperity3bt's rule, which the parity test pins: a lone bot's orders take the market trades
    in the order it sent them, not by price."""
    d = day(tick(0, bids=[(90, 5)], asks=[(105, 5)], trades=[MarketTrade("X", 98, 1, "b", "s", 0)]))
    result = run_day(d, ScriptedBot({0: [Order("X", 99, 1), Order("X", 100, 1)]}))
    assert fills(result) == [(99, 1, "trade")]


def test_bots_trade_with_each_other_at_the_resting_price():
    quiet = dict(bids=[(98, 5)], asks=[(104, 5)])
    d = day(tick(0, **quiet), tick(1, **quiet), tick(2, **quiet))
    buyer, seller, watcher = ScriptedBot({0: [Order("X", 101, 2)]}), ScriptedBot({1: [Order("X", 100, -3)]}), ScriptedBot()
    a, b, _ = market(d, buyer, seller, watcher, config=RESTING)

    assert seller.books[1]["X"].bids == ((101, 2), (98, 5))  # others' resting orders are in the book
    assert buyer.books[1]["X"].bids == ((98, 5),)  # but never your own
    assert a.fills == [Fill(1, "X", 101, 2, "trade", "b1", order_id=1)]
    assert b.fills == [Fill(1, "X", 101, -2, "book", "b0", order_id=2)]
    assert watcher.books[2]["X"].asks == ((100, 1), (104, 5))  # the seller's last unit rests
    assert watcher.seen[2][2]["X"] == [MarketTrade("X", 101, 2, "b0", "b1", 1)]
    assert "X" not in buyer.seen[2][2] and "X" not in seller.seen[2][2]  # they got fills instead


def test_losing_a_race_is_not_a_limit_breach():
    # A rests a bid for 6 at 100. At tick 1 it cancels that and bids 10 at 99, which fits the
    # position it saw (0). If B's sell reaches A's 100 bid first, A is already long 6, the cancel
    # finds nothing, and the bid for 10 is rejected as a race.
    quiet = dict(bids=[(98, 5)], asks=[(104, 5)])
    d = day(tick(0, **quiet), tick(1, **quiet), limits={"X": 10})
    raced = []
    for seed in range(10):
        a, b = market(
            d,
            ScriptedBot({0: [Order("X", 100, 6)], 1: [Cancel(1), Order("X", 99, 10)]}),
            ScriptedBot({1: [Order("X", 100, -6)]}),
            config=EngineConfig(resting=True, seed=seed),
        )
        assert a.errors == [] and a.limit_breaches == [] and max(a.positions["X"]) <= 10
        raced.append(a.races == [(1, "X")] and a.positions["X"][-1] == 6)
    assert any(raced) and not all(raced)


def test_breaching_the_position_you_saw_is_still_a_breach():
    d = day(tick(0, asks=[(104, 5)]), limits={"X": 2})
    a, _ = market(d, ScriptedBot({0: [Order("X", 99, 3)]}), ScriptedBot())
    assert a.limit_breaches == [(0, "X")] and a.races == []


def test_market_names_must_be_unique():
    with pytest.raises(ValueError, match="unique"):
        run_market(day(tick(0)), [("a", ScriptedBot()), ("a", ScriptedBot())])


def test_a_delay_sends_orders_to_a_later_ticks_book():
    # A buy at 101 decided on tick 0 meets tick 1's book, where the ask has moved to 103: no fill.
    d = day(tick(0, asks=[(101, 5)]), tick(100, asks=[(103, 5)]), tick(200, asks=[(101, 5)]))
    script = {0: [Order("X", 101, 2)]}
    assert fills(run_day(d, ScriptedBot(script))) == [(101, 2, "book")]
    late = ScriptedBot(script)
    result = run_day(d, late, EngineConfig(delay=1))
    assert fills(result) == [] and result.orders[0][0] == 100  # placed when it reached the exchange
    # Two ticks late it meets tick 2's ask at 101 again, and the bot learns of the fill on no earlier tick.
    later = ScriptedBot(script)
    assert fills(run_day(d, later, EngineConfig(delay=2))) == [(101, 2, "book")]
    assert [len(own) for _, own, _ in later.seen] == [0, 0, 0]


def test_an_order_that_fills_before_its_late_cancel_lands_makes_a_race_not_a_breach():
    # A resting bid of the full room, cancelled at 200 and replaced lower; a trade fills it at the end of 200,
    # before the cancel arrives at 300. The bot's orders fit what it saw (it cancelled the bid), so the
    # rejection is a race: the fill moved its position since (the 2026-10-31 template's DELAY check).
    d = day(*[tick(t, bids=[(97, 5)], asks=[(102, 5)], trades=[MarketTrade("X", 99, 10)] if t == 200 else ()) for t in range(0, 500, 100)])
    script = {0: [Order("X", 99, 10)], 200: [Cancel(1), Order("X", 98, 10)]}
    result = run_day(d, ScriptedBot(script), EngineConfig(resting=True, delay=1))
    assert fills(result) == [(99, 10, "trade")]
    assert result.limit_breaches == [] and result.races == [(300, "X")]


def test_a_delayed_order_meets_that_ticks_market_trades():
    # A bid at 100 decided on tick 0, which has no trades; a sell prints at 100 on tick 1.
    d = day(tick(0, bids=[(99, 5)], asks=[(102, 5)]), tick(100, bids=[(99, 5)], asks=[(102, 5)], trades=[MarketTrade("X", 100, 3)]))
    script = {0: [Order("X", 100, 3)]}
    assert fills(run_day(d, ScriptedBot(script))) == []
    assert fills(run_day(d, ScriptedBot(script), EngineConfig(delay=1))) == [(100, 3, "trade")]
