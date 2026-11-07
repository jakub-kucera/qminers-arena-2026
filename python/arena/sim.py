"""An agent-based market: it makes days of data, and lets bots trade inside it.

    uv run python -m arena.sim generate data/sim --days 5                  # five days, Prosperity layout
    uv run python -m arena.backtest python/bots/template.py 1 --data data/sim      # replay them like any data
    uv run python -m arena.sim run python/bots/template.py --days 5                # the bot inside the market, against replay
    uv run python -m arena.sim run python/bots/template.py --spec KELP.maker.skew=0.05 --resting
    uv run python -m arena.sim run python/bots/template.py --products KELP,HYDROGEL_PACK --regime trend_up
    uv run python -m arena.sim run python/bots/drill/template.py --format drill --set "PARAMS.KELP={'fair': 'wall_mid'}"
    uv run python -m arena.sim run python/bots/template.py --days 20 --engine rust     # the same output, the market in rust/src/arena/sim.rs

Why: the engine replays a recording, so the market never reacts to our orders. The Arena's
simulator may: a take moves the price, the market maker skews against the flow it receives, and
the private run is a seed we never see (references/wiki/concepts/harder-rounds.md, A1). This is
the smallest such market the literature describes (PyMarketSim; Wang & Wellman 2017; ABIDES; see
their pages in references/wiki/sources/). Per product, every tick:

  1. The fundamental moves. It reverts to a level at rate `reversion` (Wang & Wellman's eq. 1
     without the floor at 0), with Gaussian steps, an optional drift, and jumps that may snap back
     after a while, or come in bursts that mostly reverse the jump before. With a regime change (`with_regime`, `--regime`), from a point in
     the day the value and its level shift at once, or both start to trend.
  2. The quoters arrive and post, against the live book:
       - the market maker re-quotes its walls around its view of the fundamental, moved against
         its inventory (`skew`), so after it is hit it quotes worse (A3);
       - limit traders post small orders a few ticks from their view of the fundamental and
         cancel them after `life` ticks; a price that crosses the book takes instead.
  3. The book is snapshotted, three levels a side as in Prosperity's files. In `run`, bots see
     the snapshot and trade: their orders take from the book at once, and the rest waits.
  4. The takers arrive in a seeded random order, with price-time priority against the book,
     the bots' orders included. Their trades are this tick's market trades:
       - noise takers buy or sell a few lots at the touch for no reason, the sides possibly
         unequal in number and size, and possibly repeating the last noise taker's side;
       - value takers see the fundamental with noise and take when the touch is far enough off;
       - momentum takers buy when the mid's short average is above its long one, and sell below.

Seeding follows ABIDES: one master seed, one generator per product and agent kind, so a run
repeats exactly. Each arrival makes the same draws whatever the book shows, so adding a bot
changes only what the agents meet, never what they draw: a day with the bot and the recording
without it share every random number.

This is the order a Prosperity tick implies: its trades print against its book, and the replay
engine fills the bot's tick-t orders from them. So a recorded day replays with the same
semantics, and the gap between replaying it and running the bot in the market is the market's
reaction to the bot, not a change of rules.

Bots in the market follow the replay engine's two modes:
  - default: an order takes what it can at once, then stays for that tick's takers only, then is
    cancelled;
  - resting: it stays until filled or cancelled (unless ioc), with a real place in the queue.
Limits are checked as in the engine, every order for a product rejected if all its buys or all its
sells could breach. A bot's orders never trade with each other. Standard library only.
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import math
import os
import random
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field, fields, is_dataclass, replace
from pathlib import Path

from arena.engine import Bot, DayResult, EngineConfig, QueueModel, TradeMatching, breaches, call_bot, known, new_result, record
from arena.model import Book, Cancel, Day, Fill, MarketTrade, OpenOrder, Tick

DEPTH = 3  # levels a side in a snapshot, as in Prosperity's price files
MAKER, LIMIT, NOISE, VALUE, MOMENTUM = "maker", "limit", "noise", "value", "momentum"
AGENTS = (MAKER, LIMIT, NOISE, VALUE, MOMENTUM)


# ---------------------------------------------------------------------------- specs


@dataclass(frozen=True)
class Fundamental:
    start: float
    level: float | None = None  # what it reverts to; None: start
    reversion: float = 0.0  # share of the gap to the level closed each tick
    sd: float = 0.0  # standard deviation of each tick's step
    drift: float = 0.0  # added each tick
    jump_rate: float = 0.0  # chance of a jump each tick
    jump_size: float = 0.0  # each jump is this, up or down at random
    snap_back: int | None = None  # ticks after which a jump is undone; None: it stays
    # Jumps that cluster and reverse, as on P4 round 5's ROBOT_DISHES: k ticks after a jump the
    # chance of another is jump_rate + jump_excite x jump_decay^(k-1), and each goes against the one
    # before with chance jump_reverse (None: up or down at random).
    jump_excite: float = 0.0
    jump_decay: float = 0.0
    jump_reverse: float | None = None
    # A regime change (see with_regime): at share regime_at of the day, the value and the level
    # both move by regime_shift and stay there; from then on, both move by regime_drift a tick, so
    # a product that returns to a level follows the trend instead of pulling back against it.
    regime_at: float | None = None
    regime_shift: float = 0.0
    regime_drift: float = 0.0


@dataclass(frozen=True)
class Maker:
    """The market maker: one large quote a side, the walls `wall_mid` reads."""

    half_spread: float = 2.0  # each wall's distance from its centre, before rounding to a tick
    size: tuple[int, int] = (20, 30)  # each wall's volume, uniform
    noise: float = 0.0  # standard deviation of its view of the fundamental
    skew: float = 0.0  # ticks its centre moves against each lot of its inventory
    refresh: float = 1.0  # chance each tick that it re-quotes (cancels and posts again)
    # Re-quote before the snapshot, as Prosperity's walls do. False puts it among the takers, after
    # the bots, so the walls they see are a tick old and value takers can pick them off.
    first: bool = True


@dataclass(frozen=True)
class LimitTraders:
    rate: float = 0.0  # arrivals a tick (Poisson)
    offset: tuple[float, float] = (0.5, 2.0)  # distance from the view, uniform; a buy goes below it
    size: tuple[int, int] = (1, 5)
    noise: float = 0.0  # standard deviation of the view of the fundamental
    life: int = 10  # ticks before the order is cancelled


@dataclass(frozen=True)
class NoiseTakers:
    rate: float = 0.0
    size: tuple[int, int] = (1, 8)
    buy_share: float = 0.5
    sell_size: tuple[int, int] | None = None  # a sell's volume, uniform; None: size
    persistence: float = 0.0  # chance a noise taker takes the same side as the one before


@dataclass(frozen=True)
class ValueTakers:
    rate: float = 0.0
    size: tuple[int, int] = (1, 5)
    noise: float = 0.0  # standard deviation of the view of the fundamental
    threshold: float = 1.0  # take when the touch is at least this far on the right side of the view


@dataclass(frozen=True)
class MomentumTakers:
    rate: float = 0.0
    size: tuple[int, int] = (1, 5)
    short: int = 20  # ticks in the short average of the mid
    long: int = 100
    threshold: float = 1.0  # take when the averages differ by at least this


@dataclass(frozen=True)
class ProductSpec:
    name: str
    limit: int  # the bots' position limit
    fundamental: Fundamental
    maker: Maker = Maker()
    limit_traders: LimitTraders = LimitTraders()
    noise: NoiseTakers = NoiseTakers()
    value: ValueTakers = ValueTakers()
    momentum: MomentumTakers = MomentumTakers()


@dataclass(frozen=True)
class MarketSpec:
    products: tuple[ProductSpec, ...]
    ticks: int = 10_000
    step: int = 100  # timestamp step, as in Prosperity
    names: bool = False  # show the agents' kinds as buyer and seller (Prosperity 3 round 1 shows none)


# Calibrated against P3 round 1 with arena.diagnose (the acceptance test in python/tests/test_sim.py, and
# the comparison in IDEAS.md, "An agent-based day generator"). Named after the products they stand
# in for, so the template's PARAMS trade them as they are.
PRESETS: dict[str, ProductSpec] = {
    # A random walk with walls 3-4 ticks apart, and one-tick orders inside them about half the time.
    "KELP": ProductSpec(
        "KELP",
        50,
        Fundamental(2030, sd=0.12),
        Maker(half_spread=1.75, size=(20, 30)),
        LimitTraders(rate=1.0, offset=(-0.5, 1.0), size=(1, 6), life=1),
        NoiseTakers(rate=0.25, size=(1, 5)),
        ValueTakers(rate=0.04, size=(1, 5), noise=0.5, threshold=1.0),
    ),
    # A fixed value: walls at 9995 / 10005, and most trades with small orders inside them,
    # some on the wrong side of 10,000 (Prosperity's takers sometimes buy below it).
    "RAINFOREST_RESIN": ProductSpec(
        "RAINFOREST_RESIN",
        50,
        Fundamental(10_000),
        Maker(half_spread=5, size=(20, 30)),
        LimitTraders(rate=1.5, offset=(-2.0, 4.0), size=(1, 6), life=1),
        NoiseTakers(rate=0.2, size=(1, 5)),
    ),
    # A faster random walk whose walls move past half the spread on about one tick in six, with
    # some momentum flow.
    "SQUID_INK": ProductSpec(
        "SQUID_INK",
        50,
        Fundamental(2000, sd=1.0),
        Maker(half_spread=1.5, size=(20, 30)),
        LimitTraders(rate=1.0, offset=(-0.5, 1.0), size=(1, 6), life=1),
        NoiseTakers(rate=0.25, size=(1, 5)),
        ValueTakers(rate=0.03, size=(1, 5), noise=1.0, threshold=1.0),
        MomentumTakers(rate=0.02, size=(1, 5)),
    ),
    # P4's Hydrogel: returns to a level over about 1,000 ticks (an Ornstein-Uhlenbeck fundamental:
    # reversion 0.0022 gives arena.diagnose's slow-reversion ratio of 2.3, and sd 2.06 an sd over the
    # day of 2.06 / sqrt(2 x 0.0022) = 31), behind walls 16 ticks apart. Not in the default market,
    # which is P3 round 1's.
    "HYDROGEL_PACK": ProductSpec(
        "HYDROGEL_PACK",
        200,
        Fundamental(9_995, reversion=0.0022, sd=2.06),
        Maker(half_spread=8, size=(20, 30)),
        LimitTraders(rate=0.08, offset=(2.0, 7.0), size=(1, 5), life=5),
        NoiseTakers(rate=0.03, size=(1, 5)),
        ValueTakers(rate=0.005, size=(1, 5), noise=2.0, threshold=1.0),
    ),
    # KELP with P3 round 1's taker flow, which KELP leaves balanced (so results on KELP still
    # reproduce): 35% of the trades at the touch are buys, larger than the sells (3.5 lots against
    # 2.6, 42% of the volume), and consecutive signs correlate (C(1) 0.13). A maker quoting both
    # sides is hit on the bid more often, so it drifts long, as the template does on Kelp.
    "KELP_FLOW": ProductSpec(
        "KELP_FLOW",
        50,
        Fundamental(2030, sd=0.12),
        Maker(half_spread=1.75, size=(20, 30)),
        LimitTraders(rate=1.0, offset=(-0.5, 1.0), size=(1, 6), life=1),
        NoiseTakers(rate=0.25, size=(2, 6), sell_size=(1, 5), buy_share=0.35, persistence=0.02),
        ValueTakers(rate=0.04, size=(1, 5), noise=0.5, threshold=1.0),
    ),
    # KELP whose market maker doesn't know the price: its centre is the fundamental plus a tick of
    # noise each re-quote, skewed 0.02 ticks against each lot it holds, so the walls no longer give
    # the price away (every other preset's maker quotes around the fundamental exactly). Not
    # calibrated to a Prosperity product: arena.diagnose notes it "mid and wall mid both noisy"
    # (wall signature 36 against KELP's 3), where the wall mid needs smoothing (IDEAS.md, "A market
    # maker that doesn't know the price"). From the second audit (2026-10-26, A7).
    "KELP_NOISY": ProductSpec(
        "KELP_NOISY",
        50,
        Fundamental(2030, sd=0.12),
        Maker(half_spread=1.75, size=(20, 30), noise=1.0, skew=0.02),
        LimitTraders(rate=1.0, offset=(-0.5, 1.0), size=(1, 6), life=1),
        NoiseTakers(rate=0.25, size=(1, 5)),
        ValueTakers(rate=0.04, size=(1, 5), noise=0.5, threshold=1.0),
    ),
    # P4 round 5's ROBOT_DISHES on day 4, from tick 1,153: the value sits on multiples of 100 and
    # jumps by 100, mostly straight back (87% of jumps reverse the one before), in bursts (a jump
    # follows another one tick later 29% of the time, against 3% a tick when quiet), behind walls
    # 8 apart. The pair it flickers between wanders over the day. Limit 10, as in round 5.
    "ROBOT_DISHES": ProductSpec(
        "ROBOT_DISHES",
        10,
        Fundamental(10_400, jump_rate=0.03, jump_size=100, jump_excite=0.26, jump_decay=0.75, jump_reverse=0.87),
        Maker(half_spread=4, size=(5, 10)),
        LimitTraders(rate=0.3, offset=(4.5, 5.5), size=(4, 10), life=1),
        NoiseTakers(rate=0.025, size=(1, 4)),
    ),
    # A large-tick book, the regime Prosperity hardly has (research_new_ideas.md R9): a maker half a
    # tick from a fundamental that barely moves (sd 0.05 a tick), so the spread is one tick; deep
    # queues of limit traders join the best and stay; takers of 5-15 lots, a few percent of the
    # queue a trade, some of them informed. Not calibrated to a product; for the join gate and the
    # hysteresis mid (IDEAS.md, "A large-tick book").
    "LARGE_TICK": ProductSpec(
        "LARGE_TICK",
        100,
        Fundamental(1000, sd=0.05),
        Maker(half_spread=0.5, size=(100, 200), refresh=0.5),
        LimitTraders(rate=2.0, offset=(0.0, 0.6), size=(5, 20), life=20),
        NoiseTakers(rate=0.4, size=(5, 15)),
        ValueTakers(rate=0.05, size=(5, 15), noise=0.2, threshold=0.4),
    ),
}
DEFAULT_PRESETS = ["KELP", "RAINFOREST_RESIN", "SQUID_INK"]  # P3 round 1's, the default market


def preset_market(products: list[str] | None = None, **options) -> MarketSpec:
    names = products or DEFAULT_PRESETS
    unknown = [name for name in names if name not in PRESETS]
    if unknown:
        raise ValueError(f"no preset for {', '.join(unknown)}: choose from {', '.join(PRESETS)}")
    return MarketSpec(tuple(PRESETS[name] for name in names), **options)


def with_override(spec: MarketSpec, path: str, value: object) -> MarketSpec:
    """Sets one field: `ticks=2000`, or `KELP.maker.skew=0.1` (product, then its fields)."""
    head, *rest = path.split(".")
    if not rest:
        return _set_field(spec, head, value, path)
    products = list(spec.products)
    for i, product in enumerate(products):
        if product.name == head:
            products[i] = _set_path(product, rest, value, path)
            return replace(spec, products=tuple(products))
    raise ValueError(f"{path}: no product {head!r} (have {', '.join(p.name for p in spec.products)})")


def _set_path(obj, keys: list[str], value, path: str):
    if len(keys) == 1:
        return _set_field(obj, keys[0], value, path)
    child = getattr(obj, keys[0], None)
    if not is_dataclass(child):
        raise ValueError(f"{path}: {keys[0]!r} is not a group of settings")
    return replace(obj, **{keys[0]: _set_path(child, keys[1:], value, path)})


def _set_field(obj, key: str, value, path: str):
    if key not in {f.name for f in fields(obj)}:
        raise ValueError(f"{path}: {type(obj).__name__} has no field {key!r}")
    if isinstance(getattr(obj, key), tuple) and isinstance(value, list):
        value = tuple(value)
    return replace(obj, **{key: value})


def parse_spec_override(text: str) -> tuple[str, object]:
    path, sep, raw = text.partition("=")
    if not sep:
        raise ValueError(f"bad --spec {text!r}: use PATH=VALUE, e.g. KELP.maker.skew=0.1")
    try:
        value = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        value = raw
    return path, value


# ---------------------------------------------------------------------------- the book


@dataclass
class _Order:
    id: int
    owner: str  # an agent kind, or a bot's name
    product: str
    price: float
    quantity: int  # left to fill, signed
    timestamp: int
    expires: int | None = None  # tick from which its agent cancels it
    tag: str = ""  # a bot's Order.tag, passed through

    def __post_init__(self):
        self.buying = self.quantity > 0

    def view(self) -> OpenOrder:
        return OpenOrder(self.id, self.product, self.price, self.quantity, self.timestamp, self.tag)


class _Book:
    """One product's live limit order book, price-time priority."""

    def __init__(self):
        self.bids: dict[float, list[_Order]] = {}
        self.asks: dict[float, list[_Order]] = {}
        self.orders: dict[int, _Order] = {}

    def best_bid(self) -> float | None:
        return max(self.bids) if self.bids else None

    def best_ask(self) -> float | None:
        return min(self.asks) if self.asks else None

    def submit(self, order: _Order, rest: bool, protect: bool) -> list[tuple[_Order, float, int]]:
        """Matches an incoming order, best price first, then rests what's left if `rest`.

        With `protect`, it skips resting orders of its own owner (a bot never trades with itself).
        Returns (resting order, price, volume) for each match.
        """
        buying = order.buying
        side = self.asks if buying else self.bids
        matches = []
        for price in sorted(side, reverse=not buying):
            if (price > order.price) if buying else (price < order.price):
                break
            for there in side[price]:
                if order.quantity == 0:
                    break
                if protect and there.owner == order.owner:
                    continue
                volume = min(abs(order.quantity), abs(there.quantity))
                there.quantity += volume if buying else -volume
                order.quantity -= volume if buying else -volume
                matches.append((there, price, volume))
            self._prune(side, price)
            if order.quantity == 0:
                break
        if order.quantity and rest:
            (self.bids if buying else self.asks).setdefault(order.price, []).append(order)
            self.orders[order.id] = order
        return matches

    def cancel(self, order_id: int) -> _Order | None:
        order = self.orders.pop(order_id, None)
        if order is None:
            return None
        side = self.bids if order.buying else self.asks
        queue = side.get(order.price, [])
        if order in queue:
            queue.remove(order)
            if not queue:
                del side[order.price]
        return order

    def _prune(self, side: dict[float, list[_Order]], price: float) -> None:
        left = []
        for order in side[price]:
            if order.quantity:
                left.append(order)
            else:
                self.orders.pop(order.id, None)
        if left:
            side[price] = left
        else:
            del side[price]

    def snapshot(self, hide: str | None = None) -> Book:
        """The top DEPTH levels a side, without `hide`'s own orders."""

        def levels(side: dict[float, list[_Order]], best_first: bool) -> tuple:
            out = []
            for price in sorted(side, reverse=best_first):
                volume = sum(abs(o.quantity) for o in side[price] if o.owner != hide)
                if volume:
                    out.append((price, volume))
                    if len(out) == DEPTH:
                        break
            return tuple(out)

        return Book(bids=levels(self.bids, True), asks=levels(self.asks, False))


