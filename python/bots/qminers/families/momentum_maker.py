"""Family 2 (7 Nov): momentum maker. The market's net aggressive flow over the last WINDOW_MS (at least MIN_FLOW lots)
sets a direction for SIGNAL_MS; while it holds, one passive order of QUOTE lots rests on that side (a bid after net
buying), IMPROVE ticks inside the touch where the spread allows (0 joins it), and the other side's quotes are pulled.
With no signal, a position is worked out passively on the reducing side at the touch; after FLAT_MS without a signal
it is closed by an IOC at the touch. The limit counts every order that can still fill, so |position| never exceeds
MAX_POS. A quote is re-posted only when its wanted price changes (queue place). In the last WIND_DOWN_S seconds no
new position is added, and the last FLAT_S close what is left with an IOC.
"""

from __future__ import annotations

from collections import deque

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


WINDOW_MS = 1000  # flow window
MIN_FLOW = 1  # lots of net aggressive flow that set the direction
SIGNAL_MS = 3000  # how long a direction lasts after its last confirming flow
QUOTE = 10  # lots of the resting order
IMPROVE = 0  # ticks inside the touch (where the spread allows)
MAX_POS = 50  # |position| cap, every order that can still fill counted
FLAT_MS = 5000  # with no signal for this long, close the position with an IOC (0: never)
WIND_DOWN_S = 60  # add no new position in the last this many seconds
FLAT_S = 10  # close the rest with an IOC in the last this many seconds
SESSION_S = 3600  # the session's length in seconds (set it from the round's data)


class MomentumMakerStrategy(BaseStrategy):
    """Rest a passive order on the side of the recent aggressive flow; work the position out when it fades."""

    def __init__(self) -> None:
        super().__init__()
        self._pos: int = 0
        self._orders: dict[str, list] = {}  # id -> [sign, price, left, cancelling, ioc]
        self._start_us: None | int = None
        self._flow: deque = deque()
        self._flow_sum: int = 0
        self._dir: int = 0
        self._dir_until: int = 0
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

    def _keep_one(self, sign: int, price: int, quantity: int) -> None:
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
        if price and not have and quantity > 0:
            self._send(sign, price, quantity, False)

    def on_order_book_change(self, snapshot: OrderBookSnapshot, trades: list[Trade]) -> None:
        now = snapshot.timestamp_us
        if self._start_us is None:
            self._start_us = now
        net = 0
        for trade in trades:
            if trade.taker_owner == 'market':
                net += trade.quantity if trade.book_side == 'ask' else -trade.quantity
        if net:
            self._flow.append((now, net))
            self._flow_sum += net
        horizon = now - WINDOW_MS * 1000
        while self._flow and self._flow[0][0] < horizon:
            self._flow_sum -= self._flow.popleft()[1]
        if net and abs(self._flow_sum) >= MIN_FLOW:
            self._dir = 1 if self._flow_sum > 0 else -1
            self._dir_until = now + SIGNAL_MS * 1000
        signal = self._dir if now < self._dir_until else 0

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

        elapsed_s = (now - self._start_us) / 1_000_000
        quiet_us = now - self._dir_until
        if elapsed_s > SESSION_S - FLAT_S or (signal == 0 and FLAT_MS > 0 and quiet_us > FLAT_MS * 1000):
            if self._pos != 0:
                self._keep_one(1, 0, 0)
                self._keep_one(-1, 0, 0)
                if self._taker_id is None:
                    sign = -1 if self._pos > 0 else 1
                    self._taker_id = self._send(sign, best_bid if sign < 0 else best_ask, abs(self._pos), True)
                return
        late = elapsed_s > SESSION_S - WIND_DOWN_S

        bid_price = min(best_bid + IMPROVE, best_ask - 1)
        ask_price = max(best_ask - IMPROVE, best_bid + 1)
        if signal != 0 and not late:
            if signal > 0:
                self._keep_one(1, bid_price, QUOTE)
                self._keep_one(-1, 0, 0)
            else:
                self._keep_one(-1, ask_price, QUOTE)
                self._keep_one(1, 0, 0)
            return
        # no signal: work a position out on the reducing side, at the touch
        if self._pos > 0:
            self._keep_one(-1, best_ask, self._pos)
            self._keep_one(1, 0, 0)
        elif self._pos < 0:
            self._keep_one(1, best_bid, -self._pos)
            self._keep_one(-1, 0, 0)
        else:
            self._keep_one(1, 0, 0)
            self._keep_one(-1, 0, 0)

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
