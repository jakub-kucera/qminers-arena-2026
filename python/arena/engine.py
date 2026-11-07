"""Replays a Day against a bot and simulates its fills.

Default rules follow IMC Prosperity and were checked fill-for-fill against jmerle's prosperity3bt:
  1. Every tick the bot sees the book and returns orders.
  2. If a product's orders could breach its position limit (all its buys, or all its sells,
     filling), every order for that product is cancelled.
  3. Each order trades against the visible book at the book's prices, best price first.
  4. What's left can fill against that tick's market trades, at the order's own price
     (see TradeMatching).
  5. Anything still unfilled is cancelled: no order rests into the next tick.

Resting mode (EngineConfig.resting) replaces rule 5 with an exchange where orders stay on the
book until they fill or the bot cancels them. Its queue model estimates fills for orders that
aren't in the recorded data:
  - A new order takes what it can from the visible book (rule 3). The rest rests, unless the
    order is ioc. It joins the back of the queue: the visible volume at its price is ahead of it.
  - Market trades at the order's price first use up the volume ahead of it, then fill it.
    Trades at a worse price fill it straight away (it would have traded first). Fills are at
    the order's price. TradeMatching worse / none turn off fills from trades at / at any price.
  - When a new snapshot shows the other side at or through a resting order's price, those
    orders would have hit it: it fills at its own price against that volume, and the bot sees
    the snapshot without it. That tick's market trades at the crossed prices lose the same
    volume, since they traded with those same orders.
  - If the visible volume at the order's price drops below the volume counted ahead of it,
    orders ahead of it were cancelled, so it moves up. An emptied level puts it at the front.
    That is EngineConfig.queue "back", the pessimistic end: a cancellation is always behind it.
    "prob" splits each decrease of the level that trades don't explain between the volume
    ahead and behind: a share x**n lands ahead, x being the share of the level ahead of it and
    n queue_power (hftbacktest's ProbQueueModel with PowerProbQueueFunc3; n = 1 is uniform,
    a large n tends to "back"). "front", the optimistic end: everyone else at its price
    re-posts every tick, so from the snapshot after it was placed nothing is ahead of it.
    Queue position only matters under TradeMatching.ALL: trades through its price and
    crossing snapshots fill it whatever is ahead.
  - The limit check (rule 2) counts resting orders, and only rejects that tick's new orders.
  - Your own orders never trade with each other.
Positions are valued at each tick's mark price: the data's, else the book's mid (EngineConfig.mark
"mid"). For an exchange that scores another way (the Arena's portal shows a "mark-out price" and a
"position-limit penalty", ON_THE_DAY.md, "Known so far"), two settings change rule 2 and the mark:
  - mark "touch": a long position is valued at the best bid, a short one at the best ask, what it
    would fetch at once (the mark when that side is empty); "last": at the product's last market
    trade in the data (the mark until its first).
  - limit_penalty: no order is rejected for the limit (rule 2 is off). After each tick's fills,
    every lot of a position beyond its limit costs this much, charged to that product, and the
    tick counts as a breach. Like `fee` below, it is in the data's price units (price_units).
Fees (EngineConfig.fee, fee_bps): each fill costs `fee` a lot and `fee_bps` basis points of its
value, charged to the product's cash as it settles, the same for every participant and for passive
and aggressive fills alike. `fee` is in the data's price units, as a person reads the rules: with a
format's decimal prices (Day.info's `unit`, e.g. 0.01) a fee of 0.01 is one engine unit a lot.
0 is Prosperity's rule. `maker_fee` and `maker_fee_bps`, when set, replace them for passive fills
(a fill's source "trade" or "cross": the resting side; "book" took a level, the aggressor), and may
be negative, a rebate: Ready Trader Go charged takers 2 bps and paid makers 1. `order_fee` is charged
for each new order the exchange accepts (after the caps and the limit check), filled or not, in the
same units: the 2026-11-03 rehearsal's portal charged 0.5 cents an order, 28% of the bot's gross.
Print share (EngineConfig.print_share): each market trade offers our orders only this share of its
volume, rounded down, the same every time (fill_ratio's draws are random and thin the book too):
the 2026-11-03 rehearsal's portal gave resting orders half of each print, as if the rest went to
orders its book didn't show. The bots still see each trade whole, less what our orders took. 1 is Prosperity's rule.
Latency (EngineConfig.delay): with delay n, what a bot returns at tick t reaches the
exchange n ticks later: it meets tick t+n's book and market trades (and, per tick, dies there).
Its limits are checked twice, as without a delay: against the position the bot saw when it decided
(a breach; the orders it cancels count as gone, even one that filled before the cancel arrived), then
against the position when it arrives, which the fills of its own earlier late orders have moved since (a race). Either rejects every new order for that product, as Prosperity
does, so a bot that quotes all the room under its limit loses many ticks to races: one tick late,
the template races on 3,248 of day 0's 10,000 ticks on P3 round 1. The bot is called before that
tick's late orders are matched, so it never learns of a tick's trades before the next. For an
exchange that applies orders a step late (probe 3); 0 is Prosperity's rule.
Depletion (EngineConfig.deplete): a replay may keep what we took off its book ("they only consume
the liquidity they trade against"). With deplete, the lots a take removes from the recorded book
stay missing from that price level in later snapshots, for every participant, while the recording
shows more there than we left; once its volume falls to what we left or below, or the level goes,
the recording's level stands again. Only takes from the recorded book count, not fills on another
bot's order or a resting order's cross. Off is Prosperity's rule: each snapshot as recorded.
Order caps (EngineConfig.max_orders): a bot may send this many new orders a tick (cancels don't
count); the rest, in the order it sent them, are dropped and the tick logs an error, as an exchange
that refuses or disconnects past its rate limit would (AlgoTrade closed the connection above 500
messages a second). None, Prosperity's rule, takes them all. Two more caps an exchange may set
(the 2026-10-28 rehearsal's rules had both): EngineConfig.max_actions caps everything a bot sends
a tick, cancels included, keeping the first in the order sent; EngineConfig.max_resting caps the
orders a product may have working at once, the ones kept from earlier ticks first, then the new
orders that would rest (immediate-or-cancel ones don't count), in the order sent. What is over
either cap is dropped, an error.
"""