# ---------------------------------------------------------------------------- the agents


def _poisson(rng: random.Random, rate: float) -> int:
    if rate <= 0:
        return 0
    limit, k, p = math.exp(-rate), 0, rng.random()
    while p > limit:
        k += 1
        p *= rng.random()
    return k


class _Product:
    """One product's fundamental, agents and book."""

    def __init__(self, spec: ProductSpec, seed: int, ticks: int = 10_000):
        self.spec = spec
        f0 = spec.fundamental
        self.regime_tick = None if f0.regime_at is None else round(f0.regime_at * ticks)
        self.level_shift = 0.0
        self.book = _Book()
        self.rngs = {kind: random.Random(f"{seed}/{spec.name}/{kind}") for kind in (*AGENTS, "fundamental", "arrival")}
        f = spec.fundamental
        self.value = f.start
        self.jumps: list[tuple[int, float]] = []  # (tick it snaps back at, size)
        self.last_jump: tuple[int, float] | None = None  # (tick, size) of the last jump
        self.last_noise_buy: bool | None = None  # the last noise taker's side
        self.maker_quotes: list[int] = []
        self.maker_inventory = 0
        self.mids: list[float] = []

    def step_fundamental(self, tick: int) -> None:
        f, rng = self.spec.fundamental, self.rngs["fundamental"]
        if self.regime_tick is not None and tick >= self.regime_tick:
            move = (f.regime_shift if tick == self.regime_tick else 0.0) + f.regime_drift
            self.value += move
            self.level_shift += move
        level = (f.start if f.level is None else f.level) + self.level_shift
        shock, jump_draw, jump_sign = rng.gauss(0, 1), rng.random(), rng.random()
        self.value += f.reversion * (level - self.value) + f.sd * shock + f.drift
        rate = f.jump_rate
        if f.jump_excite and self.last_jump is not None:
            rate += f.jump_excite * f.jump_decay ** (tick - self.last_jump[0] - 1)
        if rate and jump_draw < rate:
            if f.jump_reverse is not None and self.last_jump is not None:
                last = self.last_jump[1]
                size = -last if jump_sign < f.jump_reverse else last
            else:
                size = f.jump_size if jump_sign < 0.5 else -f.jump_size
            self.value += size
            self.last_jump = (tick, size)
            if f.snap_back is not None:
                self.jumps.append((tick + f.snap_back, size))
        for back in [jump for jump in self.jumps if jump[0] == tick]:
            self.value -= back[1]
            self.jumps.remove(back)

    def arrivals(self) -> tuple[list[str], list[str]]:
        """This tick's arrivals: the quoters, who come before the snapshot, and the takers, after the bots."""
        s, order = self.spec, self.rngs["arrival"]
        maker = [MAKER] * (self.rngs[MAKER].random() < s.maker.refresh)
        quoters = [LIMIT] * _poisson(self.rngs[LIMIT], s.limit_traders.rate)
        takers = []
        for kind, rate in ((NOISE, s.noise.rate), (VALUE, s.value.rate), (MOMENTUM, s.momentum.rate)):
            takers += [kind] * _poisson(self.rngs[kind], rate)
        if s.maker.first:
            quoters = maker + quoters
        else:
            takers += maker
        order.shuffle(takers)
        return quoters, takers

    def act(self, kind: str, tick: int, timestamp: int, new_id) -> list[tuple[_Order, _Order, float, int]]:
        """One agent's arrival. Returns (incoming, resting, price, volume) for each match."""
        rng, s, book = self.rngs[kind], self.spec, self.book
        orders: list[tuple[_Order, bool]] = []  # (order, rests)
        if kind == MAKER:
            m = s.maker
            noise, bid_size, ask_size = rng.gauss(0, 1), rng.randint(*m.size), rng.randint(*m.size)
            for order_id in self.maker_quotes:
                book.cancel(order_id)
            centre = self.value + m.noise * noise - m.skew * self.maker_inventory
            bid, ask = round(centre - m.half_spread), round(centre + m.half_spread)
            if ask <= bid:
                ask = bid + 1
            quotes = [_Order(new_id(), MAKER, s.name, bid, bid_size, timestamp), _Order(new_id(), MAKER, s.name, ask, -ask_size, timestamp)]
            self.maker_quotes = [q.id for q in quotes]
            orders = [(q, True) for q in quotes]
        elif kind == LIMIT:
            t = s.limit_traders
            buying, offset, noise, size = rng.random() < 0.5, rng.uniform(*t.offset), rng.gauss(0, 1), rng.randint(*t.size)
            view = self.value + t.noise * noise
            price = math.floor(view - offset) if buying else math.ceil(view + offset)
            orders = [(_Order(new_id(), LIMIT, s.name, price, size if buying else -size, timestamp, tick + t.life), True)]
        elif kind == NOISE:
            t = s.noise
            buying = rng.random() < t.buy_share
            if t.persistence and rng.random() < t.persistence and self.last_noise_buy is not None:
                buying = self.last_noise_buy
            self.last_noise_buy = buying
            size = rng.randint(*(t.size if buying or t.sell_size is None else t.sell_size))
            touch = book.best_ask() if buying else book.best_bid()
            if touch is not None:
                orders = [(_Order(new_id(), NOISE, s.name, touch, size if buying else -size, timestamp), False)]
        elif kind == VALUE:
            t = s.value
            noise, size = rng.gauss(0, 1), rng.randint(*t.size)
            view = self.value + t.noise * noise
            ask, bid = book.best_ask(), book.best_bid()
            if ask is not None and ask <= view - t.threshold:
                orders = [(_Order(new_id(), VALUE, s.name, math.floor(view - t.threshold), size, timestamp), False)]
            elif bid is not None and bid >= view + t.threshold:
                orders = [(_Order(new_id(), VALUE, s.name, math.ceil(view + t.threshold), -size, timestamp), False)]
        elif kind == MOMENTUM:
            t = s.momentum
            size = rng.randint(*t.size)
            if len(self.mids) >= t.long:
                signal = sum(self.mids[-t.short :]) / t.short - sum(self.mids[-t.long :]) / t.long
                ask, bid = book.best_ask(), book.best_bid()
                if signal >= t.threshold and ask is not None:
                    orders = [(_Order(new_id(), MOMENTUM, s.name, ask, size, timestamp), False)]
                elif signal <= -t.threshold and bid is not None:
                    orders = [(_Order(new_id(), MOMENTUM, s.name, bid, -size, timestamp), False)]
        matches = []
        for order, rests in orders:
            matches += [(order, *match) for match in book.submit(order, rests, protect=False)]
        return matches

    def expire(self, tick: int) -> None:
        for order in [o for o in self.book.orders.values() if o.expires is not None and o.expires <= tick]:
            self.book.cancel(order.id)

    def snapshot_mid(self, book: Book) -> float | None:
        mid = book.mid
        if mid is None:
            mid = (book.bids or book.asks or [(None,)])[0][0]
        if mid is not None:
            self.mids.append(mid)
        elif self.mids:
            self.mids.append(self.mids[-1])
        return mid


