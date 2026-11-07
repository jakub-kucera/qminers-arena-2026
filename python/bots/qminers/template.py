"""DAY-OF SKELETON: the template for the Arena's format (python/arena/formats/qminers.py), prepared.

The same file as python/bots/template.py down to the end of EXECUTION, except PARAMS
(python/tests/test_drill.py checks DEFAULTS, STRATEGY and EXECUTION word for word; after a change to
the template, `uv run python -m experiments.format_drill --sync`). On the day rewrite only:
  - the imports, if their API needs any (their SDK module is provided by the format, not copied here);
  - PARAMS: one entry per product from `arena.diagnose all --format qminers --data D --suggest`, prices
    in the product's ticks;
  - ADAPTER: the seven functions below (to_ticks, to_price, read_book, params_for, read_trades,
    read_fills, read_resting) keep their signatures and docstrings; each body raises until written, and
    the drill's body (python/bots/drill/template.py) sits beside it as a model; then the entry class:
    `class Bot.on_tick` renamed to their entry (qminers.ENTRY) and each API call in it replaced.
Ticks at the boundary: STRATEGY and EXECUTION work in whole ticks (+1 = one tick inside), ADAPTER converts.
ON_THE_DAY.md, "The format swap, step by step", is the checklist. The Rust twin, if grids get slow, is a
rust/twins.json row (the checklist's step 10; no row until the ADAPTER is real).
"""

from __future__ import annotations

import math
import traceback
from statistics import NormalDist

# The backtester sets this to True so bugs raise instead of being swallowed.
STRICT = False
# Steps an order takes to reach the exchange: what a call sends meets the book DELAY steps later
# (the rules, probe 3, or calibrate's delay). 0: by the next call it is listed or done.
DELAY = 0  # TODO(day): the rules' or probe 3's delay
# With DELAY: whether an order that doesn't fill stays on the book between calls.
ORDERS_REST = True  # TODO(day): False if their orders don't rest
# Where an exchange charges for every order placed: a quote's shortfall at a price where an order already works is
# posted only once it reaches this many lots (0 posts every shortfall). 10 paid on the 2026-11-03 rehearsal's portal,
# 11% fewer orders, +8% public and +6% hidden (IDEAS.md, "Top-ups where every order costs a fee").
TOPUP_MIN = 0

DEFAULTS = {
    "limit": 50,  # position limit: must match the competition's
    "fair": "sized_mid",  # "fixed", "mid", "wall_mid", "outer_mid", "sized_mid", "weighted_mid" or "hysteresis_mid" (see fair_value)
    "fixed_fair": None,  # used when fair is "fixed"
    "fixed_guard": None,  # fair "fixed": use the sized mid instead while it is further than this from fixed_fair
    "wall_size": 15,  # sized_mid: the smallest level that counts as the market maker's quote
    "smoothing": 0.0,  # 0 uses each tick's fair as is; closer to 1 moves it more slowly
    # Take, clear and make around fair + imbalance * rho, rho = (Vb - Va)/(Vb + Va) at the best
    # levels: the linear micro-price. 0 turns it off. Fitted per product by experiments.day.imbalance.
    "imbalance": 0.0,
    # A linear fair (IDEAS.md, "A `linear` fair"): add lin_rho3 x the depth imbalance over the best 3
    # levels, and lin_momentum x the fair's move over the last lin_window ticks, in an agent market
    # where flow and momentum carry the price (experiments.day.predict). 0 turns each off.
    "lin_rho3": 0.0,
    "lin_momentum": 0.0,
    "lin_window": 100,
    # Pull the side a move runs over (IDEAS.md, "Gating a side on the last move"): after the fair has
    # risen at least gate_move over gate_window ticks, no ask; after a fall as large, no bid. None: off.
    "gate_move": None,
    "gate_window": 20,
    "take_edge": 1,  # take book orders priced at least this much better than fair
    "clear_edge": 0,  # cut inventory at prices up to this much worse than fair
    "make_edge": 2,  # quote at least this far from fair
    "make_inside": 1,  # ...and this many ticks inside the best book quote, if that is further out; None: at make_edge whatever the book
    "skew": 0.0,  # move quotes this far against inventory when at the full position limit
    "size_skew": 0.0,  # scale each quote by max(1 +/- size_skew * gap / limit, 0): the side that adds to the gap shrinks
    "target": 0,  # position to hold: clear and skew work inventory toward it (e.g. long with a steady drift)
    "make_size": None,  # largest quote; None quotes all remaining room under the limit
    # Per side, in place of take_edge and make_edge (None: the shared one): an asymmetric market,
    # where dips snap back faster than rips or takers lean one way (IDEAS.md, "Per-side edges").
    "take_edge_buy": None,
    "take_edge_sell": None,
    "make_edge_buy": None,
    "make_edge_sell": None,
    "make_levels": 1,  # split each side's quote over this many prices, make_step apart, outward from the best one
    "make_step": 1,
    "take_reserve": 0,  # quotes keep this much of the limit free for takes: they fill the position up to limit - take_reserve
    # A large-tick book (a one-tick spread most of the time; Albers, Gao & Wang): a quote that would
    # join the best stands a tick back unless at least join_min lots queue there and the other side's
    # best holds no more than join_ratio times that (a small opposite queue is about to empty). None: off.
    "join_min": None,
    "join_ratio": 2.0,
    # Passive-first execution toward a target (harder-rounds A2): take and clear cross at most
    # cross_max lots a tick, and clear only the part of the gap to target beyond cross_excess; the
    # quotes work the rest. None: off.
    "cross_max": None,
    "cross_excess": None,
    # A price the product returns to (see level_target): a number from earlier days, or "day" for
    # the mean of the day so far. None turns it off. While on, it sets target instead.
    "level": None,
    "level_weight": None,  # with a number level: ticks it counts for against the day's mean; None: fixed
    "level_band": 20,  # hold the full limit against a move this far from the level
    "level_exit": None,  # flatten once back within this of the level; None: hold until the other band
    "level_guard": None,  # past this many level_bands from the level, drop the bet (target 0) until back within one band
    # Changepoint detection on a number level (see changepoint_level): the expected ticks between
    # shifts of the level, None for off. It needs the product's reversion to the level a tick and the
    # sd of its one-tick steps, measured on the download (python/experiments/study/sim_regimes.py shows how).
    "cpd_hazard": None,
    "cpd_reversion": None,
    "cpd_sd": None,
    "cpd_block": 50,  # ticks averaged into one observation
    "cpd_action": "level",  # "level": bet around the re-estimated level; "drop": keep the level, drop the bet once it has likely moved
    "cpd_threshold": 0.5,  # "drop": the chance that the level has moved since the open from which the bet is dropped for the day
    # A call option on another product (see follow_target): it takes that product's target as a
    # share of its own limit. None trades the product on its own.
    "follow": None,
    "strike": None,  # the call's strike
    "max_cost_per_delta": 20.0,  # stay flat when half the spread per unit of delta is above this
    # A call priced off a volatility smile fitted on earlier days (see smile_fair): the fair is
    # Black-Scholes at v(m) = a m^2 + b m + c, m = ln(strike / S) / sqrt(T), plus the call's usual
    # offset from that, so take, clear and make trade its fast deviations. None turns it off.
    "smile": None,  # (a, b, c)
    "underlying": None,  # the product S is read from, by this product's fair method
    "expiry": None,  # days to expiry at the open of the day
    "day_length": 1_000_000,  # timestamps in a day, for the time to expiry
    "smile_window": 20,  # ticks the call's offset from the smile is averaged over (EMA)
    # A basket of other products, {leg: weight} (see basket_target). Its spread, the basket's price
    # less the legs' weighted prices, is traded with the level settings, level being its usual value.
    "basket": None,
    "hedge_ratio": 0.0,  # the legs that hedge hold -weight * hedge_ratio per basket (or delta * hedge_ratio per smile call) held
    "hedge": False,  # a basket leg: hold what the baskets it belongs to want against them
    # Fading jumps that snap back (see jump_target): a move of the fair value at least this big
    # is a jump. None turns it off. While on, it sets target instead.
    "jump_min": None,
    "jump_hold": None,  # ticks to hold against a jump; None: until the next jump
    "jump_edge": 10,  # clear_edge while the target is against a jump: worth paying, a jump is worth jump_min
    "jump_seen": 5,  # jumps seen today before trading on them
    "jump_share": 0.6,  # the least share of them that reversed the jump before
    # Following named traders (see copy_target): {name: weight}, positive to trade with that
    # name, negative to trade against it. None turns it off. While on, it sets target instead.
    "copy": None,
    "copy_hold": None,  # ticks to hold after a signal; None: until the next one
    # Following an informed trader without a name (experiments.day.informed; Frankfurt Hedgehogs on
    # P3's Olivia): a trade of one of these sizes that buys at the day's running low of the fair, or
    # sells at its high, after copy_warmup ticks, is a signal of weight 1 its way. None: off. It
    # turns copy on alone, and adds to the named weights where both are set.
    "copy_sizes": None,
    "copy_warmup": 100,
    "copy_edge": 5,  # clear_edge while the target follows a signal
    # Protection against a regime the parameters weren't tuned for (see loss_stop, regime_guard;
    # arena.stress tests them).
    "stop_loss": None,  # flatten and stop for the day once today's PnL is this far below its high; None: off
    "stop_edge": None,  # clear_edge while flattening after the stop; None: the book's spread, to reach the other side
    # From flatten_from (a timestamp: on the day, from the round's length) to the close, work the
    # position to zero: no takes, cut it at up to flatten_edge worse than fair (None: the book's
    # spread, to reach the other side), and quote only the side that reduces it. For an exchange
    # that liquidates what is left at a bad price.
    "flatten_from": None,
    "flatten_edge": None,
    # A small end position is cheaper kept than crossed (Capponi et al.): with flatten_keep, a position
    # within it is held (no takes, quotes flatten_widen further out) and a larger one worked down to it.
    "flatten_keep": None,
    "flatten_widen": 0,
    "reduce_only": False,  # quote only the side that moves the position toward target (set while flattening)
    "vol_guard": None,  # fall back to plain market making while recent volatility is this many times the day's
}

