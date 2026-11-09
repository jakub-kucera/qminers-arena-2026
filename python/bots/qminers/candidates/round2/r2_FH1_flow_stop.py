"""Round 2 candidate R2-FH1 (7 Nov, 20:15, the fable worktree): the flow holder (family 14) at GRACE_MS 0 (an IOC entry, which reproduces the board's momentum agent to the cent: 118,374) and STOP 3 (flatten when the mid has moved 3 ticks against the position since its signal): 132,005 on round2_public.csv (in 75% 109,253, last 25% 22,752; STOP 4 129,685 / 107,626 / 22,059; 5 126,863; 2 123,062; 10 117,669; off 118,374), max drawdown 17,140 against 19,543, pnl_se 29.3k. Every other knob tested loses or ties: a passive entry (GRACE_MS 100 / 1,000: -6k / +10k against +118k, the impact lands inside 100 ms), a decay to flat (FLAT_S 10-90: ties), a passive unwind (ties), only big orders that moved the touch (CLEAR_ONLY 1: 50,675). The family's notes follow.
Family 14 (7 Nov, round 2): the flow holder. Round 2's public tape: aggressive orders of 500+ lots move the mid 1.3-2.0
ticks by 5 s (round 1: 0.5) and the move stays, so holding EXPOSURE lots on the side of the last big aggressor collects the
impact of each one (the momentum agent of the round-2 board: +118k with IOC entries and flips at 100 lots). This family
enters and flips PASSIVELY where it can: the target side is the side of the last aggressive order of MIN_LOTS lots or more;
the bot rests a limit order at the touch on that side for the lots it still needs (joining the queue, first when the level is
new), and only if that order has not filled within GRACE_MS does it cross the spread with an IOC for the remainder (GRACE_MS 0:
always an IOC, the momentum agent's way; a very large GRACE_MS: never). A target that flips cancels the resting order and
works the new side the same way; while the old position is being unwound the two legs are one order (the reducing side first).
With FLAT_S, a target with no big order for that long becomes flat, and with EXIT_PASSIVE the unwind rests at the touch
(it crosses only when a new big order flips the target); CLEAR_ONLY takes only big orders that moved the touch they hit.
A stop: if the mid has moved STOP ticks against the position since its target was set, the position is flattened with an IOC
and no new target is taken until the next big order. The limit counts every order that can still fill; |position| never
beyond EXPOSURE. No wind-down.

Knobs: MIN_LOTS (the aggressor size that sets the target), EXPOSURE (the lots held), GRACE_MS (how long the passive entry
may wait before an IOC completes it), STOP (ticks against the position before a flatten; 0: off), INSIDE (1: rest one tick
inside the touch when the spread is 2+ ticks, first in a new queue; 0: at the touch), REQUOTE_MS (re-post the passive order
if the touch moved away by then).
"""

from __future__ import annotations

from simulator.models import OrderBookSnapshot, OrderRequest, OrderStatus, OrderType, PrivateOrderEvent, Side, Trade
from simulator.strategy import BaseStrategy

MIN_LOTS = 500  # an aggressive order of this many lots or more sets the target side
EXPOSURE = 100  # the lots held on the target side
GRACE_MS = 0  # the passive entry's grace before an IOC completes it (0: always IOC)
STOP = 3  # flatten when the mid has moved this many ticks against the position since the target was set (0: off)
INSIDE = 0  # 1: the passive order one tick inside the touch when the spread is 2+ ticks
FLAT_S = 0.0  # >0: with no big order for this many seconds the target is flat (the position unwound)
EXIT_PASSIVE = 0  # 1: an unwind toward flat (not a flip) rests at the touch and never crosses; 0: it follows GRACE_MS
CLEAR_ONLY = 0  # 1: only a big order whose event moved the touch it hit sets the target
SESSION_S = 1_000_000_000  # unused: no wind-down


