"""Round 1 candidate R1-F3 (7 Nov, 13:15): F3 (r0_F3_full_room.py) with SESSION_S 1e9, so it never winds down whatever
the private tape's length: on round1.csv (4.4M rows, 12,000 s, a 1-tick spread 93% of the time) +425,553, the last 25%
+110,540, no penalty (with SESSION_S 12000: +424,617). Imbalance and depletion filters only cut volume there.
Playground candidate F3 (7 Nov): the ladder maker (families/ladder_maker.py) at its best cell on the playground's
second sample (sample_v2.csv, 5,750 s): one level, the touch only, and every lot of room the limit gives quoted there
(SIZE_TOUCH 200 = LIMIT + |position|, topped up behind our order once TOPUP lots of room are free), no skew beyond the
limit itself: +263,604 for the 5,750 s, the last 25% +62,039 (F2: +212,831 / +48,200), no penalty. SESSION_S 5750: set
it from the round's data. The family's notes follow.

Family 6 (7 Nov): ladder market maker. Rest orders on LEVELS price levels a side (the market's touch and the next
LEVELS-1 behind it), SIZE_TOUCH lots at the touch and SIZE_DEEP behind. An order stays where it is when the touch moves
away from it (its queue place is worth something when the price comes back), until it is more than KEEP_DEPTH-1 ticks
behind the touch; an order left alone in front of the market's touch is cancelled when CANCEL_ALONE is 1. A level gets
an order only where we have none. The limit counts every order that can still fill, each side separately (buys at most
LIMIT - position, sells at most LIMIT + position); with REBALANCE 1 the deepest order of a side is cancelled to make
room at an empty touch. Inventory: beyond SKEW lots the side that adds to the position is not quoted (SKEW_CANCEL 1:
its orders are cancelled, 0: they stay but no new ones are posted); beyond UNWIND lots an IOC at the touch sells (or
buys) back down to UNWIND_TO. In the last WIND_DOWN_S seconds only the reducing side is quoted.
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


LEVELS = 1  # price levels quoted a side, the touch first
KEEP_DEPTH = 1  # an order more than KEEP_DEPTH-1 ticks behind the touch is cancelled
SIZE_TOUCH = 200  # lots at the touch: 200 is all the room the limit gives (LIMIT + |position|)
SIZE_DEEP = 50  # lots on each level behind it
LIMIT = 100  # every order that can still fill, counted against the 100 the penalty starts at
SKEW = 100  # beyond this many lots, stop quoting the side that adds to the position (100: the limit does it)
SKEW_CANCEL = 1  # 1: cancel that side's orders beyond SKEW; 0: keep them, post none
CANCEL_ALONE = 1  # 1: cancel an order priced in front of the market's touch
REBALANCE = 0  # 1: cancel the side's deepest order to make room at an empty touch
IMB = 0.0  # quote a side only while the market's lots at its touch are at least IMB times the other touch's (0: off)
MIN_QUEUE = 0  # quote a side only while the market has at least this many lots at its touch
INSIDE_POS = 1000  # beyond this |position|, the reducing side quotes one tick inside the touch (1000: never)
INSIDE_SPREAD = 2  # ... when the spread is at least this many ticks
TOPUP = 10  # with TOPUP lots or more of room left, add another order behind ours at the touch (0: one order a level)
UNWIND = 1000  # beyond this |position| an IOC at the touch trades back to UNWIND_TO (1000: never)
UNWIND_TO = 50
WIND_DOWN_S = 60  # in the last this many seconds, quote only the side that reduces the position
SESSION_S = 1_000_000_000  # the session's length in seconds (set it from the round's data)


class LadderMakerStrategy(BaseStrategy):
    """Rest a ladder of orders on each side; keep queue places; a limit that counts every order able to fill."""

    def __init__(self) -> None:
        super().__init__()
        self._position: int = 0
        self._orders: dict[str, list] = {}  # id -> [side, price, quantity left, cancelling, is_ioc]
        self._start_us: None | int = None
        self._ioc_pending: bool = False

    def on_order_book_change(self, snapshot: OrderBookSnapshot, trades: list[Trade]) -> None:
        """Keep the ladder on each side."""
        if self._start_us is None:
            self._start_us = snapshot.timestamp_us
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
            return
        bid_ok = bid_lots >= MIN_QUEUE and bid_lots >= IMB * ask_lots
        ask_ok = ask_lots >= MIN_QUEUE and ask_lots >= IMB * bid_lots

        elapsed_s = (snapshot.timestamp_us - self._start_us) / 1_000_000
        winding_down = elapsed_s > SESSION_S - WIND_DOWN_S
        position = self._position
        if not self._ioc_pending and position > UNWIND:
            self._send(Side.SELL, best_bid, position - UNWIND_TO, True)
        elif not self._ioc_pending and position < -UNWIND:
            self._send(Side.BUY, best_ask, -position - UNWIND_TO, True)
        want_bid = position < SKEW and not (winding_down and position >= 0) and bid_ok
        want_ask = position > -SKEW and not (winding_down and position <= 0) and ask_ok
        cancel_bid = (winding_down and position >= 0) or (SKEW_CANCEL and position >= SKEW) or not bid_ok
        cancel_ask = (winding_down and position <= 0) or (SKEW_CANCEL and position <= -SKEW) or not ask_ok
        spread = best_ask - best_bid
        bid_anchor = best_bid + 1 if position <= -INSIDE_POS and spread >= INSIDE_SPREAD else best_bid
        ask_anchor = best_ask - 1 if position >= INSIDE_POS and spread >= INSIDE_SPREAD else best_ask
        self._ladder(Side.BUY, bid_anchor, want_bid, cancel_bid)
        self._ladder(Side.SELL, ask_anchor, want_ask, cancel_ask)

    def _ladder(self, side: Side, best: int, want: bool, cancel_all: bool) -> None:
        """Cancel this side's orders outside the ladder; post an order on each empty level the limit has room for."""
        sign = 1 if side == Side.BUY else -1
        have = {}  # ticks behind the touch -> our lots there
        exposure = 0
        deepest_id = None
        deepest_dist = -1
        for order_id, order in self._orders.items():
            if order[0] != side:
                continue
            exposure += order[2]
            if order[3] or order[4]:
                continue
            dist = (best - order[1]) * sign  # ticks behind the touch
            if cancel_all or dist >= KEEP_DEPTH or (dist < 0 and CANCEL_ALONE):
                self.cancel_order(order_id)
                order[3] = True
                continue
            have[dist] = have.get(dist, 0) + order[2]
            if dist > deepest_dist:
                deepest_dist = dist
                deepest_id = order_id
        if not want:
            return
        if side == Side.BUY:
            room = LIMIT - self._position - exposure
        else:
            room = LIMIT + self._position - exposure
        if REBALANCE and 0 not in have and room < SIZE_TOUCH and deepest_id is not None and deepest_dist > 0:
            self.cancel_order(deepest_id)
            self._orders[deepest_id][3] = True
        for level in range(LEVELS):
            size = SIZE_TOUCH if level == 0 else SIZE_DEEP
            if level in have:
                if not TOPUP or level > 0 or size - have[level] < TOPUP or room < TOPUP:
                    continue
                size -= have[level]
            quantity = min(size, room)
            if quantity <= 0:
                return
            self._send(side, best - sign * level, quantity, False)
            room -= quantity

    def _send(self, side: Side, price: int, quantity: int, ioc: bool) -> None:
        """Send an order and remember it."""
        order_type = OrderType.IOC if ioc else OrderType.LIMIT
        order_id = self.send_order(OrderRequest(side=side, price=price, quantity=quantity, order_type=order_type))
        self._orders[order_id] = [side, price, quantity, False, ioc]
        if ioc:
            self._ioc_pending = True

    def on_private_order_update(self, event: PrivateOrderEvent) -> None:
        """Count fills into the position; forget orders that are done."""
        order = self._orders.get(event.order_id)
        if order is None:
            return
        done = False
        if event.status == OrderStatus.PARTIALLY_FILLED or event.status == OrderStatus.FILLED:
            if order[0] == Side.BUY:
                self._position += event.filled_quantity
            else:
                self._position -= event.filled_quantity
            order[2] = event.remaining_quantity
            done = event.status == OrderStatus.FILLED or event.remaining_quantity == 0
        elif event.status == OrderStatus.CANCELED or event.status == OrderStatus.REJECTED:
            done = True
        if done:
            self._orders.pop(event.order_id, None)
            if order[4]:
                self._ioc_pending = False