# stop_loss is about 3 times the product's largest intraday drawdown on the days it was tuned on
# (arena.stress prints it), so it never fires there: it caps a day the regime changes (IDEAS.md,
# "Stress: what a regime change costs").
# TODO(day): one entry per product from `arena.diagnose all --format qminers --data D --suggest`, prices in the
# product's ticks; the limit comes from the exchange in params_for, so it can't drift from theirs.
PARAMS: dict = {}


# ------------------------------------------------------------------------------ STRATEGY


class Book:
    """Visible order book. Levels are [price, volume] with volume > 0, best price first.

    take and clear reduce level volumes as they trade, so later steps see what's left.
    """

    def __init__(self, bids: list[list[int]], asks: list[list[int]]):
        self.bids = bids
        self.asks = asks

    def copy(self) -> Book:
        return Book([level[:] for level in self.bids], [level[:] for level in self.asks])


class Plan:
    """One product's orders for this tick, keeping all of them inside the position limit.

    Orders can all fill in the same tick, so the room to buy ignores planned sells and vice versa.
    The room is the full room under the limit: EXECUTION cancels any resting order the plan
    doesn't keep, and cancels free their room before new orders are checked.

    Where orders reach the exchange a step or more late (EXECUTION's on_the_way), the orders sent
    and not yet there start the plan as planned, since they may all fill and can't be cancelled
    yet, and the resting orders whose cancels haven't arrived hold their room, not the net, as
    they may fill first.
    """

    def __init__(self, position: int, limit: int, sent: list[tuple[int, int, bool]] = (), cancelling: list[tuple] = ()):
        self.position = position
        self.limit = limit
        self.bought = sum(quantity for _, quantity, _ in sent if quantity > 0)
        self.sold = -sum(quantity for _, quantity, _ in sent if quantity < 0)
        self.held_buy = sum(quantity for _, _, quantity in cancelling if quantity > 0)
        self.held_sell = -sum(quantity for _, _, quantity in cancelling if quantity < 0)
        self.takes: list[tuple[int, int]] = []  # (price, signed quantity) trading with the book now
        self.quotes: list[tuple[int, int]] = []  # (price, signed quantity) waiting to be hit
        # What the strategy decided, for the products traded after this one (see Market).
        self.fair: float | None = None
        self.target = 0
        self.legs: dict[str, float] = {}  # a basket's wish for each leg that hedges it

    @property
    def net(self) -> int:
        """Position if every planned order fills."""
        return self.position + self.bought - self.sold

    @property
    def buy_room(self) -> int:
        return self.limit - self.position - self.bought - self.held_buy

    @property
    def sell_room(self) -> int:
        return self.limit + self.position - self.sold - self.held_sell

    def buy(self, price: int, quantity: int, quote: bool = False) -> int:
        quantity = min(quantity, self.buy_room)
        if quantity > 0:
            (self.quotes if quote else self.takes).append((price, quantity))
            self.bought += quantity
        return max(quantity, 0)

    def sell(self, price: int, quantity: int, quote: bool = False) -> int:
        quantity = min(quantity, self.sell_room)
        if quantity > 0:
            (self.quotes if quote else self.takes).append((price, -quantity))
            self.sold += quantity
        return max(quantity, 0)


class Market:
    """What one product's strategy sees of the others this tick: every book, before anyone trades,
    the other traders' trades since the last tick as (buyer, seller, quantity, price), and the plans of
    the products traded so far. Trader.run trades a product that follows or hedges another after
    it, so one level of dependency works."""

    def __init__(
        self,
        books: dict[str, Book],
        trades: dict[str, list[tuple[str, str, int, int]]] | None = None,
        fills: dict[str, list[tuple[float, int]]] | None = None,
        timestamp: int = 0,
    ):
        self.books = books
        self.trades = trades or {}
        self.fills = fills or {}  # our own fills since the last tick, as (price, signed quantity)
        self.timestamp = timestamp
        self.plans: dict[str, Plan] = {}