# ---------------------------------------------------------------------------- the market


@dataclass
class _Player:
    name: str
    bot: Bot
    result: DayResult
    position: dict[str, int]
    cash: dict[str, float]
    unseen_fills: list[Fill] = field(default_factory=list)
    live: dict[int, _Order] = field(default_factory=dict)  # its orders on the book, by id


@dataclass
class SimDay:
    day: Day  # the snapshots and the agents' trades with each other, as a recording
    fundamentals: dict[str, list[float]]  # per product, the fundamental at each snapshot
    results: list[DayResult]  # one per bot, in order


def run(
    spec: MarketSpec,
    seed: int,
    bots: list[tuple[str, Bot]] = (),
    resting: bool = False,
    capture_output: bool = True,
    name: str | None = None,
) -> SimDay:
    """Runs the market for one day, with the bots (if any) trading inside it."""
    names = [n for n, _ in bots]
    if len(set(names)) != len(names) or set(names) & set(AGENTS):
        raise ValueError(f"bot names must be unique and not an agent kind: {names}")
    config = EngineConfig(resting=resting, capture_output=capture_output)
    products = {p.name: _Product(p, seed, spec.ticks) for p in spec.products}
    limits = {p.name: p.limit for p in spec.products}
    day_name = name or f"sim{seed}"
    shell = Day(day_name, list(products), limits, [])
    players = [_Player(n, bot, new_result(shell), dict.fromkeys(products, 0), dict.fromkeys(products, 0.0)) for n, bot in bots]
    for _, bot in bots:
        if hasattr(bot, "begin_day"):
            bot.begin_day(shell)
    by_name = {p.name: p for p in players}
    arrival = random.Random(f"{seed}/bots")
    counter = iter(range(1, 1 << 62))

    def new_id() -> int:
        return next(counter)

    def execute(incoming: _Order, there: _Order, price: float, volume: int, timestamp: int, log: list[MarketTrade]) -> None:
        buyer, seller = (incoming, there) if incoming.buying else (there, incoming)
        for order, other, sign in ((buyer, seller, 1), (seller, buyer, -1)):
            if order.owner == MAKER:
                products[order.product].maker_inventory += sign * volume
            elif order.owner in by_name:
                player = by_name[order.owner]
                source = "book" if order is incoming else "trade"
                fill = Fill(timestamp, order.product, price, sign * volume, source, _shown(other.owner, spec, by_name), order.id, order.tag)
                player.position[order.product] += sign * volume
                player.cash[order.product] -= price * sign * volume
                player.result.fills.append(fill)
                player.unseen_fills.append(fill)
                if not order.quantity:
                    player.live.pop(order.id, None)
        log.append(MarketTrade(incoming.product, price, volume, buyer.owner, seller.owner, timestamp))

    ticks: list[Tick] = []
    fundamentals: dict[str, list[float]] = {p: [] for p in products}
    marks = dict.fromkeys(products, 0.0)
    since: list[MarketTrade] = []  # every trade since the bots' last call
    for tick in range(spec.ticks):
        timestamp = tick * spec.step
        executed: list[MarketTrade] = []
        takers = {}
        for product, state in products.items():
            state.expire(tick)
            state.step_fundamental(tick)
            quoters, takers[product] = state.arrivals()
            for kind in quoters:
                for match in state.act(kind, tick, timestamp, new_id):
                    execute(*match, timestamp, executed)

        books = {product: state.book.snapshot() for product, state in products.items()}
        for product, state in products.items():
            fundamentals[product].append(state.value)
            mid = state.snapshot_mid(books[product])
            marks[product] = marks[product] if mid is None else mid

        quoted = len(executed)
        if players:
            seen = since + executed
            _bots_trade(players, products, books, seen, marks, timestamp, spec, by_name, limits, resting, config, arrival, new_id, execute, executed)
        for product, state in products.items():
            for kind in takers[product]:
                for match in state.act(kind, tick, timestamp, new_id):
                    execute(*match, timestamp, executed)
        since = executed[quoted:]  # the bots see these next tick
        if not resting:  # the bots' orders lived for this tick's takers only
            for player in players:
                for order in player.live.values():
                    products[order.product].book.cancel(order.id)
                player.live.clear()
        trades = _by_product(_named(t, spec, by_name) for t in executed if t.buyer not in by_name and t.seller not in by_name)
        ticks.append(Tick(timestamp, books, trades, {p: m for p, m in ((p, _mid(b)) for p, b in books.items()) if m is not None}))
        tick_marked = Tick(timestamp, books, {}, dict(marks))
        for player in players:
            record(player, tick_marked, marks)

    for player in players:
        player.result.market_trades = [(t.timestamp, trade) for t in ticks for trades in t.trades.values() for trade in trades]
    return SimDay(Day(day_name, list(products), limits, ticks), fundamentals, [p.result for p in players])


