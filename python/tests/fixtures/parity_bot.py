"""Snapshot of an early bots/template.py, trading every Prosperity 3 product, for tests/test_parity.py.

Its fills were checked one by one against jmerle's prosperity3bt 0.12.0. Don't edit it:
the expected numbers in the test belong to exactly this code.
"""

from __future__ import annotations

import json
import math
import traceback

from datamodel import Order, OrderDepth, TradingState

# The backtester sets this to True so bugs raise instead of being swallowed.
STRICT = False

DEFAULTS = {
    "limit": 50,  # position limit: must match the competition's
    "fair": "mid",  # "fixed", "mid" or "wall_mid" (see fair_value)
    "fixed_fair": None,  # used when fair is "fixed"
    "smoothing": 0.0,  # 0 uses each tick's fair as is; closer to 1 moves it more slowly
    "take_edge": 1,  # take book orders priced at least this much better than fair
    "clear_edge": 0,  # cut inventory at prices up to this much worse than fair
    "make_edge": 2,  # quote at least this far from fair
    "skew": 0.0,  # move quotes this far against inventory when at the full position limit
    "make_size": None,  # largest quote; None quotes all remaining room under the limit
}

PARAMS = {
    # IMC Prosperity 3, round 1
    "RAINFOREST_RESIN": {"limit": 50, "fair": "fixed", "fixed_fair": 10_000},
    "KELP": {"limit": 50, "fair": "wall_mid", "make_edge": 1},
    # IMC Prosperity 2, round 1
    "AMETHYSTS": {"limit": 20, "fair": "fixed", "fixed_fair": 10_000},
    "STARFRUIT": {"limit": 20, "fair": "wall_mid", "make_edge": 1},
}


# ------------------------------------------------------------------------------ STRATEGY


class Book:
    """Visible order book. Levels are [price, volume] with volume > 0, best price first.

    take and clear reduce level volumes as they trade, so later steps see what's left.
    """

    def __init__(self, bids: list[list[int]], asks: list[list[int]]):
        self.bids = bids
        self.asks = asks


class Plan:
    """One product's orders for this tick, keeping all of them inside the position limit.

    Orders can all fill in the same tick, so the room to buy ignores planned sells and vice versa.
    """

    def __init__(self, position: int, limit: int):
        self.position = position
        self.limit = limit
        self.bought = 0
        self.sold = 0
        self.orders: list[tuple[int, int]] = []  # (price, signed quantity)

    @property
    def net(self) -> int:
        """Position if every planned order fills."""
        return self.position + self.bought - self.sold

    def buy(self, price: int, quantity: int) -> int:
        quantity = min(quantity, self.limit - self.position - self.bought)
        if quantity > 0:
            self.orders.append((price, quantity))
            self.bought += quantity
        return max(quantity, 0)

    def sell(self, price: int, quantity: int) -> int:
        quantity = min(quantity, self.limit + self.position - self.sold)
        if quantity > 0:
            self.orders.append((price, -quantity))
            self.sold += quantity
        return max(quantity, 0)


def trade_product(book: Book, position: int, p: dict, memory: dict) -> list[tuple[int, int]]:
    fair = fair_value(book, p, memory)
    if fair is None:  # no price seen yet
        return []
    plan = Plan(position, p["limit"])
    take(book, fair, p, plan)
    clear(book, fair, p, plan)
    make(book, fair, p, plan)
    return plan.orders


def fair_value(book: Book, p: dict, memory: dict) -> float | None:
    method = p["fair"]
    if method == "fixed":
        return p["fixed_fair"]
    if method == "mid":
        fair = mid(book.bids, book.asks)
    elif method == "wall_mid":
        # Market-making bots quote the largest size at stable prices. The midpoint of those
        # "walls" is much less noisy than the plain mid, which small orders keep moving.
        fair = mid(_wall(book.bids), _wall(book.asks))
    else:
        raise ValueError(f"unknown fair value method {method!r}")

    previous = memory.get("fair")
    if fair is None:  # one side of the book is empty: keep the last value
        return previous
    if previous is not None and p["smoothing"]:
        fair = p["smoothing"] * previous + (1 - p["smoothing"]) * fair
    memory["fair"] = fair
    return fair


def mid(bids: list[list[int]], asks: list[list[int]]) -> float | None:
    if not bids or not asks:
        return None
    return (bids[0][0] + asks[0][0]) / 2