from __future__ import annotations

import io
import random
import time
import traceback
from collections import Counter, defaultdict, deque
from contextlib import nullcontext, redirect_stdout
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Protocol

from arena.model import Book, Cancel, Day, Fill, MarketTrade, OpenOrder, Order, Tick


class QueueModel(StrEnum):
    """Resting mode: where the other orders' cancellations at a resting order's price fall."""

    BACK = "back"  # always behind it: it only moves up as far as the visible volume forces
    PROB = "prob"  # split by its place in the queue (EngineConfig.queue_power)
    FRONT = "front"  # the others re-post every tick, behind it: nothing ahead after one snapshot


class Mark(StrEnum):
    """The price a position is valued at each tick (EngineConfig.mark; see the module docstring)."""

    MID = "mid"  # the data's mark, else the book's mid
    TOUCH = "touch"  # long at the best bid, short at the best ask: what closing it would fetch
    LAST = "last"  # the product's last market trade in the data


class TradeMatching(StrEnum):
    """Which market trades an order can fill against once the visible book is exhausted."""

    ALL = "all"  # trades at the order's price or worse (in resting mode, after the queue ahead)
    WORSE = "worse"  # only trades strictly worse than the order's price (more conservative)
    NONE = "none"  # none: fills come from the visible book only


@dataclass(frozen=True)
class EngineConfig:
    trade_matching: TradeMatching = TradeMatching.ALL
    resting: bool = False  # orders rest until filled or cancelled (see the module docstring)
    queue: QueueModel = QueueModel.BACK  # resting mode: how a resting order moves up its queue
    queue_power: float = 1.0  # queue "prob": a decrease lands ahead with probability x**n
    # Share of each book level and market trade available to us. Below 1 it approximates other
    # teams competing for the same liquidity: each unit is available with this probability.
    # The draws are seeded and don't depend on the bot's orders, so variants of a bot see the
    # same liquidity and can be compared fairly.
    fill_ratio: float = 1.0
    seed: int = 0
    mark: Mark = Mark.MID  # the price positions are valued at (see the module docstring)
    limit_penalty: float | None = None  # None: rule 2, as Prosperity; a number: charge each lot beyond a limit this much a tick
    capture_output: bool = True  # hide the bot's prints (their size is still measured)
    delay: int = 0  # ticks between a bot's decision and its orders reaching the exchange (see the module docstring)
    fee: float = 0.0  # charged per lot filled (see the module docstring)
    fee_bps: float = 0.0  # charged per fill, in basis points of its value
    maker_fee: float | None = None  # a passive fill's fee a lot instead of fee (negative: a rebate)
    maker_fee_bps: float | None = None  # a passive fill's basis points instead of fee_bps (negative: a rebate)
    deplete: bool = False  # volume taken from the recorded book stays gone from later snapshots (see the module docstring)
    max_orders: int | None = None  # new orders a bot may send a tick; the rest are dropped, an error (see the module docstring)
    max_actions: int | None = None  # orders and cancels a bot may send a tick; the rest are dropped, an error
    max_resting: int | None = None  # orders a product may have working at once; new ones beyond are dropped, an error
    order_fee: float = 0.0  # charged per new order the exchange accepts, filled or not (see the module docstring)
    print_share: float = 1.0  # the share of each market trade, rounded down, our orders may take (see the module docstring)


class Bot(Protocol):
    def step(
        self,
        tick: Tick,
        positions: dict[str, int],
        own_fills: list[Fill],
        market_trades: dict[str, list[MarketTrade]],
        open_orders: list[OpenOrder],
    ) -> list[Order | Cancel]:
        """Returns this tick's new orders and cancels.

        own_fills are the fills since the last call, market_trades the previous tick's.
        open_orders are the bot's resting orders, always empty unless the engine is in resting mode.
        An order's tag comes back unread on its OpenOrder and Fills. A bot may also define
        begin_day(day), which is called with the Day (and its per-product info) before the first tick.
        """
        ...


