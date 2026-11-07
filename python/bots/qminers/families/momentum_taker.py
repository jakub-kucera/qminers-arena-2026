"""Family 1 (7 Nov): momentum taker, a generalised version of the starter's trend follower.

The market's net aggressive flow (lots bought minus lots sold by the tape's takers, over the last WINDOW_MS, or only
the trades since the previous call when WINDOW_MS is 0) of at least MIN_FLOW lots opens a trade in its direction: an
IOC of SIZE lots at the touch, CROSS ticks through it. While the flow keeps pointing the same way within ENTRY_MS of
the first entry, it adds SIZE more on each call, up to MAX_POS. The position is closed by an IOC at the touch after
HOLD_MS, on a reversal (the flow pointing the other way, if REVERSE), on STOP_TICKS of the mid against it, or near
the end of the session; with TP_TICKS, every entry fill also rests a passive exit TP_TICKS beyond its fill price,
filled when the book walks there. One taker order in flight at a time. The limit counts every order that can still
fill (sent, resting, being cancelled), so |position| never exceeds MAX_POS.
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


WINDOW_MS = 0  # flow window; 0: only the trades since the previous call
MIN_FLOW = 1  # lots of net aggressive flow that open (or add to) a trade
SIZE = 10  # lots per entry order
MAX_POS = 50  # |position| cap, every order that can still fill counted
ENTRY_MS = 0  # after the first entry, keep adding while the flow agrees for this long
HOLD_MS = 4000  # close the trade this long after the first entry
TP_TICKS = 0  # >0: rest a passive exit this many ticks beyond each entry fill
STOP_TICKS = 0  # >0: close when the mid has gone this many ticks against the entry
REVERSE = 1  # 1: close on flow the other way
CROSS = 0  # ticks through the touch for the IOC price
WIND_DOWN_S = 30  # no new trades in the last this many seconds, and close what is open
SESSION_S = 3600  # the session's length in seconds (set it from the round's data)


class MomentumTakerStrategy(BaseStrategy):
    """Take in the direction of the tape's aggressive flow; close after a hold, a reversal, a stop or a target."""

    def __init__(self) -> None:
        super().__init__()
        self._pos: int = 0
        self._orders: dict[str, list] = {}  # id -> [sign, price, left, cancelling, ioc]
        self._start_us: None | int = None
        self._flow: deque = deque()  # (timestamp_us, signed lots) within the window
        self._flow_sum: int = 0
        self._dir: int = 0  # the open trade's direction, 0 when flat
        self._entry_us: int = 0
        self._entry_mid: float = 0.0
        self._exiting: bool = False
        self._taker_id: None | str = None
        self._pending_tp: list = []  # (sign, price, quantity) to rest at the next call

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

    def _cancel_resting(self) -> None:
        for order_id, order in self._orders.items():
            if not order[4] and not order[3]:
                self.cancel_order(order_id)
                order[3] = True

    def on_order_book_change(self, snapshot: OrderBookSnapshot, trades: list[Trade]) -> None:
        now = snapshot.timestamp_us
        if self._start_us is None:
            self._start_us = now
        net = 0
        for trade in trades:
            if trade.taker_owner == 'market':
                net += trade.quantity if trade.book_side == 'ask' else -trade.quantity
        if WINDOW_MS > 0:
            if net:
                self._flow.append((now, net))
                self._flow_sum += net
            horizon = now - WINDOW_MS * 1000
            while self._flow and self._flow[0][0] < horizon:
                self._flow_sum -= self._flow.popleft()[1]
            flow = self._flow_sum
        else:
            flow = net
        signal = 1 if flow >= MIN_FLOW else (-1 if flow <= -MIN_FLOW else 0)

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
        mid = (best_bid + best_ask) / 2

        while self._pending_tp:
            sign, price, quantity = self._pending_tp.pop()
            if not self._exiting and self._dir != 0:
                self._send(sign, price, quantity, False)

        if self._taker_id is not None:
            return  # one taker order in flight

        late = (now - self._start_us) / 1_000_000 > SESSION_S - WIND_DOWN_S
        if self._dir != 0 and not self._exiting:
            held = now - self._entry_us >= HOLD_MS * 1000
            reversed_flow = REVERSE and signal == -self._dir
            stopped = STOP_TICKS > 0 and (mid - self._entry_mid) * self._dir <= -STOP_TICKS
            if held or reversed_flow or stopped or late:
                self._exiting = True
                self._cancel_resting()
        if self._exiting or (late and self._pos != 0):
            if self._pos == 0:
                if not any(not order[4] for order in self._orders.values()):
                    self._exiting = False
                    self._dir = 0
                return
            sign = -1 if self._pos > 0 else 1
            reducing = 0
            for order in self._orders.values():
                if order[0] == sign:
                    reducing += order[2]
            quantity = abs(self._pos) - reducing
            if quantity > 0:
                price = best_bid - CROSS if sign < 0 else best_ask + CROSS
                self._taker_id = self._send(sign, price, quantity, True)
            return
        if self._dir != 0 and self._pos == 0 and not any(self._orders):
            self._dir = 0  # entries never filled
        if late or signal == 0:
            return
        if self._dir == 0:
            self._dir = signal
            self._entry_us = now
            self._entry_mid = mid
        elif signal != self._dir or now - self._entry_us > ENTRY_MS * 1000:
            return
        price = best_ask + CROSS if signal > 0 else best_bid - CROSS
        self._taker_id = self._send(signal, price, SIZE, True)

    def on_private_order_update(self, event: PrivateOrderEvent) -> None:
        order = self._orders.get(event.order_id)
        if order is None:
            return
        status = event.status
        if status == OrderStatus.PARTIALLY_FILLED or status == OrderStatus.FILLED:
            filled = event.filled_quantity
            self._pos += filled if order[0] > 0 else -filled
            order[2] = event.remaining_quantity
            if TP_TICKS > 0 and order[4] and order[0] == self._dir and not self._exiting:
                self._pending_tp.append((-order[0], event.fill_price + order[0] * TP_TICKS, filled))
            if status == OrderStatus.FILLED or event.remaining_quantity == 0:
                self._orders.pop(event.order_id, None)
                if event.order_id == self._taker_id:
                    self._taker_id = None
        elif status == OrderStatus.CANCELED or status == OrderStatus.REJECTED:
            self._orders.pop(event.order_id, None)
            if event.order_id == self._taker_id:
                self._taker_id = None