def _bots_trade(players, products, books, since, marks, timestamp, spec, by_name, limits, resting, config, arrival, new_id, execute, executed):
    """The bots see the snapshot and the trades since their last call, decide at once, and their
    actions reach the book in a seeded random order, as in engine.run_market."""
    actions, decided = [], []
    for player in players:
        seen_books = {product: state.book.snapshot(hide=player.name) for product, state in products.items()} if resting else books
        market_trades = _by_product(_named(t, spec, by_name) for t in since if player.name not in (t.buyer, t.seller))
        mine = [order.view() for order in player.live.values()]
        seen = Tick(timestamp, seen_books, {}, dict(marks))
        actions.append(call_bot(player.bot, seen, player.position, player.unseen_fills, market_trades, mine, config, player.result))
        decided.append((dict(player.position), mine))
        player.unseen_fills = []

    order_of_arrival = list(range(len(players)))
    arrival.shuffle(order_of_arrival)
    for i in order_of_arrival:
        player = players[i]
        seen_position, seen = decided[i]
        seen_ids = {o.id for o in seen}
        orders, cancelled = [], set()
        for action in actions[i]:
            if not isinstance(action, Cancel):
                orders.append(action)
            elif action.order_id in player.live:
                order = player.live.pop(action.order_id)
                products[order.product].book.cancel(order.id)
                cancelled.add(order.id)
                player.result.cancels.append((timestamp, order.id))
            elif action.order_id not in seen_ids:
                hint = "" if resting else " (orders only rest in resting mode)"
                player.result.errors.append((timestamp, f"cancel for order {action.order_id}, which isn't open{hint}"))
        orders = known(orders, limits, timestamp, player.result)
        kept = [order.view() for order in player.live.values()]
        breached = breaches(orders, seen_position, [o for o in seen if o.id not in cancelled], limits)
        raced = breaches(orders, player.position, kept, limits) - breached
        player.result.limit_breaches.extend((timestamp, product) for product in sorted(breached))
        player.result.races.extend((timestamp, product) for product in sorted(raced))
        placed = []
        for order in orders:
            if order.product in breached | raced:
                continue
            live = _Order(new_id(), player.name, order.product, order.price, order.quantity, timestamp, tag=order.tag)
            placed.append(live.view())
            rests = not (resting and order.ioc)
            for there, price, volume in products[order.product].book.submit(live, rests, protect=True):
                execute(live, there, price, volume, timestamp, executed)
            if live.quantity and rests:
                player.live[live.id] = live
        player.result.orders.extend((timestamp, o) for o in kept + placed)