@dataclass
class DayResult:
    day: str
    products: list[str]
    limits: dict[str, int]
    timestamps: list[int] = field(default_factory=list)
    # Per product, one value per tick, recorded after that tick's fills.
    positions: dict[str, list[int]] = field(default_factory=dict)
    marks: dict[str, list[float]] = field(default_factory=dict)
    pnl: dict[str, list[float]] = field(default_factory=dict)
    best_bids: dict[str, list[float | None]] = field(default_factory=dict)  # None: that side was empty
    best_asks: dict[str, list[float | None]] = field(default_factory=dict)
    wall_mids: dict[str, list[float | None]] = field(default_factory=dict)  # Book.wall_mid; None: a side was empty
    # (timestamp, trade) for every market trade in the data, as recorded: not the trades between
    # bots in a shared market, and not reduced by this bot's fills against them.
    market_trades: list[tuple[int, MarketTrade]] = field(default_factory=list)
    # (timestamp, order) for every order working during that tick, before its fills: placed then
    # (after the limit check), or resting from earlier.
    orders: list[tuple[int, OpenOrder]] = field(default_factory=list)
    cancels: list[tuple[int, int]] = field(default_factory=list)  # (timestamp, order id)
    fills: list[Fill] = field(default_factory=list)
    errors: list[tuple[int, str]] = field(default_factory=list)  # (timestamp, traceback or message)
    limit_breaches: list[tuple[int, str]] = field(default_factory=list)  # (timestamp, product)
    # (timestamp, product): new orders rejected because another bot filled one of this bot's
    # orders after it decided. They fitted the position it saw, so this isn't a bug.
    races: list[tuple[int, str]] = field(default_factory=list)
    step_seconds: list[float] = field(default_factory=list)
    max_output_chars: int = 0
    units: dict[str, float] = field(default_factory=dict)  # price_units: what a rate in the currency is per engine unit (1 if absent)


@dataclass
class _Live:
    """An accepted order inside the engine."""

    id: int
    product: str
    price: float
    quantity: int  # left to fill, signed
    timestamp: int
    owner: int = 0  # index of the participant that placed it
    ahead: int = 0  # resting mode: recorded volume queued in front of it at its price
    seen: int = 0  # resting mode: the visible volume at its price in the last snapshot
    traded: int = 0  # resting mode: market trades at its price since then that used up volume ahead
    tag: str = ""  # Order.tag, passed through

    def view(self) -> OpenOrder:
        return OpenOrder(self.id, self.product, self.price, self.quantity, self.timestamp, self.tag)


@dataclass
class _Participant:
    name: str
    bot: Bot
    result: DayResult
    position: dict[str, int]
    cash: dict[str, float]
    unseen_fills: list[Fill] = field(default_factory=list)  # fills the bot hasn't been shown yet
    market_trades: dict[str, list[MarketTrade]] = field(default_factory=dict)  # what it sees next tick


def run_day(day: Day, bot: Bot, config: EngineConfig = EngineConfig()) -> DayResult:
    return run_market(day, [("you", bot)], config)[0]


