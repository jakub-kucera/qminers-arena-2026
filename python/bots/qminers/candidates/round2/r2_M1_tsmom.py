"""R2-M1 (7 Nov, round 2): time-series momentum. Round 2's price wanders hundreds of ticks and a move over the last
minute or two keeps going (round 2's public tape: after the mid has moved 8+ ticks in 60 s it moves on about +10 ticks
in the next 60 s, in both halves of the tape). The signal is the mid's move over the last LOOKBACK_MS: at ENTER_TICKS
or more one way the target is MAX_POS lots that way; the target stays until the move reaches ENTER_TICKS the other way
(EXIT_FRAC < 0) or falls under EXIT_FRAC x ENTER_TICKS the run's way (EXIT_FRAC >= 0: flat). The position goes to the
target by IOCs at the touch (CROSS ticks through it), one in flight; with PASSIVE_MS > 0 by a resting order at our own
touch first (the bid when buying), re-pegged when the touch moves, and by IOCs once PASSIVE_MS have passed since the
target changed. The limit counts every order that can still fill, so |position| never exceeds MAX_POS. No signal in
the first LOOKBACK_MS. Round 2's public tape: +87,156 (in 51,111 / out 36,045; 75 fills, 6,500 lots); round 1's:
-23,695 (few trades, so the loss on a tape without trends stays small; no self-gate, unlike R2-M2).
"""

from __future__ import annotations

from collections import deque

from simulator.models import OrderBookSnapshot, OrderRequest, OrderStatus, OrderType, PrivateOrderEvent, Side, Trade
from simulator.strategy import BaseStrategy


LOOKBACK_MS = 120000  # the move is the mid now minus the mid this long ago
ENTER_TICKS = 12  # a move of at least this many ticks sets the target that way
EXIT_FRAC = -1.0  # < 0: hold until the opposite signal; >= 0: flat once the move is under this x ENTER_TICKS
MAX_POS = 100  # |position| cap, every order that can still fill counted
CROSS = 0  # ticks through the touch for the IOC price
PASSIVE_MS = 0  # > 0: work each change by a resting order at our touch first, IOCs after this long


class TsMomStrategy(BaseStrategy):
    """Hold MAX_POS lots the way the mid has moved over the last LOOKBACK_MS; flip or flatten on the exit band."""

    def __init__(self) -> None:
        super().__init__()
        self._pos = 0
        self._orders = {}  # id -> [sign, price, left, cancelling]
        self._start_us = None
        self._hist = deque()  # (time, mid)
        self._dir = 0
        self._taker_id = None
        self._passive_id = None
        self._work_sign = 0
        self._work_us = 0  # when the wanted change last took its current sign

    def _room(self, sign: int) -> int:
        exposure = 0
        for order in self._orders.values():
            if order[0] == sign:
                exposure += order[2]
        return MAX_POS - sign * self._pos - exposure

    def _send(self, sign: int, price: int, quantity: int, ioc: bool):
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
        self._orders[order_id] = [sign, price, quantity, False]
        return order_id

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
        mid = (best_bid + best_ask) / 2
        hist = self._hist
        hist.append((now, mid))
        horizon = now - LOOKBACK_MS * 1000
        while len(hist) > 1 and hist[1][0] <= horizon:
            hist.popleft()
        if now - self._start_us >= LOOKBACK_MS * 1000:
            move = mid - hist[0][1]
            if move >= ENTER_TICKS:
                self._dir = 1
            elif move <= -ENTER_TICKS:
                self._dir = -1
            elif EXIT_FRAC >= 0 and self._dir != 0 and move * self._dir < EXIT_FRAC * ENTER_TICKS:
                self._dir = 0

        want = self._dir * MAX_POS - self._pos
        sign = 1 if want > 0 else -1 if want < 0 else 0
        if sign != self._work_sign:
            self._work_sign = sign
            self._work_us = now
        if PASSIVE_MS > 0:
            passive = self._orders.get(self._passive_id) if self._passive_id is not None else None
            if passive is not None:
                timed_out = now - self._work_us >= PASSIVE_MS * 1000
                if passive[0] != sign or passive[1] != (best_bid if passive[0] > 0 else best_ask) or timed_out:
                    if not passive[3]:
                        passive[3] = True
                        self.cancel_order(self._passive_id)
                return  # wait for the cancel (or the fill)
            if sign != 0 and self._taker_id is None and now - self._work_us < PASSIVE_MS * 1000:
                self._passive_id = self._send(sign, best_bid if sign > 0 else best_ask, abs(want), False)
                return
        if self._taker_id is not None or sign == 0:
            return
        if sign > 0:
            self._taker_id = self._send(1, best_ask + CROSS, want, True)
        else:
            self._taker_id = self._send(-1, best_bid - CROSS, -want, True)

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
                self._done(event.order_id)
        elif status == OrderStatus.CANCELED or status == OrderStatus.REJECTED:
            self._done(event.order_id)

    def _done(self, order_id: str) -> None:
        self._orders.pop(order_id, None)
        if order_id == self._taker_id:
            self._taker_id = None
        if order_id == self._passive_id:
            self._passive_id = None
