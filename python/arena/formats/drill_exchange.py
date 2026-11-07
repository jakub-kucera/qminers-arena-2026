"""The `exchange` module the drill format provides to bots: the types its API returns.

A bot file defines `class Bot` with `on_tick(self, api)`. It is called once a step, reads the
market through `api` and trades by calling it:

    api.time                         milliseconds since the session opened
    api.symbols()                    the products traded
    api.tick_size(symbol)            price increment, e.g. 0.05
    api.max_position(symbol)         the most the position may be, long or short
    api.book(symbol)                 a Book, or None before the product's first quote
    api.position(symbol)             signed
    api.trades(symbol)               the market's trades in this step, as Trades
    api.fills()                      your own fills since the last step, as Fills
    api.orders(symbol=None)          your resting orders, oldest first, as OrderViews
    api.buy(symbol, price, size, ioc=False) -> order id
    api.sell(symbol, price, size, ioc=False) -> order id
    api.cancel(order_id)

Prices are decimals on each product's tick grid; sizes are positive ints (`buy` and `sell` give
the side). Orders rest until filled or cancelled unless `ioc`. Order ids are opaque strings.
The Bot instance lives for the whole session, so it can keep state on `self`.
"""

from __future__ import annotations

from typing import NamedTuple, Protocol


class Level(NamedTuple):
    price: float
    size: int


class Book(NamedTuple):
    bids: list[Level]  # best first
    asks: list[Level]  # best first


class Trade(NamedTuple):
    price: float
    size: int
    aggressor: str  # "buy" or "sell"


class Fill(NamedTuple):
    order_id: str
    symbol: str
    price: float
    size: int  # signed: positive bought


class OrderView(NamedTuple):
    order_id: str
    symbol: str
    price: float
    size: int  # signed, what is left to fill


class Api(Protocol):
    time: int

    def symbols(self) -> list[str]: ...
    def tick_size(self, symbol: str) -> float: ...
    def max_position(self, symbol: str) -> int: ...
    def book(self, symbol: str) -> Book | None: ...
    def position(self, symbol: str) -> int: ...
    def trades(self, symbol: str) -> list[Trade]: ...
    def fills(self) -> list[Fill]: ...
    def orders(self, symbol: str | None = None) -> list[OrderView]: ...
    def buy(self, symbol: str, price: float, size: int, ioc: bool = False) -> str: ...
    def sell(self, symbol: str, price: float, size: int, ioc: bool = False) -> str: ...
    def cancel(self, order_id: str) -> None: ...