def run_market(day: Day, bots: list[tuple[str, Bot]], config: EngineConfig = EngineConfig()) -> list[DayResult]:
    """Replays a day with several bots trading in one market. Returns a result per bot, in order.

    The bots compete for the recorded book and market trades, and trade with each other:
      - Every tick they all see the same market and decide at once. Their orders then reach the
        exchange in a random order, seeded and drawn again every tick.
      - A new order trades with the recorded book and the other bots' orders, best price first.
        At one price the recorded volume goes first, then the bots' orders, oldest first.
        Fills are at the price of the order that was there first.
      - What's left meets the tick's market trades as an exchange would queue it: each trade
        fills the orders it reaches best price first, then oldest, whoever arrived first.
      - The book a bot sees includes the other bots' resting orders, never its own. Trades
        between other bots show up in its market trades, with the bots' names.
    With one bot this is exactly the single-bot engine, whose leftover orders take the trades in
    the order the bot sent them (prosperity3bt's rule, pinned by the parity test).
    """
    names = [name for name, _ in bots]
    if len(set(names)) != len(names):
        raise ValueError(f"participant names must be unique: {names}")
    # Separate random streams, so the liquidity draws don't depend on the number of bots.
    rng = random.Random(config.seed)
    arrival = random.Random(f"arrival-{config.seed}")
    players = [
        _Participant(name, bot, new_result(day), dict.fromkeys(day.products, 0), dict.fromkeys(day.products, 0.0))
        for name, bot in bots
    ]
    for _, bot in bots:
        if hasattr(bot, "begin_day"):
            bot.begin_day(day)
    mark = dict.fromkeys(day.products, 0.0)
    last: dict[str, float | None] = dict.fromkeys(day.products)  # Mark.LAST: each product's last market trade
    resting: list[_Live] = []
    owner: dict[int, int] = {}  # order id -> participant index
    next_id = 1
    # With a delay, each tick's decisions wait here until they reach the exchange.
    late = deque(([[] for _ in players], [(dict(p.position), []) for p in players]) for _ in range(config.delay)) if config.delay else None

    # The fee and the limit penalty a lot in engine units (see price_units).
    unit = price_units(day)
    lot_fee = {p: config.fee / unit[p] for p in day.products}
    maker_lot_fee = {p: config.maker_fee / unit[p] for p in day.products} if config.maker_fee is not None else None
    order_cost = {p: config.order_fee / unit[p] for p in day.products}
    penalty = {p: config.limit_penalty / unit[p] for p in day.products} if config.limit_penalty is not None else None

    def settle(fills: list[Fill]) -> None:
        for fill in fills:
            player = players[owner[fill.order_id]]
            player.position[fill.product] += fill.quantity
            player.cash[fill.product] -= fill.price * fill.quantity
            passive = fill.source != "book"
            if passive and maker_lot_fee is not None:
                player.cash[fill.product] -= maker_lot_fee[fill.product] * abs(fill.quantity)
            elif config.fee:
                player.cash[fill.product] -= lot_fee[fill.product] * abs(fill.quantity)
            if passive and config.maker_fee_bps is not None:
                player.cash[fill.product] -= config.maker_fee_bps * abs(fill.price * fill.quantity) / 10_000
            elif config.fee_bps:
                player.cash[fill.product] -= config.fee_bps * abs(fill.price * fill.quantity) / 10_000
            player.result.fills.append(fill)
            player.unseen_fills.append(fill)

    missing: dict[tuple[str, bool, float], list[int]] = {}  # deplete: (product, ask side, price) -> [lots taken, lots left]

    for tick in day.ticks:
        if config.deplete:
            tick = _deplete(tick, missing)
        taken_now: dict[tuple[str, bool, float], int] = defaultdict(int)
        books, trades = _liquidity(tick, config.fill_ratio, rng, config.print_share)
        if resting:
            crossed, taken = _cross(resting, books, tick.timestamp)
            _spend_crossed(trades, taken)
            _requeue(resting, tick.books, config.queue, config.queue_power)
            tick = _without(tick, taken)
            resting = [order for order in resting if order.quantity]
            settle(crossed)

        actions, decided = [], []
        for i, player in enumerate(players):
            mine = [order.view() for order in resting if order.owner == i]
            seen = _seen_by(tick, resting, i)
            actions.append(call_bot(player.bot, seen, player.position, player.unseen_fills, player.market_trades, mine, config, player.result))
            decided.append((dict(player.position), mine))  # what the bot based its orders on
            player.unseen_fills = []
        if late is not None:
            late.append((actions, decided))
            actions, decided = late.popleft()  # what was decided config.delay ticks ago arrives now

        working = list(resting)  # every order on the book this tick, oldest first
        between: list[MarketTrade] = []  # trades between participants
        order_of_arrival = list(range(len(players)))
        arrival.shuffle(order_of_arrival)
        for i in order_of_arrival:
            player = players[i]
            seen_position, seen = decided[i]
            mine = [order for order in working if order.owner == i]
            sent = actions[i]
            if config.max_actions is not None and len(sent) > config.max_actions:
                player.result.errors.append((tick.timestamp, f"action cap: {len(sent) - config.max_actions} of {len(sent)} actions over --max-actions {config.max_actions} dropped"))
                sent = sent[:config.max_actions]
            orders, cancelled, kept = _cancel(sent, mine, {o.id for o in seen}, config.resting, tick.timestamp, player.result)
            working = [order for order in working if order.id not in cancelled]
            orders = known(orders, day.limits, tick.timestamp, player.result)
            if config.max_orders is not None and len(orders) > config.max_orders:
                player.result.errors.append((tick.timestamp, f"order cap: {len(orders) - config.max_orders} of {len(orders)} new orders over --max-orders {config.max_orders} dropped"))
                orders = orders[:config.max_orders]
            if config.max_resting is not None:
                orders = _resting_cap(orders, kept, config.max_resting, tick.timestamp, player.result)
            if config.limit_penalty is None:
                # Orders that don't fit the position the bot saw are its bug. Orders that did fit, but
                # no longer do because another bot filled one of its orders since, lost a race.
                # Both are rejected, as Prosperity does: every new order for that product. What the bot
                # cancels is gone from what it saw, even an order that filled before the cancel arrived:
                # that fill moved the position since, a race.
                asked = {action.order_id for action in sent if isinstance(action, Cancel)}
                breached = breaches(orders, seen_position, [o for o in seen if o.id not in asked], day.limits)
                raced = breaches(orders, player.position, kept, day.limits) - breached
                player.result.limit_breaches.extend((tick.timestamp, product) for product in sorted(breached))
                player.result.races.extend((tick.timestamp, product) for product in sorted(raced))
                orders = [order for order in orders if order.product not in breached | raced]
            placed = [_Live(next_id + k, o.product, o.price, o.quantity, tick.timestamp, i, tag=o.tag) for k, o in enumerate(orders)]
            next_id += len(placed)
            owner.update((order.id, i) for order in placed)
            if config.order_fee:
                for order in placed:
                    player.cash[order.product] -= order_cost[order.product]
            player.result.orders.extend((tick.timestamp, order.view()) for order in kept + placed)
            for order, live in zip(orders, placed):
                # Settled straight away: a fill on another bot's resting order changes its
                # position before its own new orders meet the limit check.
                took = _take(live, books, working, names, tick.timestamp, between)
                for fill in took:
                    if fill.source == "book" and not fill.counterparty:  # from the recorded book, not another bot's order
                        taken_now[(fill.product, fill.quantity > 0, fill.price)] += abs(fill.quantity)
                settle(took)
                if live.quantity and not (config.resting and order.ioc):
                    live.ahead = live.seen = _volume_at(live, tick.books)
                    working.append(live)  # in the default mode, only until the end of this tick

        if config.resting:
            settle(_fill_resting(working, trades, config.trade_matching, tick.timestamp))
            resting = [order for order in working if order.quantity]
        elif len(players) == 1:
            # One bot's leftover orders take the trades in the order it sent them: prosperity3bt's rule.
            settle([fill for order in working for fill in _take_trades(order, trades, config.trade_matching, tick.timestamp)])
        else:
            settle(_match_trades(working, trades, config.trade_matching, tick.timestamp))
        for key, lots in taken_now.items() if config.deplete else ():
            product, ask, price = key
            shown = next((v for p, v in (tick.books[product].asks if ask else tick.books[product].bids) if p == price), 0)
            entry = missing.setdefault(key, [0, 0])
            entry[0] += lots
            entry[1] = max(shown - lots, 0)
        remaining = _remaining_trades(trades)
        for player in players:
            player.market_trades = _market_view(remaining, between, player.name)

        for product in day.products:
            mark[product] = _mark(tick, product, mark[product])
            if tick.trades.get(product):
                last[product] = float(tick.trades[product][-1].price)
        for player in players:
            if penalty is not None:
                _charge(player, day.limits, penalty, tick.timestamp)
            record(player, tick, mark if config.mark is Mark.MID else _valued(player.position, tick, mark, last, config.mark))

    return [player.result for player in players]