class FlowHolder(BaseStrategy):
    """Hold EXPOSURE lots on the side of the last big aggressor, entering passively, crossing after a grace."""

    def __init__(self) -> None:
        super().__init__()
        self._position: int = 0
        self._orders: dict[str, list] = {}  # id -> [side, price, lots left, cancelling, ioc]
        self._target: int = 0  # +1 long, -1 short, 0 flat (after a stop)
        self._target_us: int = 0
        self._target_mid: float = 0.0
        self._ioc_pending: bool = False
        self._now_us: int = 0
        self._signal_us: int = 0  # the last big order's time
        self._prev_touch: None | tuple = None

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
        for order in snapshot.asks:
            if order.owner == 'market':
                best_ask = order.price
                break
        if best_bid is None or best_ask is None:
            return
        mid = (best_bid + best_ask) / 2
        spread = best_ask - best_bid
        # the signal: the biggest aggressive order in this event's trades, per taker
        hit: dict = {}
        for trade in trades:
            if trade.taker_owner == 'market':
                key = (trade.taker_order_id, trade.book_side)
                hit[key] = hit.get(key, 0) + trade.quantity
        for (taker, book_side), lots in hit.items():
            if lots >= MIN_LOTS:
                if CLEAR_ONLY and self._prev_touch is not None:
                    moved = best_ask > self._prev_touch[1] if book_side == 'ask' else best_bid < self._prev_touch[0]
                    if not moved:
                        continue
                new_target = 1 if book_side == 'ask' else -1  # buyers lifted the ask: go long
                self._signal_us = self._now_us
                if new_target != self._target:
                    self._target = new_target
                    self._target_us = self._now_us
                    self._target_mid = mid
        self._prev_touch = (best_bid, best_ask)
        if FLAT_S > 0 and self._target != 0 and self._now_us - self._signal_us >= FLAT_S * 1_000_000:
            self._target = 0
            self._target_us = self._now_us
        # the stop
        if STOP > 0 and self._target != 0 and self._position != 0:
            against = self._target * (self._target_mid - mid)
            if against >= STOP:
                self._target = 0
        want = self._target * EXPOSURE
        need = want - self._position
        side = Side.BUY if need > 0 else Side.SELL
        # cancel resting orders on the wrong side, or at a price the touch has left
        for order_id, order in list(self._orders.items()):
            if order[3] or order[4]:
                continue
            wrong_side = (need > 0 and order[0] == Side.SELL) or (need < 0 and order[0] == Side.BUY) or need == 0
            touch = best_bid if order[0] == Side.BUY else best_ask
            stale = order[1] != touch and (order[1] != (best_bid + 1 if order[0] == Side.BUY else best_ask - 1) or spread < 2)
            if wrong_side or stale:
                self.cancel_order(order_id)
                order[3] = True
        if need == 0 or self._ioc_pending:
            return
        # the lots still uncovered by live orders on the needed side (every order that can still fill counts)
        live = sum(o[2] for o in self._orders.values() if o[0] == side)
        uncovered = abs(need) - live
        unwinding = self._target == 0 and self._position != 0
        grace_over = self._now_us - self._target_us >= GRACE_MS * 1000 and not (EXIT_PASSIVE and unwinding)
        if uncovered <= 0:
            # a passive order is out: once its grace is over, cancel it; the IOC goes out on the next call, when the
            # cancel has landed, so a fill that beats the cancel can never add to an IOC's lots
            if grace_over:
                for oid, o in self._orders.items():
                    if o[0] == side and not o[3] and not o[4]:
                        self.cancel_order(oid)
                        o[3] = True
            return
        if grace_over:
            price = best_ask if side == Side.BUY else best_bid
            self._send(side, price, uncovered, True)
            return
        if side == Side.BUY:
            price = best_bid + 1 if (INSIDE and spread >= 2) else best_bid
        else:
            price = best_ask - 1 if (INSIDE and spread >= 2) else best_ask
        self._send(side, price, uncovered, False)

    def _send(self, side: Side, price: int, lots: int, ioc: bool) -> None:
        order_type = OrderType.IOC if ioc else OrderType.LIMIT
        order_id = self.send_order(OrderRequest(side=side, price=price, quantity=lots, order_type=order_type))
        self._orders[order_id] = [side, price, lots, False, ioc]
        if ioc:
            self._ioc_pending = True

    def on_private_order_update(self, event: PrivateOrderEvent) -> None:
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