def trade_product(product: str, book: Book, position: int, p: dict, memory: dict, market: Market | None = None,
                  sent: list[tuple[int, int, bool]] = (), cancelling: list[tuple] = ()) -> Plan:
    """Fair value -> take -> clear -> make, on a copy of the book: market.books stays untouched. sent and
    cancelling: what EXECUTION's on_the_way says hasn't reached the exchange yet (see Plan)."""
    plan = Plan(position, p["limit"], sent, cancelling)
    market = market or Market({product: book})
    fair = smile_fair(book, p, memory, market) if p["smile"] is not None else fair_value(book, p, memory)
    if fair is None:  # no price seen yet
        return plan
    spread = book.asks[0][0] - book.bids[0][0] if book.bids and book.asks else 0
    if p["flatten_from"] is not None and market.timestamp >= p["flatten_from"]:
        edge = p["flatten_edge"] if p["flatten_edge"] is not None else spread
        keep = p["flatten_keep"]
        if keep is not None and abs(position) <= keep:  # held to the close, quoted wider
            widen = {k: p[k] + p["flatten_widen"] for k in ("make_edge", "make_edge_buy", "make_edge_sell") if p[k] is not None}
            p = {**p, **widen, "target": position, "take_edge": math.inf, "take_edge_buy": None, "take_edge_sell": None,
                 "clear_edge": -math.inf, "reduce_only": False}
        else:
            target = 0 if keep is None else int(math.copysign(keep, position))
            p = {**p, "target": target, "take_edge": math.inf, "take_edge_buy": None, "take_edge_sell": None, "clear_edge": edge,
                 "reduce_only": True}
    elif p["stop_loss"] is not None and loss_stop(fair, position, market.fills.get(product, []), market.timestamp, p, memory):
        edge = p["stop_edge"] if p["stop_edge"] is not None else spread
        p = {**p, "target": 0, "take_edge": math.inf, "take_edge_buy": None, "take_edge_sell": None, "make_size": 0, "clear_edge": edge}
    elif p["vol_guard"] is not None and regime_guard(fair, p, memory):
        pass  # plain market making toward the static target
    elif p["basket"] is not None:
        p = {**p, "target": basket_target(fair, p, memory, market, plan)}
    elif p["level"] is not None:
        p = {**p, "target": level_target(fair, p, memory)}
    elif p["copy"] is not None or p["copy_sizes"] is not None:
        target = copy_target(market.trades.get(product, []), p, memory, fair, book)
        p = {**p, "target": target, "clear_edge": p["copy_edge"] if target else p["clear_edge"]}
    elif p["jump_min"] is not None:
        target = jump_target(fair, p, memory)
        p = {**p, "target": target, "clear_edge": p["jump_edge"] if target else p["clear_edge"]}
    elif p["follow"] is not None:
        p = {**p, "target": follow_target(book, fair, p, memory, market.plans.get(p["follow"]))}
    elif p["hedge"]:
        p = {**p, "target": hedge_target(product, p, market)}
    if p["smile"] is not None and p["hedge_ratio"]:
        plan.legs = {p["underlying"]: -p["hedge_ratio"] * memory.get("delta", 0.0) * position}
    plan.fair, plan.target = fair, p["target"]
    trend, recent = moves(fair, p, memory)
    if p["imbalance"] and book.bids and book.asks:
        fair += p["imbalance"] * imbalance(book)
    if p["lin_rho3"] and book.bids and book.asks:
        fair += p["lin_rho3"] * depth_imbalance(book, 3)
    fair += p["lin_momentum"] * trend
    if p["gate_move"] is not None and abs(recent) >= p["gate_move"]:
        p = {**p, "pull": 1 if recent > 0 else -1}
    book = book.copy()  # take and clear use up its levels
    take(book, fair, p, plan)
    clear(book, fair, p, plan)
    make(book, fair, p, plan)
    return plan


def fair_value(book: Book, p: dict, memory: dict) -> float | None:
    if p["fair"] == "fixed":
        if p["fixed_guard"] is not None:
            # A fixed value that the market has left (a level shift, a trend) is no longer the value.
            # The sized mid, not the wall mid: a rival's large order far from the touch would move
            # the wall mid past the guard (IDEAS.md, "Adversarial rivals"). Where a side has no
            # level of wall_size it uses the best one, so the guard doesn't flicker off in a trend.
            market = mid(_sized(book.bids, p["wall_size"]), _sized(book.asks, p["wall_size"]))
            if market is not None and abs(market - p["fixed_fair"]) > p["fixed_guard"]:
                return market
        return p["fixed_fair"]
    fair = price(book, p)
    previous = memory.get("fair")
    if fair is None:  # one side of the book is empty: keep the last value
        return previous
    if p["fair"] == "hysteresis_mid":
        if fair == math.floor(fair):
            # A spread of an even number of ticks puts the mid on a tick: take the half tick on the side
            # of the last value instead, so a one-tick book's mid doesn't flicker between x and x.5.
            last = memory.get("hysteresis")
            fair += 0.5 if last is not None and last > fair else -0.5
        memory["hysteresis"] = fair
    if previous is not None and p["smoothing"]:
        fair = p["smoothing"] * previous + (1 - p["smoothing"]) * fair
    memory["fair"] = fair
    return fair


def price(book: Book, p: dict) -> float | None:
    """The book's price by p's fair-value method, before smoothing. None if a side is empty."""
    method = p["fair"]
    if method == "fixed":
        return p["fixed_fair"]
    if method in ("mid", "hysteresis_mid"):
        fair = mid(book.bids, book.asks)
    elif method == "wall_mid":
        # Market-making bots quote the largest size at stable prices. The midpoint of those
        # "walls" is much less noisy than the plain mid, which small orders keep moving.
        fair = mid(_wall(book.bids), _wall(book.asks))
    elif method == "outer_mid":
        # The outermost bid and ask, where the market maker usually sits (Frankfurt Hedgehogs).
        fair = mid(book.bids[-1:], book.asks[-1:])
    elif method == "sized_mid":
        # The first level from the top with at least wall_size. Unlike the largest or outermost
        # level, a large order far from the touch can't move it, so it holds up when other
        # traders' resting orders share the book (IDEAS.md, wall-mid definitions).
        fair = mid(_sized(book.bids, p["wall_size"]), _sized(book.asks, p["wall_size"]))
    elif method == "weighted_mid":
        # The best prices weighted by the other side's volume, I*ask + (1-I)*bid with I = Vb/(Vb+Va):
        # what most teams call the micro-price (Stoikov's is between it and the mid).
        if not book.bids or not book.asks:
            return None
        share = book.bids[0][1] / (book.bids[0][1] + book.asks[0][1])
        fair = share * book.asks[0][0] + (1 - share) * book.bids[0][0]
    else:
        raise ValueError(f"unknown fair value method {method!r}")
    return fair


def imbalance(book: Book) -> float:
    """(Vb - Va)/(Vb + Va) at the best bid and ask, in [-1, 1]."""
    bid, ask = book.bids[0][1], book.asks[0][1]
    return (bid - ask) / (bid + ask)


def depth_imbalance(book: Book, depth: int) -> float:
    """(Vb - Va)/(Vb + Va) over the best `depth` levels a side."""
    bid, ask = sum(v for _, v in book.bids[:depth]), sum(v for _, v in book.asks[:depth])
    return (bid - ask) / (bid + ask)


