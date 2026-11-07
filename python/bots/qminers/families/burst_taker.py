"""Family 13 (7 Nov, round 1): a burst taker that crosses the position limit on purpose. The penalty is flat (10,000 a
second above |100| whatever the size; orders are rejected only past 1,000), so after an aggressive order of at least
TRIGGER lots it sends an IOC of BURST lots the same way, then closes the whole position with an IOC HOLD_MS later.
A test of whether a big move after a big sweep pays the spread twice plus the penalty for the milliseconds over 100.
One position at a time; nothing else. ASCII, one BaseStrategy subclass, the static analysis's constraints.
"""

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


TRIGGER = 800  # lots of one aggressive order (summed over its prints) that start a burst
BURST = 800  # lots of the burst's IOC (|position| + BURST stays within the 1,000 the exchange accepts)
HOLD_MS = 200  # ms after the burst's fill that the position is closed
CROSS = 0  # ticks through the touch for both IOCs (more fills, a worse price)
COOLDOWN_MS = 0  # no new burst this long after a close


class BurstTakerStrategy(BaseStrategy):
    """After a big sweep, take a big position its way with an IOC; close it with an IOC HOLD_MS later."""

    def __init__(self) -> None:
        super().__init__()
        self._position: int = 0
        self._pending: dict[str, int] = {}  # id -> signed lots still possible to fill
        self._close_at: int = 0  # time to close the position (0: nothing open)
        self._cool_until: int = 0

    def on_order_book_change(self, snapshot: OrderBookSnapshot, trades: list[Trade]) -> None:
        now = snapshot.timestamp_us
        best_bid = 0
        for order in snapshot.bids:
            if order.owner == 'market':
                best_bid = order.price
                break
        best_ask = 0
        for order in snapshot.asks:
            if order.owner == 'market':
                best_ask = order.price
                break
        if not best_bid or not best_ask:
            return
        if self._pending:
            return
        if self._position != 0:
            if now >= self._close_at:
                if self._position > 0:
                    self._send(Side.SELL, best_bid - CROSS, self._position)
                else:
                    self._send(Side.BUY, best_ask + CROSS, -self._position)
                self._cool_until = now + COOLDOWN_MS * 1000
            return
        if now < self._cool_until:
            return
        swept: dict = {}
        for trade in trades:
            if trade.taker_owner == 'market':
                key = (trade.taker_order_id, trade.book_side)
                swept[key] = swept.get(key, 0) + trade.quantity
        for (taker, book_side), lots in swept.items():
            if lots >= TRIGGER:
                if book_side == 'ask':  # a buyer swept the asks: the price runs up
                    self._send(Side.BUY, best_ask + CROSS, BURST)
                else:
                    self._send(Side.SELL, best_bid - CROSS, BURST)
                self._close_at = now + 5000 + HOLD_MS * 1000
                return

    def _send(self, side: Side, price: int, quantity: int) -> None:
        if quantity <= 0 or price <= 0:
            return
        order_id = self.send_order(OrderRequest(side=side, price=price, quantity=quantity, order_type=OrderType.IOC))
        self._pending[order_id] = quantity if side == Side.BUY else -quantity

    def on_private_order_update(self, event: PrivateOrderEvent) -> None:
        sign = self._pending.get(event.order_id)
        if sign is None:
            return
        if event.status == OrderStatus.PARTIALLY_FILLED or event.status == OrderStatus.FILLED:
            self._position += event.filled_quantity if sign > 0 else -event.filled_quantity
            if event.status == OrderStatus.FILLED:
                self._pending.pop(event.order_id, None)
        elif event.status == OrderStatus.CANCELED or event.status == OrderStatus.REJECTED:
            self._pending.pop(event.order_id, None)