def _charge(player: _Participant, limits: dict[str, int], rate: dict[str, float], timestamp: int) -> None:
    """EngineConfig.limit_penalty: each lot of a position beyond its limit costs its product's `rate`, this tick."""
    for product in sorted(player.position):
        over = abs(player.position[product]) - limits[product]
        if over > 0:
            player.cash[product] -= rate[product] * over
            player.result.limit_breaches.append((timestamp, product))


def _valued(position: dict[str, int], tick: Tick, mark: dict[str, float], last: dict[str, float | None], how: Mark) -> dict[str, float]:
    """The prices one participant's positions are valued at this tick, by EngineConfig.mark."""
    if how is Mark.LAST:
        return {p: mark[p] if last[p] is None else last[p] for p in mark}
    out = {}
    for p, value in mark.items():
        book = tick.books.get(p)
        levels = (book.bids if position[p] > 0 else book.asks if position[p] < 0 else ()) if book is not None else ()
        out[p] = float(levels[0][0]) if levels else value
    return out


# Public, since arena.sim's market runs bots with them too (python/arena/sim.py): new_result, record,
# call_bot, known and breaches. The rest of this module is private to it.


def price_units(day: Day) -> dict[str, float]:
    """Per product, the currency one engine price unit is worth, for rates given in the currency (--fee,
    --maker-fee, --limit-penalty): Day.info's unit for decimal prices (0.01 if a tick is given without one,
    as python/arena/rust.py exports it), else 1 (the data's own integer prices)."""
    return {p: day.info[p].get("unit", 0.01) if "tick" in day.info.get(p, {}) else 1 for p in day.products}


def new_result(day: Day) -> DayResult:
    return DayResult(
        day.name,
        day.products,
        day.limits,
        positions={product: [] for product in day.products},
        marks={product: [] for product in day.products},
        pnl={product: [] for product in day.products},
        best_bids={product: [] for product in day.products},
        best_asks={product: [] for product in day.products},
        wall_mids={product: [] for product in day.products},
        units=price_units(day),
    )


def record(player: _Participant, tick: Tick, mark: dict[str, float]) -> None:
    result = player.result
    result.timestamps.append(tick.timestamp)
    for product in result.products:
        result.positions[product].append(player.position[product])
        result.marks[product].append(mark[product])
        result.pnl[product].append(player.cash[product] + player.position[product] * mark[product])
        book = tick.books.get(product)
        result.best_bids[product].append(book.bids[0][0] if book and book.bids else None)
        result.best_asks[product].append(book.asks[0][0] if book and book.asks else None)
        result.wall_mids[product].append(book.wall_mid if book else None)
    result.market_trades.extend((tick.timestamp, trade) for trades in tick.trades.values() for trade in trades)


def call_bot(bot, tick, position, own_fills, market_trades, open_orders, config, result) -> list[Order | Cancel]:
    output = io.StringIO()
    start = time.perf_counter()
    try:
        with redirect_stdout(output) if config.capture_output else nullcontext():
            actions = bot.step(tick, dict(position), own_fills, market_trades, open_orders)
    except Exception:
        actions = []
        result.errors.append((tick.timestamp, traceback.format_exc()))
    result.step_seconds.append(time.perf_counter() - start)
    result.max_output_chars = max(result.max_output_chars, len(output.getvalue()))
    return actions


def _cancel(actions, resting: list[_Live], seen: set[int], resting_mode: bool, timestamp, result):
    """Applies the cancels. Returns the new orders, the ids cancelled, and the orders still resting.

    seen holds the ids of the orders that were open when the bot decided. Cancelling one that has
    filled since does nothing, as on an exchange. Cancelling any other id is an error.
    """
    cancelled = set()
    live_ids = {order.id for order in resting}
    for action in actions:
        if not isinstance(action, Cancel):
            continue
        if action.order_id in live_ids - cancelled:
            cancelled.add(action.order_id)
            result.cancels.append((timestamp, action.order_id))
        elif action.order_id not in seen:
            hint = "" if resting_mode else " (orders only rest in resting mode)"
            result.errors.append((timestamp, f"cancel for order {action.order_id}, which isn't open{hint}"))
    orders = [action for action in actions if not isinstance(action, Cancel)]
    return orders, cancelled, [order for order in resting if order.id not in cancelled]


def _resting_cap(orders, kept, cap: int, timestamp, result) -> list[Order]:
    """The new orders within each product's cap on working orders: its kept ones count first, then each new
    order that would rest, in the order sent; immediate-or-cancel orders pass. Each product over it is an error."""
    working = Counter(order.product for order in kept)
    out, dropped = [], Counter()
    for order in orders:
        if not order.ioc:
            if working[order.product] >= cap:
                dropped[order.product] += 1
                continue
            working[order.product] += 1
        out.append(order)
    for product in sorted(dropped):
        result.errors.append((timestamp, f"resting cap: {dropped[product]} new orders for {product} over --max-resting {cap} dropped"))
    return out


