"""Family 3 (7 Nov): protected market maker. Two-sided quotes of QUOTE lots, OFFSET ticks outside the touch (0 joins
it, -1 improves it where the spread allows, never crossing), pulled for PULL_MS after a market trade or a move of the
touch (PULL_ON_MOVE): the side the move runs at (an aggressive buy or the touch stepping up threatens our ask), or both
sides when PULL_SIDE is 0. A quote is re-posted only when its wanted price changes, so it keeps its queue place.
Beyond SKEW lots the side that adds to the position is not quoted; the limit counts every order that can still fill,
so |position| never exceeds MAX_POS. In the last WIND_DOWN_S seconds only the reducing side is quoted, and in the last
FLAT_S an IOC at the touch closes what is left.
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


QUOTE = 10  # lots a side
MAX_POS = 50  # |position| cap, every order that can still fill counted
SKEW = 20  # beyond this many lots, stop quoting the side that adds to the position
OFFSET = -1  # ticks outside the touch (negative: inside it, where the spread allows)
PULL_MS = 6000  # how long a threatened side stays pulled
PULL_ON_MOVE = 1  # 1: a move of the touch also pulls (not only a market trade)
PULL_SIDE = 0  # 1: pull only the side the move runs at; 0: pull both sides
WIND_DOWN_S = 60  # quote only the reducing side in the last this many seconds
FLAT_S = 10  # close the rest with an IOC in the last this many seconds
SESSION_S = 3600  # the session's length in seconds (set it from the round's data)


class ProtectedMakerStrategy(BaseStrategy):
    """Quote both sides; pull the threatened side after trades and touch moves; keep queue places."""

    def __init__(self) -> None:
        super().__init__()
        self._pos: int = 0
        self._orders: dict[str, list] = {}  # id -> [sign, price, left, cancelling, ioc]
        self._start_us: None | int = None
        self._last_bid: int = 0
        self._last_ask: int = 0
        self._pulled_until: dict[int, int] = {1: 0, -1: 0}  # our bid (1) and our ask (-1)
        self._taker_id: None | str = None

    def _room(self, sign: int) -> int:
        exposure = 0
        for order in self._orders.values():
            if order[0] == sign:
                exposure += order[2]
        return MAX_POS - sign * self._pos - exposure

    def _send(self, sign: int, price: int, quantity: int, ioc: bool) -> None | str:
        quantity = min(quantity, self._room(sign))
        if quantity <= 0 or price <= 0:
            return None
        order_id = self.send_order(
            OrderRequest(
                side=Side.BUY if sign > 0 else Side.SELL,
                price=price,
                quantity=quantity,
                order_type=OrderType.IOC if ioc else OrderType.LIMIT,
            )
        )
        self._orders[order_id] = [sign, price, quantity, False, ioc]
        return order_id

    def _keep_one(self, sign: int, price: int) -> None:
        """Cancel this side's quotes at any other price (price 0: all); post one at `price` if none is there."""
        have = False
        for order_id, order in self._orders.items():
            if order[0] != sign or order[3] or order[4]:
                continue
            if price and order[1] == price and not have:
                have = True
            else:
                self.cancel_order(order_id)
                order[3] = True
        if price and not have:
            self._send(sign, price, QUOTE, False)

    def on_order_book_change(self, snapshot: OrderBookSnapshot, trades: list[Trade]) -> None:
        now = snapshot.timestamp_us
        if self._start_us is None:
            self._start_us = now
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

        threat = 0  # +1: the price runs up (our ask at risk), -1: down, 2: both
        for trade in trades:
            if trade.taker_owner == 'market':
                threat = 1 if trade.book_side == 'ask' else -1
        if PULL_ON_MOVE and self._last_bid:
            if best_bid > self._last_bid or best_ask > self._last_ask:
                threat = 1 if threat >= 0 else 2
            if best_bid < self._last_bid or best_ask < self._last_ask:
                threat = -1 if threat <= 0 else 2
        self._last_bid, self._last_ask = best_bid, best_ask
        if threat:
            until = now + PULL_MS * 1000
            if PULL_SIDE == 0 or threat == 2:
                self._pulled_until[1] = until
                self._pulled_until[-1] = until
            else:
                self._pulled_until[-threat] = until

        elapsed_s = (now - self._start_us) / 1_000_000
        if elapsed_s > SESSION_S - FLAT_S:
            self._keep_one(1, 0)
            self._keep_one(-1, 0)
            if self._pos != 0 and self._taker_id is None:
                sign = -1 if self._pos > 0 else 1
                self._taker_id = self._send(sign, best_bid if sign < 0 else best_ask, abs(self._pos), True)
            return
        winding_down = elapsed_s > SESSION_S - WIND_DOWN_S

        bid_price = min(best_bid - OFFSET, best_ask - 1)
        ask_price = max(best_ask + OFFSET, best_bid + 1)
        want_bid = self._pos < SKEW and not (winding_down and self._pos >= 0) and now >= self._pulled_until[1]
        want_ask = self._pos > -SKEW and not (winding_down and self._pos <= 0) and now >= self._pulled_until[-1]
        self._keep_one(1, bid_price if want_bid else 0)
        self._keep_one(-1, ask_price if want_ask else 0)

    def on_private_order_update(self, event: PrivateOrderEvent) -> None:
        order = self._orders.get(event.order_id)
        if order is None:
            return
        status = event.status
        if status == OrderStatus.PARTIALLY_FILLED or status == OrderStatus.FILLED:
            filled = event.filled_quantity
            self._pos += filled if order[0] > 0 else -filled
            order[2] = event.remaining_quantity
            if status == OrderStatus.FILLED or event.remaining_quantity == 0:
                self._orders.pop(event.order_id, None)
                if event.order_id == self._taker_id:
                    self._taker_id = None
        elif status == OrderStatus.CANCELED or status == OrderStatus.REJECTED:
            self._orders.pop(event.order_id, None)
            if event.order_id == self._taker_id:
                self._taker_id = None
