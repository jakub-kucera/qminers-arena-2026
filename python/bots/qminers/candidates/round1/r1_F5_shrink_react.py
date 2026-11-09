"""Round 1 candidate R1-F5 (7 Nov, 13:35): the shrink maker with REACT_CANCEL 1, DEPLETE_LOTS 100, DEPL_FRAC 0.06
(cancel only on a touch that has shrunk below 6% of its peak and 100 lots), F3's sizing, SESSION_S 1e9. Chosen on round1's
first 75% (340,516 against F3's 315,013): full +455,822, the last 25% +115,306 (F3: 425,553 / 110,540), no penalty.
Family 10 (7 Nov, round 1): the room maker with a shrinking-level guard (DEPL_FRAC): F3's round-1 fills from a level left
with 0-50 market lots lost 0.05-0.23 ticks a lot; the plain depletion guard also stopped us joining new (small) levels.
Family 7 (7 Nov): the room maker, candidate F3 (the ladder maker at one level, all the limit's room quoted at the
touch) with knobs whose defaults reproduce F3 exactly (+263,282 on sample_v2.csv): SIZE_NARROW, the lots at the touch
while the spread is one tick (SHRINK_NARROW 1: resting orders are shrunk to it with modify_order, which keeps their
place); DEPLETE_LOTS / DEPLETE_SIZE, the lots kept at a touch whose market queue holds fewer than DEPLETE_LOTS lots (the
level about to be cleared); BACK_POS, beyond which the side that adds to the position quotes one tick behind the touch;
FLAT_S, an IOC flattening the position at the touch FLAT_S seconds before the end. F3's notes follow.

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
SIZE_NARROW = 200  # lots at the touch while the spread is one tick (200: as SIZE_TOUCH)
SHRINK_NARROW = 0  # 1: shrink resting touch orders to SIZE_NARROW (modify keeps the place) while the spread is one tick
DEPLETE_LOTS = 100  # a touch whose market queue holds fewer lots than this is about to clear (0: off)
DEPLETE_SIZE = 0  # ... our lots kept there (shrunk with modify_order; 0: cancelled)
REACT_CANCEL = 1  # 1: re-quote from the last snapshot as soon as one of our cancels lands (the queue maker's knob)
DEPL_FRAC = 0.06  # >0: the depletion guard fires only on a touch that has shrunk below this share of its peak since it became the touch (a new level never fires)
BACK_POS = 1000  # beyond this |position|, the side that adds to it quotes one tick behind the touch (1000: never)
FLAT_S = 0  # this many seconds before the end, one IOC at the touch flattens the position (0: never)


class LadderMakerStrategy(BaseStrategy):
    """Rest a ladder of orders on each side; keep queue places; a limit that counts every order able to fill."""

    def __init__(self) -> None:
        super().__init__()
        self._position: int = 0
        self._orders: dict[str, list] = {}  # id -> [side, price, quantity left, cancelling, is_ioc, modify target]
        self._start_us: None | int = None
        self._snap: None | OrderBookSnapshot = None
        self._peak: dict = {}  # side -> [touch price, the market lots there at their most since it became the touch]
        self._ioc_pending: bool = False
        self._flattened: bool = False

    def on_order_book_change(self, snapshot: OrderBookSnapshot, trades: list[Trade]) -> None:
        """Keep the ladder on each side."""
        self._snap = snapshot
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
        if FLAT_S and not self._flattened and not self._ioc_pending and elapsed_s > SESSION_S - FLAT_S:
            self._flattened = True
            if position > 0:
                self._send(Side.SELL, best_bid, position, True)
            elif position < 0:
                self._send(Side.BUY, best_ask, -position, True)
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
        if position >= BACK_POS:
            bid_anchor = best_bid - 1
        if position <= -BACK_POS:
            ask_anchor = best_ask + 1
        bid_cap = SIZE_TOUCH if spread >= 2 else SIZE_NARROW
        ask_cap = bid_cap
        bid_trim = SHRINK_NARROW and spread < 2
        ask_trim = bid_trim
        bid_dying = bid_lots < DEPLETE_LOTS
        ask_dying = ask_lots < DEPLETE_LOTS
        if DEPL_FRAC > 0:
            for key, price, lots in (('B', best_bid, bid_lots), ('A', best_ask, ask_lots)):
                peak = self._peak.get(key)
                if peak is None or peak[0] != price:
                    self._peak[key] = [price, lots]
                elif lots > peak[1]:
                    peak[1] = lots
            bid_dying = bid_dying and bid_lots < DEPL_FRAC * self._peak['B'][1]
            ask_dying = ask_dying and ask_lots < DEPL_FRAC * self._peak['A'][1]
        if bid_dying:
            bid_cap = min(bid_cap, DEPLETE_SIZE)
            bid_trim = True
        if ask_dying:
            ask_cap = min(ask_cap, DEPLETE_SIZE)
            ask_trim = True
        self._ladder(Side.BUY, bid_anchor, want_bid, cancel_bid, bid_cap, bid_trim)
        self._ladder(Side.SELL, ask_anchor, want_ask, cancel_ask, ask_cap, ask_trim)

    def _trim(self, side: Side, best: int, cap: int) -> None:
        """Shrink our orders at the touch to cap lots in all, the newest (the back of the queue) first."""
        mine = []
        total = 0
        for order_id, order in self._orders.items():
            if order[0] == side and not order[3] and not order[4] and order[1] == best:
                mine.append(order_id)
                total += order[2]
        excess = total - cap
        for order_id in reversed(mine):
            if excess <= 0:
                return
            order = self._orders[order_id]
            if order[5]:
                excess -= order[2] - order[5]
                continue
            if order[2] <= excess:
                self.cancel_order(order_id)
                order[3] = True
                excess -= order[2]
            else:
                self.modify_order(order_id, order[2] - excess)
                order[5] = order[2] - excess
                excess = 0

    def _ladder(self, side: Side, best: int, want: bool, cancel_all: bool, cap: int = SIZE_TOUCH, trim: bool = False) -> None:
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
        if trim:
            self._trim(side, best, cap)
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
            size = cap if level == 0 else SIZE_DEEP
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
        self._orders[order_id] = [side, price, quantity, False, ioc, 0]
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
        elif event.status == OrderStatus.MODIFIED:
            order[2] = event.remaining_quantity
            order[5] = 0
        elif event.status == OrderStatus.REJECTED and order[5]:
            order[5] = 0  # a modify that lost the race against a fill: the order still rests
        elif event.status == OrderStatus.CANCELED or event.status == OrderStatus.REJECTED:
            done = True
        if done:
            self._orders.pop(event.order_id, None)
            if order[4]:
                self._ioc_pending = False
            if REACT_CANCEL and event.status == OrderStatus.CANCELED and self._snap is not None:
                self.on_order_book_change(self._snap, [])