def known(orders, limits, timestamp, result) -> list[Order]:
    """Drops empty orders, and orders for unknown products (an error)."""
    for order in orders:
        if order.product not in limits:
            result.errors.append((timestamp, f"order for unknown product {order.product!r}"))
    return [order for order in orders if order.product in limits and order.quantity != 0]


def breaches(orders, position, resting, limits) -> set[str]:
    """Products whose new orders could breach the limit: all their buys, or all their sells, filling.

    Resting orders (anything with .product and .quantity) count too. They always fit on their
    own, as fills move the position and shrink the order by the same amount.
    """
    buys: dict[str, int] = defaultdict(int)
    sells: dict[str, int] = defaultdict(int)
    for order in [*orders, *resting]:
        if order.quantity > 0:
            buys[order.product] += order.quantity
        else:
            sells[order.product] -= order.quantity
    return {
        product
        for product in {order.product for order in orders}
        if position[product] + buys[product] > limits[product]
        or position[product] - sells[product] < -limits[product]
    }


def _liquidity(tick: Tick, fill_ratio: float, rng: random.Random, print_share: float = 1.0):
    """Mutable copies of what this tick's orders can trade against.

    Books become [price, volume] levels. Market trades become
    [trade, available volume, left for our buys, left for our sells]: our buy takes the
    trade's seller, our sell takes its buyer.
    """

    def available(volume: int) -> int:
        return volume if fill_ratio >= 1 else rng.binomialvariate(volume, fill_ratio)

    books = {}
    for product in sorted(tick.books):
        book = tick.books[product]
        books[product] = (
            [[price, available(volume)] for price, volume in book.bids],
            [[price, available(volume)] for price, volume in book.asks],
        )

    trades = {}
    for product in sorted(tick.trades):
        entries = []
        for trade in tick.trades[product]:
            volume = available(trade.quantity)
            if print_share < 1:
                volume = int(volume * print_share)
            entries.append([trade, volume, volume, volume])
        trades[product] = entries

    return books, trades


def _take(order: _Live, books, working: list[_Live], names: list[str], timestamp: int, between: list[MarketTrade]) -> list[Fill]:
    """Trades a new order against the visible book and other participants' orders, best price first.

    At one price the recorded volume goes first, then participants' orders, oldest first. Each
    fill is at the price of the order that was already there. Returns the fills of both sides.
    """
    buying = order.quantity > 0
    sign = 1 if buying else -1
    bids, asks = books.get(order.product, ([], []))
    queue = [(price_level[0], 0, k, price_level) for k, price_level in enumerate(asks if buying else bids)]
    queue += [
        (other.price, 1, other.id, other)
        for other in working
        if other.product == order.product and other.owner != order.owner and (other.quantity < 0 if buying else other.quantity > 0)
    ]
    queue.sort(key=lambda entry: (entry[0] if buying else -entry[0], entry[1], entry[2]))

    fills = []
    for price, kind, _, there in queue:
        if (price > order.price) if buying else (price < order.price):
            break
        if kind == 0:  # a level of the recorded book: [price, volume]
            take = min(abs(order.quantity), there[1])
            if take == 0:
                continue
            there[1] -= take
            fills.append(Fill(timestamp, order.product, price, sign * take, "book", "", order.id, order.tag))
        else:  # another participant's order
            take = min(abs(order.quantity), abs(there.quantity))
            if take == 0:
                continue
            there.quantity += sign * take
            me, them = names[order.owner], names[there.owner]
            fills.append(Fill(timestamp, order.product, price, sign * take, "book", them, order.id, order.tag))
            fills.append(Fill(timestamp, order.product, price, -sign * take, "trade", me, there.id, there.tag))
            buyer, seller = (me, them) if buying else (them, me)
            between.append(MarketTrade(order.product, price, take, buyer, seller, timestamp))
        order.quantity -= sign * take
        if order.quantity == 0:
            break
    return fills


def _take_trades(order: _Live, trades, matching: TradeMatching, timestamp: int) -> list[Fill]:
    """Fills what's left of the order against market trades at its price or worse, at its own price."""
    if matching is TradeMatching.NONE or order.quantity == 0:
        return []
    buying = order.quantity > 0
    sign = 1 if buying else -1
    side = 2 if buying else 3
    fills = []
    for entry in trades.get(order.product, []):
        trade = entry[0]
        better = trade.price < order.price if buying else trade.price > order.price
        if not (better or (trade.price == order.price and matching is TradeMatching.ALL)):
            continue
        take = min(abs(order.quantity), entry[side])
        if take == 0:
            continue
        entry[side] -= take
        order.quantity -= sign * take
        counterparty = trade.seller if buying else trade.buyer
        fills.append(Fill(timestamp, order.product, order.price, sign * take, "trade", counterparty, order.id, order.tag))
        if order.quantity == 0:
            break
    return fills


def _match_trades(working: list[_Live], trades, matching: TradeMatching, timestamp: int) -> list[Fill]:
    """Several bots' leftover orders against this tick's market trades, at each order's own price.

    Each trade fills the orders it reaches in price-time priority, best price first, then the
    oldest: as _fill_resting, but with no queue, since nothing rests. TradeMatching as in
    _take_trades: a trade at an order's own price counts under ALL only.
    """
    if matching is TradeMatching.NONE:
        return []
    fills = []
    for product, entries in trades.items():
        mine = [order for order in working if order.product == product]
        buys, sells = _priority(mine, True), _priority(mine, False)
        for entry in entries:
            entry[2] = _match_queue(buys, entry[0], entry[2], True, matching, timestamp, fills)
            entry[3] = _match_queue(sells, entry[0], entry[3], False, matching, timestamp, fills)
    return fills


