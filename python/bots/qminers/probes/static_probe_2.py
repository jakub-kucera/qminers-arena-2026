"""Simple trend-following example: one-lot IOC orders in the direction of the trades just seen."""

from __future__ import annotations

from simulator.models import (
    OrderBookSnapshot,
    OrderRequest,
    OrderStatus,
    OrderType,
    PrivateOrderEvent,
    Side,
    Trade,
)
from simulator.strategy import BaseStrategy


class TrendFollowerStrategy(BaseStrategy):
    """Trend follower: after every market event, trade one lot the way the market just traded.

    Net buying since the previous callback lifts the best ask, net selling hits
    the best bid, always with an IOC order of one lot. One order is in flight at
    a time, and the same side is not sent twice in a row; a rejected or
    cancelled order flips the side to try.
    """

    def __init__(self) -> None:
        super().__init__()
        self._order_in_flight: bool = False
        self._current_order_side: None | Side = None

    def on_order_book_change(self, snapshot: OrderBookSnapshot, trades: list[Trade]) -> None:
        """Send a one-lot IOC order in the direction of the net trading since the previous call."""
        if self._order_in_flight:
            return

        # Calculate how much was traded in the market
        side_sign = {'ask': 1, 'bid': -1}
        total_traded = sum(t.quantity * side_sign[t.book_side] for t in trades)

        # Pick order side and price based on direction of trading and book
        if total_traded == 0:
            return
        elif total_traded > 0:
            if not snapshot.asks or self._current_order_side == Side.BUY:
                return
            self._current_order_side, best_price = Side.BUY, snapshot.asks[0].price
        else:
            if not snapshot.bids or self._current_order_side == Side.SELL:
                return
            self._current_order_side, best_price = Side.SELL, snapshot.bids[0].price

        # Send order
        self.send_order(
            OrderRequest(
                side=self._current_order_side,
                price=best_price,
                quantity=1,
                order_type=OrderType.IOC,
            )
        )
        self._order_in_flight = True

    def on_private_order_update(self, event: PrivateOrderEvent) -> None:
        """Free the in-flight slot on a fill; flip the side to try after a reject or cancel."""
        if event.status == OrderStatus.FILLED:
            self._order_in_flight = False
        elif event.status == OrderStatus.REJECTED or event.status == OrderStatus.CANCELED:
            self._current_order_side = Side.BUY if self._current_order_side == Side.SELL else Side.SELL


def group_two(levels: list[list[int]]) -> tuple:
    best = max(levels) if len(levels) else None
    worst = min(levels) if levels else None
    total = sum(abs(int(level[1])) for level in levels)
    seen = set(level[0] for level in levels)
    pairs = dict(zip(range(len(levels)), sorted(seen)))
    flag = any(float(level[1]) > 0 for level in levels)
    return best, worst, round(total / 3, 2), str(pairs), tuple(seen), flag


LIMIT = 100
SETTINGS = {"limit": 50, "fair": "mid", "edge": None, "sizes": [1, 2]}
TABLE: dict = {"ASSET": {"limit": 50}}


class Ledger:
    def __init__(self, bids: list[list[int]], asks: "list[list[int]]", extra: int | None = None, sent: list[tuple] = ()):
        self.bids = bids
        self.asks = asks
        self.taken: list[tuple[int, int]] = []

    def copy(self) -> "Ledger":
        return Ledger([level[:] for level in self.bids], [level[:] for level in self.asks])


def group_three(ledger: "Ledger", memory: dict) -> int:
    trail = memory.setdefault("trail", [])
    trail[:] = trail[-10:]
    counts = {price: size for price, size in ledger.bids}
    prices = {price for price, size in ledger.asks if price is not None and size is not None}
    total = 0
    for price, size in ledger.bids:
        if price in counts and price not in prices and size >= 0:
            total += size
        else:
            break
    merged = {**SETTINGS, **TABLE["ASSET"]}
    if merged.get("edge") is None:
        pass
    return total