def moves(fair: float, p: dict, memory: dict) -> tuple[float, float]:
    """The fair's move over lin_window and over gate_window ticks (0 until it has that many), for
    the linear fair and the gate; memory keeps the last fairs, only while either is on."""
    windows = (p["lin_window"] if p["lin_momentum"] else 0, p["gate_window"] if p["gate_move"] is not None else 0)
    if not any(windows):
        return 0.0, 0.0
    trail = memory.setdefault("trail", [])
    trail.append(fair)
    del trail[:-max(windows) - 1]
    return tuple(fair - trail[-k - 1] if k and len(trail) > k else 0.0 for k in windows)


def mid(bids: list[list[int]], asks: list[list[int]]) -> float | None:
    if not bids or not asks:
        return None
    return (bids[0][0] + asks[0][0]) / 2


def _wall(levels: list[list[int]]) -> list[list[int]]:
    """The level with the most volume, as a one-level list (empty if there are no levels)."""
    return [max(levels, key=lambda level: level[1])] if levels else []


def _sized(levels: list[list[int]], size: int) -> list[list[int]]:
    """The first level from the top with at least `size`, else the best level, as a one-level list."""
    return next(([level] for level in levels if level[1] >= size), levels[:1])


def level_target(fair: float, p: dict, memory: dict) -> int:
    """The position to hold when the product returns to a level: short above it, long below.

    Beyond level_band from the level, the target is the full limit against the move. Inside the
    band it keeps its last value, so the position isn't traded back and forth on every tick (each
    trade toward the target can cost half the spread), until the price reaches the other band or,
    with level_exit, comes back within level_exit of the level or goes past it. (Past it counts
    because prices jump: a gap of exactly 0 may never be seen.) On P4 Hydrogel and Velvetfruit a
    level taken from the other days made 1.7 times as much as the day's own mean (IDEAS.md).
    """
    gap = fair - estimate_level(fair, p, memory)
    held = memory.get("held", 0)
    exit_within = p["level_exit"]
    if p["level_guard"] is not None:
        # The level may have moved: past level_guard bands, stop betting on it until the price is
        # back within one band (not just inside the guard, or it trades in and out at the guard).
        if abs(gap) > p["level_guard"] * p["level_band"]:
            memory["broken"] = True
        elif abs(gap) < p["level_band"]:
            memory.pop("broken", None)
    if p["cpd_hazard"] is not None and p["cpd_action"] == "drop" and memory.get("cp_moved", 0) > p["cpd_threshold"]:
        memory["broken"] = True  # the level has likely moved: no bet on it for the rest of the day
    if memory.get("broken"):
        held = 0
    elif gap >= p["level_band"]:
        held = -p["limit"]
    elif gap <= -p["level_band"]:
        held = p["limit"]
    elif exit_within is not None and ((held < 0 and gap <= exit_within) or (held > 0 and gap >= -exit_within)):
        held = 0
    memory["held"] = held
    return held


def loss_stop(fair: float, position: int, fills: list[tuple[float, int]], timestamp: int, p: dict, memory: dict) -> bool:
    """True once today's PnL on this product has fallen stop_loss below its high: then the product
    only flattens (crossing up to stop_edge) until the day ends.

    PnL is cash from our fills plus the position at fair. A timestamp lower than the last one is a
    new day: the stop resets, and a position carried over starts at zero PnL.
    """
    if timestamp < memory.get("stop_t", -1):
        memory.pop("stopped", None)
        memory["cash"], memory["peak"] = -position * fair, 0.0
    memory["stop_t"] = timestamp
    memory["cash"] = memory.get("cash", 0.0) - sum(price * quantity for price, quantity in fills)
    pnl = memory["cash"] + position * fair
    memory["peak"] = max(memory.get("peak", 0.0), pnl)
    if memory["peak"] - pnl > p["stop_loss"]:
        memory["stopped"] = True
    return memory.get("stopped", False)


def regime_guard(fair: float, p: dict, memory: dict) -> bool:
    """True while the fair value's recent volatility is vol_guard times its volatility over the day.

    Exponential averages of squared one-tick changes, over about 20 and 1,000 ticks, after 200
    ticks of warm-up. While it holds, the product drops its target bets (level, jump, copy, basket,
    follow) and makes markets around its static target. A rough stand-in for a changepoint detector
    (Adams & MacKay, references/wiki/sources/online-changepoint-detection.md).
    """
    last = memory.get("vg_last")
    memory["vg_last"] = fair
    if last is None:
        return False
    change = (fair - last) ** 2
    memory["vg_fast"] = 0.95 * memory.get("vg_fast", change) + 0.05 * change
    memory["vg_slow"] = 0.999 * memory.get("vg_slow", change) + 0.001 * change
    memory["vg_n"] = memory.get("vg_n", 0) + 1
    return memory["vg_n"] >= 200 and memory["vg_fast"] > p["vol_guard"] ** 2 * max(memory["vg_slow"], 1e-9)


def estimate_level(fair: float, p: dict, memory: dict) -> float:
    """The level: the configured one, the mean of the day so far, or a blend of the two.

    With level_weight, a number level counts as that many ticks of the day's mean, so a day that
    settles elsewhere slowly moves it.
    """
    memory["level_sum"] = memory.get("level_sum", 0.0) + fair
    memory["level_n"] = memory.get("level_n", 0) + 1
    if p["level"] == "day":
        return memory["level_sum"] / memory["level_n"]
    if p["cpd_hazard"] is not None:
        return changepoint_level(fair, p, memory)
    if p["level_weight"] is None:
        return p["level"]
    return (p["level"] * p["level_weight"] + memory["level_sum"]) / (p["level_weight"] + memory["level_n"])