def _mid(book: Book) -> float | None:
    if book.mid is not None:
        return book.mid
    side = book.bids or book.asks
    return side[0][0] if side else None


def _shown(owner: str, spec: MarketSpec, bots) -> str:
    """How a participant is named to the bots: bots by name, agents by kind only if spec.names."""
    return owner if owner in bots or spec.names else ""


def _named(trade: MarketTrade, spec: MarketSpec, bots) -> MarketTrade:
    return replace(trade, buyer=_shown(trade.buyer, spec, bots), seller=_shown(trade.seller, spec, bots))


def _by_product(trades) -> dict[str, list[MarketTrade]]:
    out: dict[str, list[MarketTrade]] = defaultdict(list)
    for trade in trades:
        out[trade.product].append(trade)
    return dict(out)


# ---------------------------------------------------------------------------- files and the command line


def write_day(sim: SimDay, data_dir: Path, round_num: int, day_num: int) -> None:
    """Writes a day in the Prosperity layout, plus the fundamental and limits.json (read by the loader)."""
    folder = data_dir / f"round{round_num}"
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"round_{round_num}_day_{day_num}"
    with (folder / f"prices_{stem}.csv").open("w", newline="") as file:
        out = csv.writer(file, delimiter=";")
        out.writerow(
            ["day", "timestamp", "product"]
            + [f"{side}_{kind}_{k}" for side in ("bid", "ask") for k in (1, 2, 3) for kind in ("price", "volume")]
            + ["mid_price", "profit_and_loss"]
        )
        for tick in sim.day.ticks:
            for product in sim.day.products:
                book = tick.books[product]
                row = [day_num, tick.timestamp, product]
                for levels in (book.bids, book.asks):
                    for k in range(DEPTH):
                        row += list(levels[k]) if k < len(levels) else ["", ""]
                mark = tick.marks.get(product)
                row += ["" if mark is None else f"{mark:.1f}", "0.0"]
                out.writerow(row)
    with (folder / f"trades_{stem}.csv").open("w", newline="") as file:
        out = csv.writer(file, delimiter=";")
        out.writerow(["timestamp", "buyer", "seller", "symbol", "currency", "price", "quantity"])
        for tick in sim.day.ticks:
            for product in sim.day.products:
                for trade in tick.trades.get(product, []):
                    out.writerow([tick.timestamp, trade.buyer, trade.seller, product, "SEASHELLS", f"{trade.price:.1f}", trade.quantity])
    with (folder / f"fundamental_{stem}.csv").open("w", newline="") as file:
        out = csv.writer(file, delimiter=";")
        out.writerow(["timestamp", "product", "value"])
        for k, tick in enumerate(sim.day.ticks):
            for product in sim.day.products:
                out.writerow([tick.timestamp, product, f"{sim.fundamentals[product][k]:.3f}"])
    limits_path = data_dir / "limits.json"
    limits = json.loads(limits_path.read_text()) if limits_path.exists() else {}
    limits.update(sim.day.limits)
    limits_path.write_text(json.dumps(limits, indent=2, sort_keys=True) + "\n")


