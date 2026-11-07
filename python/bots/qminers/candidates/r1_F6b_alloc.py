"""Round 1 candidate R1-F6b (7 Nov, 14:25): R1-F6 with ALLOC_K -0.5 (fewer lots at the back of a long queue, more on the short side's
touch; nothing cancelled for it), chosen on round1's first 75% (362,752): full +489,844, the last 25% +127,092, ahead of F6 in 11 of 12
segments, sample_v2 +238,426 (+1,583 against F6).
Family 12 (7 Nov, round 1): R1-F6 (candidates/r1_F6_two_levels.py) with three ways to place its lots without
cancelling anything for them, every knob defaulting to F6 exactly. ALLOC_K: the touch imbalance I = (bid - ask) /
(bid + ask) moves lots between a side's touch and its deep level (the touch cap times 1 + ALLOC_K * I on the bid,
1 - ALLOC_K * I on the ask; lots taken off the touch go to the level behind, so the total stays what the limit allows).
INV_K: the same by position (when long, a smaller bid touch and more lots behind it, a fuller ask touch; the reverse when
short). ALLOC_UP 0 lets either only shrink the touch. ADV_TH: an online adverse table, a running mean of our fills'
ADV_MS markout (ticks a lot) per state (the side's signed imbalance tercile x spread 1 or 2+), learned as the session
runs; after ADV_MIN lots in a state, a side whose state's mean is below ADV_TH posts no top-up (ADV_SCOPE 2: no new
touch order at all). ALLOC_KU, ALLOC_HI, ALLOC_TH, ALLOC_DEEP shape ALLOC_K (see their comments). On round1 (IDEAS.md,
"Allocate, don't gate"): ALLOC_K -0.5 (the thick side's touch smaller, the thin side's fuller) +489,844 (+6,770, 11 of 12
segments up), below the bar for a replacement; INV_K flat, ADV_TH only loses volume. R1-F6's notes follow.

Round 1 candidate R1-F6 (7 Nov, 14:00): R1-F5 with a second level (LEVELS 2, KEEP_DEPTH 2, SIZE_TOUCH 65, SIZE_DEEP 80,
SIZE_NARROW 115, TOPUP 1), chosen on round1's first 75% from a broad plateau (356,715): full +483,074, the last 25% +126,359,
up in 4 of 4 quarters; but -35k against R1-F5 on sample_v2 (236,843 against 271,947), a 2-tick market. Was: R1-F5 (7 Nov, 13:35): the shrink maker with REACT_CANCEL 1, DEPLETE_LOTS 100, DEPL_FRAC 0.06
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


LEVELS = 2  # price levels quoted a side, the touch first
KEEP_DEPTH = 2  # an order more than KEEP_DEPTH-1 ticks behind the touch is cancelled
SIZE_TOUCH = 65  # lots at the touch: 200 is all the room the limit gives (LIMIT + |position|)
SIZE_DEEP = 80  # lots on each level behind it
LIMIT = 100  # every order that can still fill, counted against the 100 the penalty starts at
SKEW = 100  # beyond this many lots, stop quoting the side that adds to the position (100: the limit does it)
SKEW_CANCEL = 1  # 1: cancel that side's orders beyond SKEW; 0: keep them, post none
CANCEL_ALONE = 1  # 1: cancel an order priced in front of the market's touch
REBALANCE = 0  # 1: cancel the side's deepest order to make room at an empty touch
IMB = 0.0  # quote a side only while the market's lots at its touch are at least IMB times the other touch's (0: off)
MIN_QUEUE = 0  # quote a side only while the market has at least this many lots at its touch
INSIDE_POS = 1000  # beyond this |position|, the reducing side quotes one tick inside the touch (1000: never)
INSIDE_SPREAD = 2  # ... when the spread is at least this many ticks
TOPUP = 1  # with TOPUP lots or more of room left, add another order behind ours at the touch (0: one order a level)
UNWIND = 1000  # beyond this |position| an IOC at the touch trades back to UNWIND_TO (1000: never)
UNWIND_TO = 50
WIND_DOWN_S = 60  # in the last this many seconds, quote only the side that reduces the position
SESSION_S = 1_000_000_000  # the session's length in seconds (set it from the round's data)
SIZE_NARROW = 115  # lots at the touch while the spread is one tick (200: as SIZE_TOUCH)
SHRINK_NARROW = 0  # 1: shrink resting touch orders to SIZE_NARROW (modify keeps the place) while the spread is one tick
DEPLETE_LOTS = 100  # a touch whose market queue holds fewer lots than this is about to clear (0: off)
DEPLETE_SIZE = 0  # ... our lots kept there (shrunk with modify_order; 0: cancelled)
REACT_CANCEL = 1  # 1: re-quote from the last snapshot as soon as one of our cancels lands (the queue maker's knob)
DEPL_FRAC = 0.06  # >0: the depletion guard fires only on a touch that has shrunk below this share of its peak since it became the touch (a new level never fires)
BACK_POS = 1000  # beyond this |position|, the side that adds to it quotes one tick behind the touch (1000: never)
ALLOC_K = -0.5  # touch cap x (1 + ALLOC_K * imbalance) on the bid, (1 - ALLOC_K * imbalance) on the ask; the rest behind (0: off)
INV_K = 0.0  # touch cap x (1 - INV_K * position / LIMIT) on the bid, (1 + ...) on the ask; the rest behind (0: off)
ALLOC_UP = 1  # 1: the factor may also raise a touch cap above F6's (up to ALLOC_HI times); 0: only shrink it
ALLOC_HI = 2.0
ALLOC_KU = 0.0  # the imbalance's coefficient where it raises a touch cap (0: ALLOC_K's)
ALLOC_TH = 0.0  # the imbalance counts only beyond this |imbalance| (0: always)
ALLOC_DEEP = 1  # 1: lots taken off a touch go to the level behind; 0: they are not quoted
ADV_TH = -1000.0  # post a top-up only while our fills' running markout in the current state is at least this (-1000: off)
ADV_MIN = 2000  # ... once the state has this many filled lots measured
ADV_MS = 1000  # the markout's horizon
ADV_SCOPE = 1  # 1: gate top-ups only; 2: every new order at the touch
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
        self._pending = deque()  # [due us, sign, price, lots, state] per fill, for its markout
        self._adv_sum = [0.0] * 6  # state -> sum of markout x lots
        self._adv_lots = [0] * 6
        self._bstate: int = 1
        self._astate: int = 4

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
        bid_deep = SIZE_DEEP
        ask_deep = SIZE_DEEP
        if ALLOC_K or INV_K:
            imb = (bid_lots - ask_lots) / (bid_lots + ask_lots)
            if -ALLOC_TH <= imb <= ALLOC_TH:
                imb = 0.0
            inv = INV_K * position / LIMIT
            shift = ALLOC_K * imb - inv
            hi = ALLOC_HI if ALLOC_UP else 1.0
            if not bid_dying:
                factor = 1.0 + shift
                if ALLOC_KU and factor > 1.0:
                    factor = 1.0 + ALLOC_KU * imb - inv
                new = int(bid_cap * min(hi, max(0.0, factor)) + 0.5)
                if new < bid_cap and ALLOC_DEEP:
                    bid_deep += bid_cap - new
                bid_cap = new
            if not ask_dying:
                factor = 1.0 - shift
                if ALLOC_KU and factor > 1.0:
                    factor = 1.0 - ALLOC_KU * imb + inv
                new = int(ask_cap * min(hi, max(0.0, factor)) + 0.5)
                if new < ask_cap and ALLOC_DEEP:
                    ask_deep += ask_cap - new
                ask_cap = new
        bid_top = True
        ask_top = True
        if ADV_TH > -1000:
            now = snapshot.timestamp_us
            mid = (best_bid + best_ask) / 2
            pending = self._pending
            while pending and pending[0][0] <= now:
                due, sign, price, lots, state = pending.popleft()
                self._adv_sum[state] += sign * (mid - price) * lots
                self._adv_lots[state] += lots
            imb = (bid_lots - ask_lots) / (bid_lots + ask_lots)
            wide = 3 if spread >= 2 else 0
            self._bstate = wide + (0 if imb < -1 / 3 else (2 if imb > 1 / 3 else 1))
            self._astate = wide + (0 if imb > 1 / 3 else (2 if imb < -1 / 3 else 1))
            n = self._adv_lots[self._bstate]
            bid_top = n < ADV_MIN or self._adv_sum[self._bstate] >= ADV_TH * n
            n = self._adv_lots[self._astate]
            ask_top = n < ADV_MIN or self._adv_sum[self._astate] >= ADV_TH * n
        self._ladder(Side.BUY, bid_anchor, want_bid, cancel_bid, bid_cap, bid_trim, bid_deep, bid_top)
        self._ladder(Side.SELL, ask_anchor, want_ask, cancel_ask, ask_cap, ask_trim, ask_deep, ask_top)

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

    def _ladder(self, side: Side, best: int, want: bool, cancel_all: bool, cap: int = SIZE_TOUCH, trim: bool = False, deep: int = SIZE_DEEP, top_ok: bool = True) -> None:
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
            size = cap if level == 0 else deep
            if level == 0 and not top_ok and (ADV_SCOPE == 2 or level in have):
                continue
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
            if ADV_TH > -1000 and not order[4] and event.fill_price is not None:
                buy = order[0] == Side.BUY
                self._pending.append((event.timestamp_us + ADV_MS * 1000, 1 if buy else -1, event.fill_price,
                                      event.filled_quantity, self._bstate if buy else self._astate))
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
