"""IMC Prosperity's `datamodel` module, which bots import as `from datamodel import ...`.

Same class names, fields and constructor signatures as the official file, without its
jsonpickle dependency. Extensions for the backtester's resting-order mode, which IMC's
exchange doesn't have, are marked "Extension" below: Order's ioc flag, OpenOrder, Cancel and
TradingState.open_orders. Bots that don't use them run unchanged.
"""

from __future__ import annotations

import json
from json import JSONEncoder

Time = int
Symbol = str
Product = str
Position = int
UserId = str
ObservationValue = int

__all__ = [
    "Cancel",
    "ConversionObservation",
    "Listing",
    "Observation",
    "ObservationValue",
    "OpenOrder",
    "Order",
    "OrderDepth",
    "Position",
    "Product",
    "ProsperityEncoder",
    "Symbol",
    "Time",
    "Trade",
    "TradingState",
    "UserId",
]


class Listing:
    def __init__(self, symbol: Symbol, product: Product, denomination: int):
        self.symbol = symbol
        self.product = product
        self.denomination = denomination


class ConversionObservation:
    def __init__(
        self,
        bidPrice: float,
        askPrice: float,
        transportFees: float,
        exportTariff: float,
        importTariff: float,
        sugarPrice: float,
        sunlightIndex: float,
    ):
        self.bidPrice = bidPrice
        self.askPrice = askPrice
        self.transportFees = transportFees
        self.exportTariff = exportTariff
        self.importTariff = importTariff
        self.sugarPrice = sugarPrice
        self.sunlightIndex = sunlightIndex


class Observation:
    def __init__(
        self,
        plainValueObservations: dict[Product, ObservationValue],
        conversionObservations: dict[Product, ConversionObservation],
    ):
        self.plainValueObservations = plainValueObservations
        self.conversionObservations = conversionObservations

    def __str__(self) -> str:
        return json.dumps(self, cls=ProsperityEncoder)


class Order:
    def __init__(self, symbol: Symbol, price: int, quantity: int, ioc: bool = False):
        self.symbol = symbol
        self.price = price
        self.quantity = quantity
        # Extension: in resting mode, cancel what doesn't fill at once instead of resting it.
        self.ioc = ioc

    def __repr__(self) -> str:
        return f"({self.symbol}, {self.price}, {self.quantity})"


class OpenOrder:
    """Extension: one of your orders resting on the book, with what's left to fill (signed)."""

    def __init__(self, id: int, symbol: Symbol, price: int, quantity: int, timestamp: Time):
        self.id = id
        self.symbol = symbol
        self.price = price
        self.quantity = quantity
        self.timestamp = timestamp

    def __repr__(self) -> str:
        return f"(#{self.id} {self.symbol}, {self.price}, {self.quantity})"


class Cancel:
    """Extension: return it in the orders list to cancel the resting order with this id."""

    def __init__(self, order_id: int):
        self.order_id = order_id

    def __repr__(self) -> str:
        return f"(cancel #{self.order_id})"


class OrderDepth:
    """buy_orders maps price -> positive volume; sell_orders maps price -> negative volume."""

    def __init__(self):
        self.buy_orders: dict[int, int] = {}
        self.sell_orders: dict[int, int] = {}


class Trade:
    def __init__(
        self,
        symbol: Symbol,
        price: int,
        quantity: int,
        buyer: UserId | None = None,
        seller: UserId | None = None,
        timestamp: int = 0,
    ):
        self.symbol = symbol
        self.price = price
        self.quantity = quantity
        self.buyer = buyer
        self.seller = seller
        self.timestamp = timestamp

    def __repr__(self) -> str:
        return (
            f"({self.symbol}, {self.buyer} << {self.seller}, {self.price}, {self.quantity}, {self.timestamp})"
        )


class TradingState:
    def __init__(
        self,
        traderData: str,
        timestamp: Time,
        listings: dict[Symbol, Listing],
        order_depths: dict[Symbol, OrderDepth],
        own_trades: dict[Symbol, list[Trade]],
        market_trades: dict[Symbol, list[Trade]],
        position: dict[Product, Position],
        observations: Observation,
        open_orders: dict[Symbol, list[OpenOrder]] | None = None,
    ):
        self.traderData = traderData
        self.timestamp = timestamp
        self.listings = listings
        self.order_depths = order_depths
        self.own_trades = own_trades
        self.market_trades = market_trades
        self.position = position
        self.observations = observations
        # Extension: your resting orders by symbol. Always empty unless orders rest.
        self.open_orders = open_orders or {}

    def toJSON(self) -> str:
        return json.dumps(self, default=lambda o: o.__dict__, sort_keys=True)


class ProsperityEncoder(JSONEncoder):
    def default(self, o):
        return o.__dict__