def changepoint_level(fair: float, p: dict, memory: dict) -> float:
    """The level, re-estimated when it shifts: online changepoint detection (Adams & MacKay 2007).

    The fair value is averaged over blocks of cpd_block ticks. For a product that returns to its
    level mu at rate theta a tick, consecutive block means follow x_k = mu + phi (x_{k-1} - mu) + e
    with phi = exp(-theta B), so z_k = (x_k - phi x_{k-1}) / (1 - phi) is an independent, noisy
    observation of mu. Each run length r (blocks since the last shift) keeps a Gaussian posterior
    for mu. A shift happens with chance B / cpd_hazard per block; a new run's mu starts near the
    latest block mean. The level used is the posterior mean of mu over all run lengths: the
    configured level until the evidence moves it, the new one soon after a shift.
    """
    memory["cp_sum"] = memory.get("cp_sum", 0.0) + fair
    memory["cp_n"] = memory.get("cp_n", 0) + 1
    if memory["cp_n"] < p["cpd_block"]:
        return memory.get("cp_level", p["level"]) if p["cpd_action"] == "level" else p["level"]
    x = memory.pop("cp_sum") / memory.pop("cp_n")
    block, theta, sd = p["cpd_block"], p["cpd_reversion"], p["cpd_sd"]
    phi = math.exp(-theta * block)
    stationary = sd * sd / (2 * theta)  # the variance of the price around its level
    noise = stationary * (1 - phi * phi) / (1 - phi) ** 2  # the variance of one observation z of mu
    runs = memory.get("cp_runs") or [[1.0, p["level"], stationary / 4, 0]]  # [chance, mean, variance, first block]
    last = memory.get("cp_last")
    memory["cp_last"] = x
    memory["cp_k"] = k = memory.get("cp_k", 0) + 1
    if last is not None:
        z = (x - phi * last) / (1 - phi)
        hazard = min(block / p["cpd_hazard"], 1.0)
        grown, shifted = [], 0.0
        for chance, mean, var, first in runs:
            spread = var + noise
            likelihood = math.exp(-((z - mean) ** 2) / (2 * spread)) / math.sqrt(spread)
            grown.append([chance * likelihood * (1 - hazard), (mean / var + z / noise) / (1 / var + 1 / noise), 1 / (1 / var + 1 / noise), first])
            shifted += chance * likelihood * hazard
        runs = [[shifted, x, stationary, k]] + grown
        total = sum(r[0] for r in runs) or 1.0
        runs = sorted(([c / total, m, v, f] for c, m, v, f in runs if c / total > 1e-6), reverse=True)[:40]
    memory["cp_runs"] = runs
    memory["cp_moved"] = 1 - sum(c for c, _, _, first in runs if first == 0)  # chance it shifted since the open
    memory["cp_level"] = sum(c * m for c, m, _, _ in runs) / sum(c for c, _, _, _ in runs)
    return memory["cp_level"] if p["cpd_action"] == "level" else p["level"]


def jump_target(fair: float, p: dict, memory: dict) -> int:
    """The position to hold when the price jumps and snaps back: the full limit against the last jump.

    A move of the fair value by at least jump_min is a jump. Once jump_seen jumps have followed
    another today, and at least jump_share of those went the opposite way, each jump sets the
    target to the full limit against it, held for jump_hold ticks or until the next jump. Before
    that, or when too few reverse, the target is 0. The share is measured on the day itself, so
    the rule can run on every product: in P4 round 5's data the jumps came on one product and day
    (ROBOT_DISHES, steps of 100, 87% reversed), and a team reports them on another one live. On
    every round 5 product it added 501k over three days to plain market making, its worst day
    +4k; fading every jump instead lost 184k on one day (IDEAS.md).
    """
    last, memory["jump_last"] = memory.get("jump_last"), fair
    held, age = memory.get("held", 0), memory.get("jump_age", 0) + 1
    if last is not None and abs(fair - last) >= p["jump_min"]:
        sign = 1 if fair > last else -1
        if memory.get("jump_sign"):
            memory["jump_n"] = memory.get("jump_n", 0) + 1
            memory["jump_rev"] = memory.get("jump_rev", 0) + (sign != memory["jump_sign"])
        memory["jump_sign"] = sign
        n, reversed_ = memory.get("jump_n", 0), memory.get("jump_rev", 0)
        held = -sign * p["limit"] if n >= p["jump_seen"] and reversed_ >= p["jump_share"] * n else 0
        age = 0
    elif p["jump_hold"] is not None and age >= p["jump_hold"]:
        held = 0
    memory["held"], memory["jump_age"] = held, age
    return held


def copy_target(trades: list[tuple[str, str, int, int]], p: dict, memory: dict, fair: float = 0.0, book: Book | None = None) -> int:
    """The position to hold when some traders know where the price is going: up to the full limit their way.

    Each trade since the last tick adds the buyer's weight in copy and takes away the seller's.
    A non-zero sum, capped at 1 either way, sets the target to that share of the limit, held for
    copy_hold ticks or until the next signal: a weight of 0.5 leaves half the room to market making. On P3 round 5, Olivia bought at or near the day's low and sold at
    or near its high on all 19 of her trades (Kelp, Squid Ink, Croissants) (IDEAS.md).
    """
    weights = p["copy"] or {}
    signal = sum(weights.get(buyer, 0) - weights.get(seller, 0) for buyer, seller, _, _ in trades)
    if p["copy_sizes"] is not None:
        signal += informed_signal(trades, fair, book, p, memory)
    held, age = memory.get("held", 0), memory.get("copy_age", 0) + 1
    if signal:
        held, age = round(max(-1.0, min(1.0, signal)) * p["limit"]), 0
    elif p["copy_hold"] is not None and age >= p["copy_hold"]:
        held = 0
    memory["held"], memory["copy_age"] = held, age
    return held


def informed_signal(trades: list[tuple[str, str, int, int]], fair: float, book: Book | None, p: dict, memory: dict) -> int:
    """+1 for each trade of a copy_sizes size that bought at the day's running low of the fair, -1 for
    each that sold at its high. The trades since the last call printed against the book and fair of the
    last call: a trade's side is read from that book (at or above its ask a buy, at or below its bid a
    sell, inside it by the mid), and it is at an extreme if that fair was at or beyond every fair before it."""
    low, high, seen = memory.get("cp_low"), memory.get("cp_high"), memory.get("cp_ticks", 0)
    last, bid, ask = memory.get("cp_fair"), memory.get("cp_bid"), memory.get("cp_ask")
    signal = 0
    if seen >= p["copy_warmup"] and None not in (bid, ask, low, high, last):
        for _, _, quantity, price in trades:
            if quantity in p["copy_sizes"]:
                buying = price >= ask or (price > bid and price >= (bid + ask) / 2)
                if buying and last <= low:
                    signal += 1
                elif not buying and last >= high:
                    signal -= 1
    if last is not None:  # the extremes before the latest fair
        memory["cp_low"] = last if low is None else min(low, last)
        memory["cp_high"] = last if high is None else max(high, last)
    memory["cp_fair"], memory["cp_ticks"] = fair, seen + 1
    if book is not None and book.bids and book.asks:
        memory["cp_bid"], memory["cp_ask"] = book.bids[0][0], book.asks[0][0]
    return signal


def follow_target(book: Book, fair: float, p: dict, memory: dict, underlying: Plan | None) -> int:
    """A call option's target: the underlying's target as a share of the option's own limit.

    Each unit then adds its delta to the underlying's view, so the options are extra room for the
    same bet: on P4 the vouchers' implied volatility was flat within a day, and the teams' voucher
    PnL was almost exactly delta times the underlying's move (IDEAS.md). A strike stays flat when
    crossing its spread costs more than max_cost_per_delta per unit of delta, in the underlying's
    price units: deep in-the-money calls have a delta of 1 but a much wider spread. Delta comes
    from the option's own price, so no expiry date is needed. If the underlying wasn't traded
    this tick, the last target is kept.
    """
    if underlying is None or underlying.fair is None or not book.bids or not book.asks:
        return memory.get("held", 0)
    s, k = underlying.fair, p["strike"]
    delta = call_delta(s, k, implied_variance(fair, s, k))
    half_spread = (book.asks[0][0] - book.bids[0][0]) / 2
    cost = half_spread / delta if delta > 1e-6 else 1e9
    # Averaged over about 20 ticks, so a spread that widens for a tick doesn't flip the strike.
    cost = memory["cost"] = cost if "cost" not in memory else 0.95 * memory["cost"] + 0.05 * cost
    if cost > p["max_cost_per_delta"]:
        held = 0
    else:
        held = round(underlying.target / underlying.limit * p["limit"])
    memory["held"] = held
    return held