REGIMES = ("shift_up", "shift_down", "trend_up", "trend_down")


def with_regime(spec: MarketSpec, regime: str, at: float = 0.5) -> MarketSpec:
    """Every product's fundamental changes regime at share `at` of the day, as in the 2024 final.

    Sized in each product's wall spread s (twice the maker's half-spread), as arena.stress sizes its
    perturbations of recorded days: shift_up moves the value and the level 5 s at once, trend_up
    moves them 10 s over the rest of the day (the _down ones the other way). Unlike arena.stress,
    the market reacts: the maker re-centres on the new value, and value takers trade toward it.
    """
    if regime not in REGIMES:
        raise ValueError(f"unknown regime {regime!r}: choose from {', '.join(REGIMES)}")
    if not 0 < at < 1:
        raise ValueError(f"the regime must start inside the day (0 < at < 1), got {at}")
    sign = -1 if regime.endswith("_down") else 1
    products = []
    for p in spec.products:
        s = 2 * p.maker.half_spread
        if regime.startswith("shift"):
            change = {"regime_shift": sign * 5 * s}
        else:
            change = {"regime_drift": sign * 10 * s / (spec.ticks * (1 - at))}
        products.append(replace(p, fundamental=replace(p.fundamental, regime_at=at, **change)))
    return replace(spec, products=tuple(products))