def _match_queue(queue: list[_Live], trade: MarketTrade, left: int, buying: bool, matching, timestamp, fills) -> int:
    """Fills one side's orders, in priority, from a market trade. Returns the trade volume left over."""
    sign = 1 if buying else -1
    for order in queue:
        if left == 0:
            break
        size = abs(order.quantity)
        if size == 0:
            continue
        through = (order.price > trade.price) if buying else (order.price < trade.price)
        if not (through or (order.price == trade.price and matching is TradeMatching.ALL)):
            break  # the queue is best price first: no later order reaches this trade
        take = min(left, size)
        order.quantity -= sign * take
        left -= take
        counterparty = trade.seller if buying else trade.buyer
        fills.append(Fill(timestamp, trade.product, order.price, sign * take, "trade", counterparty, order.id, order.tag))
    return left


def _remaining_trades(trades) -> dict[str, list[MarketTrade]]:
    """Market trades as the bot sees them next tick: minus the volume our orders took over."""
    remaining = {}
    for product, entries in trades.items():
        left = [
            replace(trade, quantity=trade.quantity - (available - min(for_buys, for_sells)))
            for trade, available, for_buys, for_sells in entries
        ]
        remaining[product] = [trade for trade in left if trade.quantity > 0]
    return remaining


def _seen_by(tick: Tick, resting: list[_Live], participant: int) -> Tick:
    """The tick as one participant sees it: the book plus the other participants' resting orders."""
    others = [order for order in resting if order.owner != participant and order.quantity]
    if not others:
        return tick
    books = dict(tick.books)
    for product in {order.product for order in others}:
        bids, asks = defaultdict(int), defaultdict(int)
        book = books.get(product, Book())
        for price, volume in book.bids:
            bids[price] += volume
        for price, volume in book.asks:
            asks[price] += volume
        for order in others:
            if order.product == product:
                (bids if order.quantity > 0 else asks)[order.price] += abs(order.quantity)
        books[product] = Book(bids=tuple(sorted(bids.items(), reverse=True)), asks=tuple(sorted(asks.items())))
    return replace(tick, books=books)


def _market_view(remaining: dict[str, list[MarketTrade]], between: list[MarketTrade], name: str) -> dict[str, list[MarketTrade]]:
    """Market trades one participant sees next tick: the recorded ones plus other participants' trades."""
    others = [trade for trade in between if name not in (trade.buyer, trade.seller)]
    if not others:
        return remaining
    view = {product: list(trades) for product, trades in remaining.items()}
    for trade in others:
        view.setdefault(trade.product, []).append(trade)
    return view


def _mark(tick: Tick, product: str, last: float) -> float:
    if product in tick.marks:
        return tick.marks[product]
    book = tick.books.get(product)
    mid = book.mid if book else None
    return last if mid is None else mid


# ---------------------------------------------------------------------------- resting mode


def _priority(orders: list[_Live], buying: bool) -> list[_Live]:
    """Price-time priority: best price first, then the oldest."""
    side = [order for order in orders if (order.quantity > 0) == buying]
    return sorted(side, key=lambda order: (-order.price if buying else order.price, order.id))


def _cross(resting: list[_Live], books, timestamp: int):
    """Fills resting orders that the new snapshot's other side reaches, at the resting price.

    Returns the fills and the volume taken from each level, as {(product, buying, price): volume}.
    """
    fills = []
    taken: dict[tuple[str, bool, float], int] = defaultdict(int)
    for product in sorted({order.product for order in resting}):
        bids, asks = books.get(product, ([], []))
        for buying, levels in ((True, asks), (False, bids)):
            sign = 1 if buying else -1
            for order in _priority([o for o in resting if o.product == product], buying):
                for level in levels:
                    price, volume = level
                    if (price > order.price) if buying else (price < order.price):
                        break
                    take = min(abs(order.quantity), volume)
                    if take == 0:
                        continue
                    level[1] -= take
                    order.quantity -= sign * take
                    taken[(product, buying, price)] += take
                    fills.append(Fill(timestamp, product, order.price, sign * take, "cross", "", order.id, order.tag))
                    if order.quantity == 0:
                        break
    return fills, taken


def _spend_crossed(trades, taken) -> None:
    """Takes the volume resting orders just crossed off this tick's market trades at the same prices.

    A tick's trades print against its book, so a trade at a crossed level used the same orders:
    the sellers at an ask our bid crossed are the sellers in that tick's trades at that price.
    Without this, an order would fill from them twice, once by the cross and once by the trade.
    """
    for (product, buying, price), volume in taken.items():
        side = 2 if buying else 3  # our buys take a trade's seller, our sells its buyer
        for entry in trades.get(product, []):
            if volume == 0:
                break
            if entry[0].price == price:
                used = min(volume, entry[side])
                entry[side] -= used
                volume -= used


def _without(tick: Tick, taken) -> Tick:
    """The tick as the bot sees it: without the levels resting orders just traded with."""
    if not taken:
        return tick
    books = dict(tick.books)
    for product in {product for product, _, _ in taken}:
        book = books[product]
        books[product] = Book(
            bids=_minus(book.bids, [taken.get((product, False, price), 0) for price, _ in book.bids]),
            asks=_minus(book.asks, [taken.get((product, True, price), 0) for price, _ in book.asks]),
        )
    return replace(tick, books=books)


