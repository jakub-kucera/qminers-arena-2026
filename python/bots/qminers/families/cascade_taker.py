"""Family 13 (7 Nov, round 2): the cascade taker. Round 2's public tape is a random walk four times as volatile as round 1's
(1-s moves of 3.8 ticks) whose touch clears cascade: after a touch clears and the level behind it (the new touch) is thin, the
mid is 1.4-2.3 ticks further in the clear's direction one second later and has moved 2+ ticks in 45-53% of cases
(experiments.tape.spread_episodes on data/arena/round2/round2_public.csv; cancel-driven clears with under 100 lots behind:
+2.3 ticks, 53%). The aggressors are iid (no flow to follow), so the signal is the book's own cascade, not the trades.

The bot holds nothing by default. When the market's best ask rises (the old ask touch cleared, by a sweep or by cancels) and
the new ask touch holds at most THIN market lots (and, with CANCEL_ONLY 1, the event carried no trade), it sends a BUY IOC at
the new ask for min(SIZE, the new touch's lots, the room) and then rests a SELL LIMIT at the fill price + EXIT ticks for the
lots bought; if that exit has not filled within HOLD_S seconds, or the mid has moved STOP ticks against the position, the
position is flattened with an IOC at the touch (and the resting exit cancelled). Symmetric for a falling bid. At most one open
position per direction at a time (OPEN_MAX lots in all, within EXPOSURE), nothing new while a flatten is in flight, and the
limit counts every order that can still fill. No wind-down: the end position is marked against the book.

Knobs: THIN (lots at the new touch at most this), CANCEL_ONLY (1: only clears without a trade in the event), SIZE (lots a take),
EXPOSURE (|position| plus every live order on its side never beyond it), EXIT (ticks beyond the entry for the resting exit),
HOLD_S (seconds before a time stop), STOP (ticks against the entry before a stop), MIN_GAP_MS (no new take within this of the
last on that side), SPREAD_MAX (no take when the spread after the clear is wider than this many ticks).
"""

from __future__ import annotations

from simulator.models import OrderBookSnapshot, OrderRequest, OrderStatus, OrderType, PrivateOrderEvent, Side, Trade
from simulator.strategy import BaseStrategy

THIN = 100  # take only when the new touch holds at most this many market lots
CANCEL_ONLY = 0  # 1: only clears with no trade in the event (the strongest continuation); 0: any clear
SIZE = 30  # lots per take
EXPOSURE = 60  # |position| plus every live order on its side never beyond this
EXIT = 2  # the resting exit this many ticks beyond the entry price
HOLD_S = 5.0  # time stop: flatten at the touch if the exit has not filled by then
STOP = 4  # stop: flatten if the mid has moved this many ticks against the entry
MIN_GAP_MS = 500  # no new take on a side within this of the last one there
SPREAD_MAX = 3  # no take when the spread after the clear exceeds this many ticks
SESSION_S = 1_000_000_000  # unused: no wind-down