def _spec_from_args(args) -> MarketSpec:
    spec = preset_market(args.products.split(",") if args.products else None, ticks=args.ticks, names=args.names)
    for text in args.spec:
        spec = with_override(spec, *parse_spec_override(text))
    if args.regime:
        spec = with_regime(spec, args.regime, args.regime_at)
    return spec


def _add_market_arguments(parser: argparse.ArgumentParser) -> None:
    from arena.cli import add_engine_argument

    parser.add_argument("--days", type=int, default=3, help="days to simulate, one seed each (default: 3)")
    parser.add_argument("--seed", type=int, default=0, help="seed of the first day; day k uses seed + k (default: 0)")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1, help="worker processes, one day each (default: CPU count)")
    parser.add_argument("--products", help=f"comma-separated presets, from {', '.join(PRESETS)} (default: {','.join(DEFAULT_PRESETS)})")
    parser.add_argument("--ticks", type=int, default=10_000, help="ticks a day (default: 10,000)")
    parser.add_argument("--names", action="store_true", help="show the agents' kinds as buyer and seller")
    parser.add_argument(
        "--spec", action="append", default=[], metavar="PATH=VALUE",
        help="change a preset, e.g. --spec KELP.maker.skew=0.05 or --spec KELP.fundamental.sd=0.3 (repeatable)",
    )
    parser.add_argument("--regime", choices=REGIMES, help="every product's fundamental changes regime during the day (see with_regime)")
    parser.add_argument("--regime-at", type=float, default=0.5, help="with --regime: the share of the day it starts at (default: 0.5)")
    add_engine_argument(parser, "run the market here or in rust/src/arena/sim.rs, the same to the bit (rust: bots with a Rust twin, "
                        "python/arena/rust.py)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m arena.sim", description="An agent-based market: make days, or run bots inside it.")
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate", help="write simulated days in the Prosperity layout")
    generate.add_argument("out", type=Path, help="data folder to write (use it with --data)")
    generate.add_argument("--round", type=int, default=1, help="round number in the file names (default: 1)")
    _add_market_arguments(generate)
    run_parser = commands.add_parser("run", help="run a bot inside the market, and compare with replaying the same days")
    run_parser.add_argument("bot", type=Path)
    run_parser.add_argument("--format", default="prosperity", help="the bots' format (default: prosperity). The market's prices are "
                            "whole ticks; a format with decimal prices sees them as its price unit (drill: 1 = 0.01)")
    run_parser.add_argument("--resting", action="store_true", help="orders rest until filled or cancelled (always, for a format whose orders rest)")
    run_parser.add_argument("--queue", type=QueueModel, choices=list(QueueModel), default=QueueModel.BACK, help="the replay's queue model with --resting (default: back)")
    run_parser.add_argument("--queue-power", type=float, default=1.0, help="--queue prob: its power (default: 1)")
    run_parser.add_argument("--vs", dest="rivals", type=Path, action="append", default=[], metavar="BOT", help="another bot in the same market")
    run_parser.add_argument("--set", dest="overrides", action="append", default=[], metavar="PATH=VALUE", help="override a bot global (your bot only)")
    run_parser.add_argument("--out", type=Path, help="write the in-market results' CSVs to this folder")
    _add_market_arguments(run_parser)
    args = parser.parse_args(argv)
    try:
        spec = _spec_from_args(args)
    except ValueError as error:
        parser.error(str(error))

    if args.command == "generate":
        if args.engine == "rust":
            try:
                lines = _generate_rust(args, spec)
            except ValueError as error:  # a stale twin
                parser.error(str(error))
        else:
            lines = _map(args.jobs, _generate_day, [(spec, args.out, args.round, k, args.seed + k) for k in range(args.days)])
        for line in lines:
            print(line)
        print(f"written to {args.out}/: replay with --data {args.out}")
        return 0
    return _run_command(args, spec, parser)


def _write_limits(spec: MarketSpec, data_dir: Path) -> None:
    limits_path = data_dir / "limits.json"
    limits = json.loads(limits_path.read_text()) if limits_path.exists() else {}
    limits.update({p.name: p.limit for p in spec.products})
    limits_path.write_text(json.dumps(limits, indent=2, sort_keys=True) + "\n")


def _generate_rust(args, spec: MarketSpec) -> list[str]:
    from arena import rust

    rust.prepare("prosperity", [], args.allow_stale)  # no bots: the market's twin
    rows = rust.run_sim(spec, args.seed, args.days, csv=args.out, round_number=args.round, threads=args.jobs, read=False)
    _write_limits(spec, args.out)
    return [f"round {args.round} day {row['day']} (seed {row['seed']}): {row['trades']:,} trades" for row in rows]