# Black-Scholes for a call with no interest, in terms of the total variance w = sigma^2 * T to
# expiry. Price and delta depend on sigma and T only through w, so w can be implied from the
# option's own price without knowing the expiry.
_NORMAL = NormalDist()


def call_price(s: float, k: float, w: float) -> float:
    if w <= 0:
        return max(s - k, 0.0)
    d1 = (math.log(s / k) + w / 2) / math.sqrt(w)
    return s * _NORMAL.cdf(d1) - k * _NORMAL.cdf(d1 - math.sqrt(w))


def call_delta(s: float, k: float, w: float) -> float:
    if w <= 0:
        return 1.0 if s > k else 0.0
    return _NORMAL.cdf((math.log(s / k) + w / 2) / math.sqrt(w))


def implied_variance(price: float, s: float, k: float) -> float:
    """The w at which call_price matches price: 0 at or below intrinsic value (bisection)."""
    if price <= max(s - k, 0.0):
        return 0.0
    lo, hi = 0.0, 4.0  # w = 4 is a volatility of 200% for a year
    for _ in range(50):
        mid_w = (lo + hi) / 2
        if call_price(s, k, mid_w) < price:
            lo = mid_w
        else:
            hi = mid_w
    return (lo + hi) / 2


def smile_fair(book: Book, p: dict, memory: dict, market: Market) -> float | None:
    """A call's fair value: Black-Scholes at the smile's volatility, plus its usual offset from that.

    The smile v(m) = a m^2 + b m + c in m = ln(strike / S) / sqrt(T) is fitted on earlier days
    (python/experiments/day/p3_smile.py does it), S is the underlying's price and T the years to expiry. A
    strike keeps a steady offset from any fitted smile (P3's volcanic vouchers: up to 2 a day), so
    the fair adds the EMA of the call's own price less the model, up to the last tick; what is
    left to trade is the fast deviation. Keeps the last fair while either book has an empty side.
    """
    underlying = market.books.get(p["underlying"])
    s = price(underlying, p) if underlying is not None else None
    own = price(book, p)
    if s is None or own is None:
        return memory.get("fair")
    k, t = p["strike"], max(p["expiry"] - market.timestamp / p["day_length"], 1e-6) / 365
    a, b, c = p["smile"]
    m = math.log(k / s) / math.sqrt(t)
    w = max(a * m * m + b * m + c, 0.0) ** 2 * t
    model = call_price(s, k, w)
    memory["delta"] = call_delta(s, k, w)
    offset = memory.get("offset", own - model)
    memory["offset"] = offset + 2 / (p["smile_window"] + 1) * (own - model - offset)
    memory["fair"] = model + offset
    return memory["fair"]


def basket_target(fair: float, p: dict, memory: dict, market: Market, plan: Plan) -> int:
    """A basket's target: level_target on its spread, the basket's price less its legs' weighted prices.

    level is the spread's usual value, the premium. A family whose prices sum to a constant is a
    basket too: one member, the others as legs of weight -1, level the constant. Each leg that
    hedges is asked for -weight * hedge_ratio times the target (plan.legs). Legs are priced by the
    basket's fair method; if one has no price this tick, the last target is kept.
    """
    legs = [price(market.books[leg], p) if leg in market.books else None for leg in p["basket"]]
    if None in legs:
        target = memory.get("held", 0)
    else:
        spread = fair - sum(weight * leg for weight, leg in zip(p["basket"].values(), legs))
        target = level_target(spread, p, memory)
    plan.legs = {leg: -weight * p["hedge_ratio"] * target for leg, weight in p["basket"].items()}
    return target


def hedge_target(product: str, p: dict, market: Market) -> int:
    """A basket leg's target: what the baskets it belongs to want held against them, within the limit."""
    wanted = sum(plan.legs.get(product, 0.0) for plan in market.plans.values())
    return max(-p["limit"], min(p["limit"], round(wanted)))


def take(book: Book, fair: float, p: dict, plan: Plan) -> None:
    """Trade against book orders priced at least take_edge (each side's own, if set) better than fair."""
    buy_edge = p["take_edge"] if p["take_edge_buy"] is None else p["take_edge_buy"]
    sell_edge = p["take_edge"] if p["take_edge_sell"] is None else p["take_edge_sell"]
    for level in book.asks:
        if level[0] > fair - buy_edge:
            break
        level[1] -= plan.buy(level[0], _crossable(level[1], p, plan))
    for level in book.bids:
        if level[0] < fair + sell_edge:
            break
        level[1] -= plan.sell(level[0], _crossable(level[1], p, plan))


def _crossable(volume: int, p: dict, plan: Plan) -> int:
    """What cross_max leaves of a level's volume to cross this tick."""
    if p["cross_max"] is None:
        return volume
    return min(volume, max(p["cross_max"] - sum(abs(q) for _, q in plan.takes), 0))


def clear(book: Book, fair: float, p: dict, plan: Plan) -> None:
    """Trade inventory back to target at (or close to) fair, freeing room for better trades later."""
    target, excess = p["target"], p["cross_excess"] or 0
    if plan.net > target + excess:
        for level in book.bids:
            if level[0] < fair - p["clear_edge"] or plan.net <= target + excess:
                break
            level[1] -= plan.sell(level[0], _crossable(min(level[1], plan.net - target - excess), p, plan))
    elif plan.net < target - excess:
        for level in book.asks:
            if level[0] > fair + p["clear_edge"] or plan.net >= target - excess:
                break
            level[1] -= plan.buy(level[0], _crossable(min(level[1], target - excess - plan.net), p, plan))