def _deplete(tick: Tick, missing: dict[tuple[str, bool, float], list[int]]) -> Tick:
    """EngineConfig.deplete: the tick with what we took from the recorded book still gone. A level's
    deficit holds while the recording shows more at that price than we left there; once the
    recorded volume falls to what we left or below (the recording's own trades and cancels have
    gone past it), or the level leaves the book, the recording's level stands again."""
    for key in list(missing):
        product, ask, price = key
        book = tick.books.get(product)
        volume = next((v for p, v in ((book.asks if ask else book.bids) if book else ()) if p == price), 0)
        lots, left = missing[key]
        if volume <= left:
            del missing[key]
        else:
            missing[key][1] = max(volume - lots, 0)
    return _without(tick, {key: lots for key, (lots, _) in missing.items()})


def _minus(levels, used) -> tuple:
    return tuple((price, volume - u) for (price, volume), u in zip(levels, used) if volume > u)


def _volume_at(order: _Live, books: dict[str, Book]) -> int:
    """Visible volume at the order's price on its own side: what's queued in front of a new order."""
    book = books.get(order.product)
    levels = (book.bids if order.quantity > 0 else book.asks) if book else ()
    return next((volume for price, volume in levels if price == order.price), 0)


def _requeue(resting: list[_Live], books: dict[str, Book], model: QueueModel = QueueModel.BACK, power: float = 1.0) -> None:
    """Moves resting orders up their queue from the new snapshot (see QueueModel).

    It reads the recorded book, not _liquidity's --fill-ratio copy, as _volume_at does for a new
    order: the volume queued ahead of an order is all of the visible volume at its price, the part
    this bot couldn't have traded with included. _cross fills from the thinned copy instead, since
    only the share available to the bot can trade with it."""
    for order in resting:
        book = books.get(order.product)
        if not book:
            continue
        buying = order.quantity > 0
        levels = book.bids if buying else book.asks
        if not levels or ((order.price > levels[0][0]) if buying else (order.price < levels[0][0])):
            order.ahead = 0  # nothing visible at its price or better: it's at the front
        elif (volume := next((v for price, v in levels if price == order.price), None)) is not None:
            if model is QueueModel.FRONT:
                order.ahead = 0
            elif model is QueueModel.PROB:
                order.ahead = min(_prob_ahead(order, volume, power), volume)
            else:
                order.ahead = min(order.ahead, volume)
            order.seen = volume
        elif (order.price > levels[-1][0]) if buying else (order.price < levels[-1][0]):
            order.ahead = 0  # its level is inside the visible depth but empty
        # else: below the visible depth, so nothing is known: keep the estimate
        order.traded = 0


def _prob_ahead(order: _Live, volume: int, power: float) -> int:
    """hftbacktest's ProbQueueModel.depth: the volume ahead after the level went from seen to volume.

    Trades at its price already took their volume from the front (order.ahead is net of them).
    What else left the level was cancelled: x**n of it ahead of the order, the rest behind, and
    whatever is more than the volume behind also comes from ahead.
    """
    cancelled = order.seen - order.traded - volume
    if cancelled <= 0:
        return order.ahead
    behind = max(order.seen - order.traded - order.ahead, 0)
    queue = order.ahead + behind
    share = (order.ahead / queue) ** power if queue else 0.0
    ahead = order.ahead - share * cancelled + min(behind - (1 - share) * cancelled, 0)
    return max(round(ahead), 0)


def _fill_resting(resting: list[_Live], trades, matching: TradeMatching, timestamp: int) -> list[Fill]:
    """Fills resting orders against this tick's market trades, in price-time priority."""
    if matching is TradeMatching.NONE:
        return []
    fills = []
    for product, entries in trades.items():
        mine = [order for order in resting if order.product == product]
        buys, sells = _priority(mine, True), _priority(mine, False)
        for entry in entries:
            entry[2] = _fill_queue(buys, entry[0], entry[2], True, matching, timestamp, fills)
            entry[3] = _fill_queue(sells, entry[0], entry[3], False, matching, timestamp, fills)
    return fills


def _fill_queue(queue: list[_Live], trade: MarketTrade, left: int, buying: bool, matching, timestamp, fills) -> int:
    """Fills one side's resting orders from a market trade. Returns the trade volume left over."""
    sign = 1 if buying else -1
    for order in queue:
        if left == 0:
            break
        size = abs(order.quantity)
        if size == 0:
            continue
        if (order.price > trade.price) if buying else (order.price < trade.price):
            take = min(left, size)  # the trade went through its price, so it would have filled first
            order.ahead = 0
        elif order.price == trade.price and matching is TradeMatching.ALL:
            # The trade reaches the queue at this price after our better-priced orders took their
            # share. The volume ahead of this order goes first; our earlier orders here already
            # took theirs from `left`.
            take = max(0, min(size, left - order.ahead))
            order.traded += min(left, order.ahead)
            order.ahead = max(0, order.ahead - left)
        else:
            break
        if take:
            order.quantity -= sign * take
            left -= take
            counterparty = trade.seller if buying else trade.buyer
            fills.append(Fill(timestamp, trade.product, order.price, sign * take, "trade", counterparty, order.id, order.tag))
    return left
