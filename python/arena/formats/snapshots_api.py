"""The `api` module the snapshots skeleton provides to bots: the types its state holds and its orders take.

A skeleton, not a real competition's module: if the organisers hand out their own module or SDK
file, the plug-in provides that file unchanged instead (ON_THE_DAY.md, "The format swap, step by
step"). A bot file defines `class Strategy` with `on_tick(self, state)`, called once a step:

    state.timestamp                  the step's time
    state.books[product]             a Book: bids and asks as (price, volume), best first
    state.position[product]          signed
    state.trades[product]            the market's trades since the last call, as Trades
    state.fills                      your own fills since the last call, as Fills
    state.open_orders[product]       your resting orders, oldest first, as OpenOrders
    state.limits[product]            the most the position may be, long or short

and returns a list of Order (signed quantity) and Cancel. Prices are decimals; the plug-in turns
them into whole price units. The Strategy instance lives for the whole session.
"""

from __future__ import annotations

from typing import NamedTuple


class Book(NamedTuple):
    bids: list[tuple[float, int]]  # best first
    asks: list[tuple[float, int]]


class Trade(NamedTuple):
    price: float
    quantity: int
    buyer: str = ""
    seller: str = ""


class Fill(NamedTuple):
    order_id: int
    product: str
    price: float
    quantity: int  # signed: positive bought


class OpenOrder(NamedTuple):
    order_id: int
    product: str
    price: float
    quantity: int  # signed, what is left to fill


class Order(NamedTuple):
    product: str
    price: float
    quantity: int  # signed: positive buys
    ioc: bool = False


class Cancel(NamedTuple):
    order_id: int


class State(NamedTuple):
    timestamp: int
    books: dict[str, Book]
    position: dict[str, int]
    trades: dict[str, list[Trade]]
    fills: list[Fill]
    open_orders: dict[str, list[OpenOrder]]
    limits: dict[str, int]