def make(book: Book, fair: float, p: dict, plan: Plan) -> None:
    """Quote both sides around fair, then shift both quotes against inventory.

    Each quote sits make_edge from fair, or make_inside ticks inside the best remaining book quote
    if that's further out (no point quoting better than needed). With make_inside None it sits at
    make_edge whatever the book: for a market shared with rivals whose quotes we may not see (per
    tick nobody's orders rest), and the nearer one to fair takes each trade first. skew then moves both quotes down
    when above target and up when below, by up to skew ticks a full limit away, to work the
    position back toward target. Quotes never cross the book, and the bid stays below the ask:
    if they meet, the side that would add to inventory steps back (the bid, at or above target).

    size_skew works through size instead (Bouchaud et al. 2018, eq. 17.4): with gap the distance
    above target as a share of the limit, the bid is scaled by max(1 - size_skew * gap, 0) and the
    ask by max(1 + size_skew * gap, 0), within the room left. With reduce_only, only the side that
    moves the position toward target quotes, and no more than the gap.
    """
    best_bid = next((price for price, volume in book.bids if volume > 0), None)
    best_ask = next((price for price, volume in book.asks if volume > 0), None)

    bid = math.floor(fair - (p["make_edge"] if p["make_edge_buy"] is None else p["make_edge_buy"]))
    ask = math.ceil(fair + (p["make_edge"] if p["make_edge_sell"] is None else p["make_edge_sell"]))
    if best_bid is not None and p["make_inside"] is not None:
        bid = min(bid, best_bid + p["make_inside"])
    if best_ask is not None and p["make_inside"] is not None:
        ask = max(ask, best_ask - p["make_inside"])

    shift = round(p["skew"] * (plan.net - p["target"]) / plan.limit)
    bid, ask = bid - shift, ask - shift
    if best_ask is not None:
        bid = min(bid, best_ask - 1)
    if best_bid is not None:
        ask = max(ask, best_bid + 1)
    if bid >= ask:  # a narrow book and a skew can bring them together: move the side that adds to inventory
        if plan.net >= p["target"]:
            bid = ask - 1
        else:
            ask = bid + 1
    if p["join_min"] is not None and best_bid is not None and best_ask is not None:
        bids, asks = _volume(book.bids, best_bid), _volume(book.asks, best_ask)
        if bid == best_bid and (bids < p["join_min"] or asks > p["join_ratio"] * bids):
            bid -= 1
        if ask == best_ask and (asks < p["join_min"] or bids > p["join_ratio"] * asks):
            ask += 1

    size = p["make_size"]
    gap = p["size_skew"] * (plan.net - p["target"]) / plan.limit
    buy = _scaled(plan.buy_room if size is None else size, 1 - gap)
    sell = _scaled(plan.sell_room if size is None else size, 1 + gap)
    if p["reduce_only"]:
        buy, sell = min(buy, max(p["target"] - plan.net, 0)), min(sell, max(plan.net - p["target"], 0))
    if p["take_reserve"]:
        buy, sell = min(buy, max(plan.buy_room - p["take_reserve"], 0)), min(sell, max(plan.sell_room - p["take_reserve"], 0))
    if p.get("pull") == 1:  # the fair just rose: don't sell into it
        sell = 0
    elif p.get("pull") == -1:
        buy = 0
    levels, step = p["make_levels"], p["make_step"]
    for k in range(levels):  # the first price gets the remainder of an uneven split
        plan.buy(bid - k * step, buy // levels + (buy % levels if k == 0 else 0), quote=True)
        plan.sell(ask + k * step, sell // levels + (sell % levels if k == 0 else 0), quote=True)


def _volume(levels: list[list[int]], price: int) -> int:
    return next((volume for level_price, volume in levels if level_price == price), 0)


def _scaled(size: int, factor: float) -> int:
    return int(size * max(factor, 0.0))


# The target modes in the order trade_product tries them: the first one set decides the target.
_TARGET_MODES = ("basket", "level", "copy", "jump_min", "follow", "hedge")
# Each mode's own settings, which do nothing while it is off (a basket uses the level ones too).
_MODE_SETTINGS = {
    "level": ("level_weight", "level_band", "level_exit", "level_guard", "cpd_hazard"),
    "cpd_hazard": ("cpd_reversion", "cpd_sd", "cpd_block", "cpd_action", "cpd_threshold"),
    "copy": ("copy_hold", "copy_edge"),
    "jump_min": ("jump_hold", "jump_edge", "jump_seen", "jump_share"),
    "follow": ("max_cost_per_delta",),
    "smile": ("expiry", "smile_window"),
    "stop_loss": ("stop_edge",),
    "flatten_from": ("flatten_edge",),
    "vol_guard": (),
}


def param_conflicts(product: str) -> list[str]:
    """The settings in PARAMS[product] that can't matter, each with the reason: a second target mode
    (the first in trade_product's order decides the target), a static target that a mode replaces,
    or a mode's own setting while the mode is off. arena.validate prints them, and a grid axis over
    one of them never changes the PnL. It doesn't trade, so it has no Rust twin."""
    own = PARAMS[product]
    p = {**DEFAULTS, **own}
    found = []
    modes = [mode for mode in _TARGET_MODES if p[mode] not in (None, False)]
    if "basket" in modes and "level" in modes:
        modes.remove("level")  # a basket's level is its spread's usual value
    if len(modes) > 1:
        found.append(f"{modes[0]} sets the target, so {', '.join(modes[1:])} {'is' if len(modes) == 2 else 'are'} ignored")
    if modes and own.get("target", 0) != 0:
        found.append(f"target is ignored: {modes[0]} sets the target")
    for mode, keys in _MODE_SETTINGS.items():
        on = p[mode] is not None or (mode == "level" and p["basket"] is not None) or (mode == "copy" and p["copy_sizes"] is not None)
        found += [f"{key} does nothing without {mode}" for key in keys if key in own and not on]
    if p["fair"] != "fixed":
        found += [f"{key} does nothing unless fair is \"fixed\"" for key in ("fixed_fair", "fixed_guard") if key in own]
    if p["basket"] is not None and p["level"] is None:
        found.append("basket needs level, its spread's usual value")
    return found


# ------------------------------------------------------------------------------ EXECUTION


def execute(plan: Plan, resting: list[tuple[int, int, int]], max_resting: int | None = None, sent: list[tuple[int, int, bool]] = (),
            topup_min: int = 0) -> tuple[list[int], list[tuple[int, int, bool]]]:
    """Turns the plan into (order ids to cancel, new orders as (price, signed quantity, ioc)).

    resting holds the product's resting orders as (id, price, signed quantity left), oldest
    first (ADAPTER's job: ids needn't sort by age), and is always empty where orders don't rest. A resting order is kept, with its place in the queue,
    while a quote on its side and at its price still wants at least its size. The quote then
    only sends the difference. Every other resting order is cancelled. Takes go out as
    immediate-or-cancel, so whatever the book can't fill never rests at a crossing price.
    max_resting, an exchange's cap on the orders a product may have working (ADAPTER passes it):
    the posts beyond the room the kept orders leave are not sent, and the kept ones keep their
    place (cancelling all and posting afresh cost the 2026-10-28 rehearsal's bot 775 of VANTA's PnL).
    sent, the orders on their way (on_the_way): its posts will rest and can't be cancelled before
    they do, so they cover the quotes at their price, after the resting orders, and take room
    under max_resting.
    topup_min (TOPUP_MIN): a shortfall at a price where a kept order already works is posted only once it
    reaches this many lots, so each partial fill doesn't become another order where every order costs a fee.
    """
    wanted: dict[tuple[bool, int], int] = {}  # (buying, price) -> signed quantity still to send
    for price, quantity in plan.quotes:
        key = (quantity > 0, price)
        wanted[key] = wanted.get(key, 0) + quantity
    cancels = []
    for order_id, price, quantity in resting:  # oldest first, as the queue has them
        key = (quantity > 0, price)
        if abs(quantity) <= abs(wanted.get(key, 0)):
            wanted[key] -= quantity
        else:
            cancels.append(order_id)
    if topup_min:
        working = {(quantity > 0, price) for order_id, price, quantity in resting if order_id not in cancels}
        for key in working:
            if key in wanted and abs(wanted[key]) < topup_min:
                wanted[key] = 0
    flying = [(price, quantity) for price, quantity, ioc in sent if not ioc]
    for price, quantity in flying:
        key = (quantity > 0, price)
        if key in wanted:
            wanted[key] -= quantity if abs(quantity) <= abs(wanted[key]) else wanted[key]
    orders = [(price, quantity, True) for price, quantity in plan.takes]
    posts = [(price, quantity, False) for (_, price), quantity in wanted.items() if quantity]
    if max_resting is not None:
        posts = posts[: max(0, max_resting - (len(resting) - len(cancels)) - len(flying))]
    return cancels, orders + posts


def on_the_way(memory: dict, resting: list[tuple]) -> tuple[list[tuple[int, int, bool]], list[tuple], list[tuple]]:
    """What a product's last calls sent that hasn't reached the exchange yet, where orders arrive late
    (the 2026-10-30 rehearsal's exchange applied a step's orders one step later; the bot, seeing only
    what the exchange listed, re-posted every step, the resting cap refused most of it and its limit
    room was spent twice). Returns the orders on their way as (price, signed quantity, ioc), the
    resting orders to manage, and those whose cancels are on their way: they go before the new orders
    arrive, but may fill first. went() keeps each call's; with a delay of 0 nothing is kept.
    """
    batches = memory.get("flight", [])
    sent = [(price, quantity, ioc) for batch in batches for price, quantity, ioc in batch[0]]
    cancelled = {order_id for batch in batches for order_id in batch[1]}
    return sent, [o for o in resting if o[0] not in cancelled], [o for o in resting if o[0] in cancelled]


def went(memory: dict, cancels: list, new: list[tuple[int, int, bool]], delay: int, rest: bool = True) -> None:
    """Keeps this call's cancels and new orders as on their way for the next `delay` calls: an order
    sent now meets the exchange `delay` steps later, after that call, and is listed (or filled) by the one after.
    Where orders don't rest (rest False), only the takes are kept: a quote on its way is gone the step after
    it arrives, and holding its full size against the limit in case all of it fills left the bot quoting
    every other step (P3 round 1 one tick late: 24,588 against 40,472 for not counting at all)."""
    if delay:
        batch = [[price, quantity, ioc] for price, quantity, ioc in new if ioc or rest]
        memory["flight"] = (memory.get("flight", []) + [[batch, list(cancels)]])[-delay:]


# ------------------------------------------------------------------------------ ADAPTER
# TODO(day): the Arena's API. Each function's body raises until it is written for their API; the drill's
# (python/bots/drill/template.py) is in the comment as a model. `api` is whatever their entry hands the bot.


def to_ticks(api, symbol: str, price: float) -> int:
    """Their price as whole ticks of the product."""
    # drill: return round(price / api.tick_size(symbol))
    raise NotImplementedError("TODO(day): to_ticks for the Arena's API")


def to_price(api, symbol: str, ticks: int) -> float:
    """Whole ticks back as the price their API takes."""
    # drill: return round(ticks * api.tick_size(symbol), 10)
    raise NotImplementedError("TODO(day): to_price for the Arena's API")


def read_book(api, symbol: str) -> Book | None:
    """The product's book in ticks, best first, volumes positive; None if it has none this step."""
    # drill: book = api.book(symbol); None if book is None, else
    #        Book([[to_ticks(api, symbol, l.price), l.size] for l in book.bids], [... book.asks])
    raise NotImplementedError("TODO(day): read_book for the Arena's API")


def params_for(api, product: str) -> dict | None:
    """DEFAULTS and the product's PARAMS, or None for a product PARAMS doesn't list. The limit is the smaller
    of PARAMS' and the exchange's (the mock round's lesson: a limit below the exchange's is a choice, one
    above it is rejected orders)."""
    # drill: if product not in PARAMS: return None; reject unknown keys;
    #        return {**DEFAULTS, **PARAMS[product], "limit": api.max_position(product)}
    # here:  "limit": min(PARAMS[product].get("limit", <the exchange's limit>), <the exchange's limit>)
    #        (not DEFAULTS["limit"]: a placeholder of 50 would cap a larger limit, the 2026-11-03 rehearsal's QUILL at 60)
    raise NotImplementedError("TODO(day): params_for for the Arena's API")


def read_trades(api) -> dict[str, list[tuple[str, str, int, int]]]:
    """Trades this step as (buyer, seller, quantity, price in ticks), by product; empty names if they give none."""
    # drill: {s: [("", "", t.size, to_ticks(api, s, t.price)) for t in api.trades(s)] for s in api.symbols()}
    raise NotImplementedError("TODO(day): read_trades for the Arena's API")


def read_fills(api, fills) -> dict[str, list[tuple[float, int]]]:
    """Our fills since the last step, by product, as (price in ticks, signed quantity)."""
    # drill: for f in fills: out.setdefault(f.symbol, []).append((to_ticks(api, f.symbol, f.price), f.size))
    raise NotImplementedError("TODO(day): read_fills for the Arena's API")


def read_resting(api, product: str) -> list[tuple[str, int, int]]:
    """The product's resting orders as (id, price in ticks, signed quantity), oldest first; [] where orders don't rest."""
    # drill: [(o.order_id, to_ticks(api, product, o.price), o.size) for o in api.orders(product)]
    raise NotImplementedError("TODO(day): read_resting for the Arena's API")


def _depends(p: dict) -> bool:
    return p.get("follow") is not None or bool(p.get("hedge"))


class Bot:  # TODO(day): their entry class and method (qminers.ENTRY)
    def __init__(self):
        self.memory: dict = {}  # the instance lives all session, so state stays on it

    def on_tick(self, api) -> None:
        books = {}
        for symbol in api.symbols():
            book = read_book(api, symbol)
            if book is not None:
                books[symbol] = book
        # TODO(day): each api.* call below is the drill's; their time mapped onto 0..999,900 in steps of 100
        market = Market(books, read_trades(api), read_fills(api, api.fills()), api.time)
        # Products that follow or hedge another go last, so they see its plan.
        products = sorted(market.books, key=lambda product: _depends(PARAMS.get(product, {})))
        for product in products:
            # Each product is isolated, so a bug in one doesn't stop the others trading.
            try:
                p = params_for(api, product)
                if p is None:
                    continue
                mine = self.memory.setdefault(product, {})
                sent, resting, cancelling = on_the_way(mine, read_resting(api, product))
                plan = trade_product(product, market.books[product], api.position(product), p, mine, market, sent, cancelling)
                market.plans[product] = plan
                cancels, new = execute(plan, resting, sent=sent, topup_min=TOPUP_MIN)  # TODO(day): max_resting=<their cap> if their exchange caps orders working a product
                went(mine, cancels, new, DELAY, ORDERS_REST)
                for order_id in cancels:
                    api.cancel(order_id)
                for price, quantity, ioc in new:
                    send = api.buy if quantity > 0 else api.sell
                    send(product, to_price(api, product, int(price)), abs(int(quantity)), ioc=ioc)
            except Exception:
                if STRICT:
                    raise
                # Each error once while it repeats: a product broken all day would otherwise print
                # a traceback every tick, and a platform may cap or slow down on that much output.
                error = traceback.format_exc()
                last = self.memory.setdefault("errors", {})
                if last.get(product) != error.splitlines()[-1]:
                    last[product] = error.splitlines()[-1]
                    print(f"{api.time} {product}: {error}")
                # Don't leave stale quotes resting while this product is broken.
                try:
                    for order in api.orders(product):
                        api.cancel(order.order_id)
                except Exception:
                    pass