def _map(jobs: int, fn, tasks: list[tuple]) -> list:
    """fn over the tasks, in a process pool unless one job, results in task order."""
    if jobs <= 1 or len(tasks) <= 1:
        return [fn(*task) for task in tasks]
    with ProcessPoolExecutor(min(jobs, len(tasks))) as pool:
        return list(pool.map(fn, *zip(*tasks)))


def _generate_day(spec: MarketSpec, out: Path, round_number: int, k: int, seed: int) -> str:
    sim = run(spec, seed)
    write_day(sim, out, round_number, k)
    return f"round {round_number} day {k} (seed {seed}): {sum(len(v) for t in sim.day.ticks for v in t.trades.values()):,} trades"


def _load_bots(args, overrides) -> list:
    from arena.formats import FORMATS

    fmt = FORMATS[args.format]
    return [fmt.load_bot(args.bot, overrides, strict=True)] + [fmt.load_bot(r, {}, strict=True) for r in args.rivals]


def _run_day(args, spec: MarketSpec, overrides: dict, seed: int) -> tuple[str, dict[str, dict[str, float]], bool]:
    """One seed's day: the bot in the market and in each replay. Returns what to print, each
    product's PnL by key (replay modes, then "market"), and whether anything raised."""
    from arena.cli import participant_names
    from arena.engine import run_market

    names = participant_names(args.bot, args.rivals)
    inside = run(spec, seed, list(zip(names, _load_bots(args, overrides))), resting=args.resting)
    recording = run(spec, seed).day
    config = {m: EngineConfig(trade_matching=m, resting=args.resting, queue=args.queue, queue_power=args.queue_power) for m in TradeMatching}
    replays = {m: run_market(recording, list(zip(names, _load_bots(args, overrides))), config[m])[0] for m in TradeMatching}
    finals = {m: {p: series[-1] for p, series in r.pnl.items()} for m, r in replays.items()}
    return _day_lines(args, names, inside.results, finals, any(r.errors for r in replays.values()))


def _day_lines(args, names: list[str], inside: list[DayResult], replays: dict, replay_failed: bool) -> tuple[str, dict[str, dict[str, float]], bool]:
    """_run_day's output from the bots' results in the market, and the bot's final PnL per product
    in each replay ({trade matching: {product: pnl}})."""
    from arena import report

    modes = list(TradeMatching)
    header = "".join(f"  {'replay ' + m.value:>14}" for m in modes) + f"  {'in market':>14}"
    mine = inside[0]
    failed = bool(mine.errors or replay_failed)
    lines = [report.format_day(mine)]
    if args.rivals:
        lines.append(report.format_rivals(names[1:], inside[1:]))
    lines.append("  pnl in the market, and replaying the same day without the bot (--match-trades):")
    lines.append(f"    {'':<20}{header}")
    rows = {}
    for product in mine.products:
        row = {m.value: replays[m][product] for m in modes} | {"market": mine.pnl[product][-1]}
        if any(row.values()):
            rows[product] = row
            lines.append(f"    {product:<20}" + "".join(f"  {v:>14,.0f}" for v in row.values()))
    lines.append("")
    if args.out:
        report.write_csvs(mine, args.out)
    return "\n".join(lines), rows, failed


def _rust_days(args, spec: MarketSpec, overrides: dict) -> list[tuple[str, dict[str, dict[str, float]], bool]]:
    """_run_day for every seed, the market and the replays in rust/ (their bots the Rust twins)."""
    from arena import rust
    from arena.cli import participant_names

    names = participant_names(args.bot, args.rivals)
    bots = [(names[0], args.bot, overrides, False)] + [(name, path, {}, False) for name, path in zip(names[1:], args.rivals)]
    for _, path, o, _ in bots:
        rust.bot_spec(path, o)  # no twin, or --set on a zoo twin: refused before the build
    rust.prepare(args.format, [args.bot, *args.rivals], args.allow_stale)
    config = EngineConfig(resting=args.resting, queue=args.queue, queue_power=args.queue_power)
    rows = rust.run_sim(spec, args.seed, args.days, bots, config, replay=True, read="results", threads=args.jobs)
    out = []
    for row in rows:
        replays = {m: totals[names[0]]["products"] for m, totals in row["replays"].items()}
        out.append(_day_lines(args, names, row["results"], replays, any(totals[names[0]]["errors"] for totals in row["replays"].values())))
    return out


def _run_command(args, spec: MarketSpec, parser) -> int:
    from arena.botfile import OverrideError, parse_override
    from arena.formats import FORMATS

    try:
        fmt = FORMATS[args.format]
        overrides = dict(parse_override(text) for text in args.overrides)
        args.resting = args.resting or getattr(fmt, "RESTING", False)
        _load_bots(args, overrides)  # fail on a bad bot or override before any day runs
        if args.engine == "rust":
            days = _rust_days(args, spec, overrides)
    except (KeyError, ValueError, OSError, OverrideError) as error:
        parser.error(f"unknown format {error}" if isinstance(error, KeyError) else str(error))
    modes = list(TradeMatching)
    totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    failed = False
    header = "".join(f"  {'replay ' + m.value:>14}" for m in modes) + f"  {'in market':>14}"
    if args.engine != "rust":
        days = _map(args.jobs, _run_day, [(args, spec, overrides, args.seed + k) for k in range(args.days)])
    for text, rows, day_failed in days:
        print(text)
        failed |= day_failed
        for product, row in rows.items():
            for key, value in row.items():
                totals[product][key] += value
    print(f"over {args.days} days (seeds {args.seed}-{args.seed + args.days - 1}){' with --resting' if args.resting else ''}:")
    print(f"  {'':<20}{header}")
    for product, row in [*totals.items(), ("total", {key: sum(t[key] for t in totals.values()) for key in [m.value for m in modes] + ["market"]})]:
        print(f"  {product:<20}" + "".join(f"  {row[key]:>14,.0f}" for key in [m.value for m in modes] + ["market"]))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
