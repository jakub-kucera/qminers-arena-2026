import pytest

from arena.model import Book, Day, MarketTrade, Tick
from arena.stress import permute, perturb


def flat_day(n=10):
    """A product at 100 with walls at 98 / 102 and a small order inside, one trade each tick."""
    ticks = [
        Tick(t * 100, {"X": Book(((99, 2), (98, 20)), ((102, 20),))}, {"X": [MarketTrade("X", 102, 1)]}, {"X": 100.5})
        for t in range(n)
    ]
    return Day("d", ["X"], {"X": 10}, ticks)


def prices(day):
    return [t.books["X"].asks[0][0] for t in day.ticks]


def test_a_shift_moves_book_trades_and_mark_together_from_mid_day():
    shifted = perturb(flat_day(), "shift_up")
    # The median spread is 3 (99 to 102), so the shift is 5 x 3 = 15 from tick 5 on.
    assert prices(shifted) == [102] * 5 + [117] * 5
    assert shifted.ticks[7].trades["X"][0].price == 117 and shifted.ticks[7].marks["X"] == 115.5
    assert shifted.ticks[7].books["X"].bids == ((114, 2), (113, 20))


def test_trends_and_spikes():
    assert prices(perturb(flat_day(), "trend_down"))[-1] == 102 - 30
    spike = perturb(flat_day(400), "spike_up")
    assert prices(spike)[199] == 102 and prices(spike)[200] == 117 and prices(spike)[300] == 102


def test_offsets_stay_on_the_products_tick_grid():
    # Prices in cents with a five-cent tick (the drill format): a trend of 10 x the 15-cent median
    # spread moves the book in whole ticks, never to 101.42.
    ticks = [Tick(t * 100, {"X": Book(((9995, 2), (9990, 20)), ((10010, 20),))}, {}, {}) for t in range(7)]
    day = perturb(Day("d", ["X"], {"X": 10}, ticks), "trend_up")
    assert all(p % 5 == 0 for t in day.ticks for b in t.books.values() for p, _ in b.bids + b.asks)
    assert prices(day)[-1] == 10010 + 150


def test_no_wall_removes_the_largest_level_in_the_middle_fifth():
    day = perturb(flat_day(), "no_wall")
    assert day.ticks[4].books["X"].bids == ((99, 2),)
    assert day.ticks[4].books["X"].asks == ((102, 20),)  # a lone level is kept
    assert day.ticks[0].books["X"].bids == ((99, 2), (98, 20))


def test_vol2_doubles_the_distance_from_the_first_wall_mid():
    day = flat_day(3)
    moved = Tick(200, {"X": Book(((102, 20),), ((106, 20),))}, {}, {})
    day = Day("d", ["X"], {"X": 10}, day.ticks[:2] + [moved])
    assert perturb(day, "vol2").ticks[2].books["X"].asks == ((110, 20),)


def test_unknown_perturbation():
    with pytest.raises(ValueError, match="unknown perturbation"):
        perturb(flat_day(), "nope")


def walking_day(n=40):
    """Two products whose walls step up one tick per tick, with a trade at the wall each tick."""
    ticks = []
    for t in range(n):
        books = {p: Book(((90 + base + t, 20), (91 + base + t, 2)), ((95 + base + t, 20),)) for p, base in (("X", 0), ("Y", 50))}
        books = {p: Book(tuple(sorted(b.bids, reverse=True)), b.asks) for p, b in books.items()}
        trades = {p: [MarketTrade(p, 95 + base + t, 1, timestamp=t * 100)] for p, base in (("X", 0), ("Y", 50))}
        ticks.append(Tick(t * 100, books, trades, {"X": 92.5 + t, "Y": 142.5 + t}))
    return Day("d", ["X", "Y"], {"X": 10, "Y": 10}, ticks)


def wall_bids(day, p):
    return [max(t.books[p].bids, key=lambda level: level[1])[0] for t in day.ticks]


def test_permute_keeps_each_tick_and_its_move_and_the_ends():
    day = walking_day()
    copy = permute(day, seed=3)
    assert [t.timestamp for t in copy.ticks] == [t.timestamp for t in day.ticks]
    for p in ("X", "Y"):
        bids = wall_bids(copy, p)
        assert bids[-1] == wall_bids(day, p)[-1] and abs(bids[0] - wall_bids(day, p)[0]) <= 1  # the same end, a start one move away
        steps = [b - a for a, b in zip(bids, bids[1:])]
        assert set(steps) <= {0, 1} and steps.count(0) <= 1  # every move is a real one; the first tick has none (0)
    for t in copy.ticks:  # each tick's book keeps its shape, its trades sit where they did and carry the new time
        book = t.books["X"]
        assert [price - book.asks[0][0] for price, _ in book.bids] == [-4, -5]
        assert [trade.price for trade in t.trades["X"]] == [book.asks[0][0]]
        assert all(trade.timestamp == t.timestamp for trade in t.trades["X"])
        assert t.books["Y"].asks[0][0] - book.asks[0][0] == 50  # the products' ticks stay together


def test_permute_shuffles_in_runs_and_is_seeded():
    day = flat_day(30)
    for t, k in zip(day.ticks, range(30)):  # tag each tick by its trade quantity
        t.trades["X"][0] = MarketTrade("X", 102, k + 1)
    order = [t.trades["X"][0].quantity - 1 for t in permute(day, seed=1, block=5).ticks]
    assert sorted(order) == list(range(30)) and order != list(range(30))
    assert all(b - a == 1 for run in range(6) for a, b in zip(order[run * 5 : run * 5 + 4], order[run * 5 + 1 : run * 5 + 5]))
    assert order == [t.trades["X"][0].quantity - 1 for t in permute(day, seed=1, block=5).ticks]
    assert [t.trades["X"][0].quantity for t in permute(day, seed=1, block=30).ticks] == list(range(1, 31))


def test_the_cli_prints_each_failing_runs_first_error(data_dir, tmp_path, capsys):
    """The 2026-10-26 dry run saw only a count of errors; the cause (a perturbation pushing a price
    where the bot fails) took a script to find."""
    from arena import stress

    bot = tmp_path / "bot.py"
    bot.write_text(
        "from datamodel import Order\n"
        "class Trader:\n"
        "    def run(self, state):\n"
        "        if min(state.order_depths['KELP'].sell_orders) > 2040:\n"
        "            raise ValueError('ask too high')\n"
        "        return {}, 0, ''\n"
    )
    code = stress.main([str(bot), "1", "--data", str(data_dir), "--only", "trend_up", "--jobs", "1"])
    out = capsys.readouterr().out
    assert code == 1 and "trend_up: 1 errors, first: ValueError: ask too high" in out and "plain:" not in out