def _wall(levels: list[list[int]]) -> list[list[int]]:
    """The level with the most volume, as a one-level list (empty if there are no levels)."""
    return [max(levels, key=lambda level: level[1])] if levels else []


def take(book: Book, fair: float, p: dict, plan: Plan) -> None:
    """Trade against book orders priced at least take_edge better than fair."""
    for level in book.asks:
        if level[0] > fair - p["take_edge"]:
            break
        level[1] -= plan.buy(level[0], level[1])
    for level in book.bids:
        if level[0] < fair + p["take_edge"]:
            break
        level[1] -= plan.sell(level[0], level[1])


def clear(book: Book, fair: float, p: dict, plan: Plan) -> None:
    """Cut inventory at (or close to) fair, freeing room under the limit for better trades later."""
    if plan.net > 0:
        for level in book.bids:
            if level[0] < fair - p["clear_edge"] or plan.net <= 0:
                break
            level[1] -= plan.sell(level[0], min(level[1], plan.net))
    elif plan.net < 0:
        for level in book.asks:
            if level[0] > fair + p["clear_edge"] or plan.net >= 0:
                break
            level[1] -= plan.buy(level[0], min(level[1], -plan.net))


def make(book: Book, fair: float, p: dict, plan: Plan) -> None:
    """Quote both sides around fair, shifted against inventory.

    Quotes step one tick inside the best remaining book quotes when there's room, rather than
    sitting further out than needed, and never cross the book.
    """
    reservation = fair - p["skew"] * plan.net / plan.limit
    bid = math.floor(reservation - p["make_edge"])
    ask = math.ceil(reservation + p["make_edge"])

    best_bid = next((price for price, volume in book.bids if volume > 0), None)
    best_ask = next((price for price, volume in book.asks if volume > 0), None)
    if best_bid is not None:
        bid = min(bid, best_bid + 1)
        ask = max(ask, best_bid + 1)
    if best_ask is not None:
        ask = max(ask, best_ask - 1)
        bid = min(bid, best_ask - 1)

    size = p["make_size"]
    plan.buy(bid, plan.limit if size is None else size)
    plan.sell(ask, plan.limit if size is None else size)


# ------------------------------------------------------------------------------ ADAPTER


def read_book(depth: OrderDepth) -> Book:
    bids = [[price, volume] for price, volume in sorted(depth.buy_orders.items(), reverse=True)]
    asks = [[price, -volume] for price, volume in sorted(depth.sell_orders.items())]
    return Book(bids, asks)


def load_memory(trader_data: str) -> dict:
    try:
        memory = json.loads(trader_data) if trader_data else {}
    except ValueError:
        return {}
    return memory if isinstance(memory, dict) else {}


def params_for(product: str) -> dict | None:
    if product not in PARAMS:
        return None
    unknown = set(PARAMS[product]) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"unknown params for {product}: {', '.join(sorted(unknown))}")
    return {**DEFAULTS, **PARAMS[product]}


class Trader:
    def run(self, state: TradingState):
        memory = load_memory(state.traderData)
        orders: dict[str, list[Order]] = {}
        for product, depth in state.order_depths.items():
            # Each product is isolated, so a bug in one doesn't stop the others trading.
            try:
                p = params_for(product)
                if p is None:
                    continue
                quotes = trade_product(read_book(depth), state.position.get(product, 0), p, memory.setdefault(product, {}))
            except Exception:
                if STRICT:
                    raise
                print(f"{state.timestamp} {product}: {traceback.format_exc()}")
                continue
            orders[product] = [Order(product, int(price), int(quantity)) for price, quantity in quotes]
        return orders, 0, json.dumps(memory)

# Parity-test variant: trade every Prosperity 3 product off the plain mid.
PARAMS.update({
    product: {"limit": limit, "fair": "mid", "make_edge": 1}
    for product, limit in {
        "SQUID_INK": 50, "CROISSANTS": 250, "JAMS": 350, "DJEMBES": 60, "PICNIC_BASKET1": 60,
        "PICNIC_BASKET2": 100, "VOLCANIC_ROCK": 400, "VOLCANIC_ROCK_VOUCHER_9500": 200,
        "VOLCANIC_ROCK_VOUCHER_9750": 200, "VOLCANIC_ROCK_VOUCHER_10000": 200,
        "VOLCANIC_ROCK_VOUCHER_10250": 200, "VOLCANIC_ROCK_VOUCHER_10500": 200, "MAGNIFICENT_MACARONS": 75,
    }.items()
})