class CascadeTaker(BaseStrategy):
    """Take the thin new touch right after a clear; exit a tick or two on, or flatten on a time or price stop."""

    def __init__(self) -> None:
        super().__init__()
        self._position: int = 0
        self._orders: dict[str, list] = {}  # id -> [side, price, lots left, cancelling, ioc, kind] kind: 'take' | 'exit' | 'flat'
        self._prev: None | tuple = None  # previous snapshot's (best bid, best ask)
        self._last_take_us: dict = {'B': -10**12, 'A': -10**12}
        self._entries: list = []  # open entries: [sign, price, lots, time_us, exit order id or None]
        self._flat_pending: bool = False
        self._now_us: int = 0

    def on_order_book_change(self, snapshot: OrderBookSnapshot, trades: list[Trade]) -> None:
        self._now_us = snapshot.timestamp_us
        best_bid = None
        bid_lots = 0
        for order in snapshot.bids:
            if order.owner == 'market':
                if best_bid is None:
                    best_bid = order.price
                elif order.price != best_bid:
                    break
                bid_lots += order.quantity
        best_ask = None
        ask_lots = 0
        for order in snapshot.asks:
            if order.owner == 'market':
                if best_ask is None:
                    best_ask = order.price
                elif order.price != best_ask:
                    break
                ask_lots += order.quantity
        if best_bid is None or best_ask is None:
            self._prev = None
            return
        mid = (best_bid + best_ask) / 2
        traded = any(t.taker_owner == 'market' for t in trades)
        # stops on open entries
        self._stops(best_bid, best_ask, mid)
        if self._prev is not None and not self._flat_pending:
            prev_bid, prev_ask = self._prev
            spread = best_ask - best_bid
            if best_ask > prev_ask and spread <= SPREAD_MAX and ask_lots <= THIN and (not CANCEL_ONLY or not traded):
                self._take(Side.BUY, best_ask, ask_lots)
            if best_bid < prev_bid and spread <= SPREAD_MAX and bid_lots <= THIN and (not CANCEL_ONLY or not traded):
                self._take(Side.SELL, best_bid, bid_lots)
        self._prev = (best_bid, best_ask)

    def _exposure(self, side: Side) -> int:
        """|position| on that side plus every live order of that side."""
        sign = 1 if side == Side.BUY else -1
        live = sum(o[2] for o in self._orders.values() if o[0] == side)
        return sign * self._position + live

    def _take(self, side: Side, price: int, touch_lots: int) -> None:
        key = 'B' if side == Side.BUY else 'A'
        if self._now_us - self._last_take_us[key] < MIN_GAP_MS * 1000:
            return
        sign = 1 if side == Side.BUY else -1
        # never add to a position on the other side: a take only opens or adds in its own direction
        if sign * self._position < 0:
            return
        room = EXPOSURE - self._exposure(side)
        lots = min(SIZE, touch_lots, room)
        if lots <= 0:
            return
        self._last_take_us[key] = self._now_us
        self._send(side, price, lots, True, 'take')

    def _stops(self, best_bid: int, best_ask: int, mid: float) -> None:
        if self._flat_pending:
            return
        if not self._entries:
            if self._position != 0 and not any(o[5] == 'exit' for o in self._orders.values()):
                # a flatten that did not fill in full left a position with no entry: flatten it at the touch
                if self._position > 0:
                    self._send(Side.SELL, best_bid, self._position, True, 'flat')
                else:
                    self._send(Side.BUY, best_ask, -self._position, True, 'flat')
                self._flat_pending = True
            return
        for entry in list(self._entries):
            sign, price, lots, t_us, exit_id = entry
            age = (self._now_us - t_us) / 1_000_000
            against = sign * (price - mid)
            if age >= HOLD_S or against >= STOP:
                self._flatten(entry, best_bid, best_ask)
                return  # one flatten at a time

    def _flatten(self, entry: list, best_bid: int, best_ask: int) -> None:
        sign, price, lots, t_us, exit_id = entry
        if exit_id is not None and exit_id in self._orders and not self._orders[exit_id][3]:
            self.cancel_order(exit_id)
            self._orders[exit_id][3] = True
        self._entries.remove(entry)
        if lots <= 0:
            return
        if sign > 0:
            self._send(Side.SELL, best_bid, lots, True, 'flat')
        else:
            self._send(Side.BUY, best_ask, lots, True, 'flat')
        self._flat_pending = True

    def _send(self, side: Side, price: int, lots: int, ioc: bool, kind: str) -> str:
        order_type = OrderType.IOC if ioc else OrderType.LIMIT
        order_id = self.send_order(OrderRequest(side=side, price=price, quantity=lots, order_type=order_type))
        self._orders[order_id] = [side, price, lots, False, ioc, kind]
        return order_id

    def on_private_order_update(self, event: PrivateOrderEvent) -> None:
        order = self._orders.get(event.order_id)
        if order is None:
            return
        done = False
        if event.status == OrderStatus.PARTIALLY_FILLED or event.status == OrderStatus.FILLED:
            filled = event.filled_quantity
            if order[0] == Side.BUY:
                self._position += filled
            else:
                self._position -= filled
            order[2] = event.remaining_quantity
            done = event.status == OrderStatus.FILLED or event.remaining_quantity == 0
            if order[5] == 'take' and event.fill_price is not None:
                sign = 1 if order[0] == Side.BUY else -1
                exit_price = event.fill_price + sign * EXIT
                exit_side = Side.SELL if sign > 0 else Side.BUY
                exit_id = self._send(exit_side, exit_price, filled, False, 'exit')
                self._entries.append([sign, event.fill_price, filled, event.timestamp_us, exit_id])
            elif order[5] == 'exit':
                for entry in self._entries:
                    if entry[4] == event.order_id:
                        entry[2] -= filled
                        if entry[2] <= 0:
                            self._entries.remove(entry)
                        break
        elif event.status == OrderStatus.CANCELED or event.status == OrderStatus.REJECTED:
            done = True
        if done:
            self._orders.pop(event.order_id, None)
            if order[5] == 'flat':
                self._flat_pending = False
            if order[5] == 'exit':
                for entry in self._entries:
                    if entry[4] == event.order_id:
                        entry[4] = None
                        break
