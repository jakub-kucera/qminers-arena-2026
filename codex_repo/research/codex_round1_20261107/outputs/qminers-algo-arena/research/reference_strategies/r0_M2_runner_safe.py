"""Playground candidate M2 (7 Nov): the momentum runner with two protections on: a 2 s flow window and no taking while
the spread is wider than 2 ticks. Sample +305,374 (last 25% +71,955), as M1 or better; on two ABIDES tapes -45,217 and
-43,606 against M1's -582,585 and -366,085 (entering after an order had cleared the touch). Set MAX_SPREAD to the
round's usual spread (experiments.day.round_start prints it).
Family 1b (7 Nov): momentum runner, the momentum taker driven by the mid's move as well as the tape's flow, with
explicit exits. A run starts when the mid has moved MOVE_TICKS or more over the last LOOKBACK book events, or (if
FLOW_ENTRY) on an aggressive trade of at least MIN_FLOW lots; while it lasts, IOCs at the touch (CROSS ticks through
it) take every lot offered until the position reaches MAX_POS the run's way. A run ends on a trailing stop (the mid
TRAIL_TICKS back from its best since the entry), a take-profit (the mid TP_TICKS past the entry's), a time stop
(HOLD_MS), or a signal the other way (which starts the opposite run at once if FLIP). After an exit, no run starts for
COOLDOWN_MS. One taker order in flight; the limit counts every order that can still fill, so |position| never exceeds
MAX_POS. In the last WIND_DOWN_S seconds no run starts and the position is closed.
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


LOOKBACK = 20  # book events the mid's move is measured over
MOVE_TICKS = 0  # a move of at least this many ticks starts a run (0: off)
FLOW_ENTRY = 1  # 1: an aggressive trade starts a run too
MIN_FLOW = 1  # lots of net aggressive flow in one call that count as a trade signal
MAX_POS = 100  # |position| cap, every order that can still fill counted
TRAIL_TICKS = 3  # >0: end the run when the mid is this far back from its best since the entry
TP_TICKS = 0  # >0: end the run when the mid is this far past the entry's mid
HOLD_MS = 0  # >0: end the run this long after it started
FLIP = 1  # 1: a signal the other way starts the opposite run at once
COOLDOWN_MS = 0  # no new run this long after an exit
CROSS = 0  # ticks through the touch for the IOC price
WIND_DOWN_S = 30  # no new runs in the last this many seconds, and close what is open
SESSION_S = 3600  # the session's length in seconds (set it from the round's data)
# Protections for a recorded tape, all off by default (the sample's result is the same with them off):
FLOW_WINDOW_MS = 2000  # >0: the flow signal is the net aggressive flow over this many ms, not one call's
MIN_TRADE = 0  # >0: trades smaller than this many lots don't count as flow
MAX_SPREAD = 2  # >0: send no taker order while the spread is wider than this many ticks
MAX_RUNS_PER_MIN = 0  # >0: no new run (and no flip) once this many have started in the last 60 s
LOSS_STOP = 0  # >0: once the PnL (cash + position at the mid) is below -LOSS_STOP, flatten and stop for the session
MIN_TOUCH = 0  # >0: take only while at least this many lots of the market's sit at the touch we take from (a thin touch is the move's end)


class MomentumRunnerStrategy(BaseStrategy):
    """Ride the mid's runs to MAX_POS with IOCs; leave on a trailing stop, a target, a time stop or a reversal."""

    def __init__(self) -> None:
        super().__init__()
        self._pos: int = 0
        self._orders: dict[str, list] = {}  # id -> [sign, price, left, cancelling, ioc]
        self._start_us: None | int = None
        self._mids: deque = deque(maxlen=LOOKBACK + 1)
        self._dir: int = 0  # the run's direction, 0 when none
        self._entry_us: int = 0
        self._entry_mid: float = 0.0
        self._best_mid: float = 0.0
        self._cool_until: int = 0
        self._taker_id: None | str = None
        self._flow: deque = deque()  # (time, signed lots) of the aggressive trades within FLOW_WINDOW_MS
        self._flow_sum: int = 0
        self._runs: deque = deque()  # start times of the runs within the last 60 s
        self._cash: float = 0.0
        self._stopped: bool = False

    def _room(self, sign: int) -> int:
        exposure = 0
        for order in self._orders.values():
            if order[0] == sign:
                exposure += order[2]
        return MAX_POS - sign * self._pos - exposure

    def _send(self, sign: int, price: int, quantity: int) -> None | str:
        quantity = min(quantity, self._room(sign))
        if quantity <= 0 or price <= 0:
            return None
        order_id = self.send_order(
            OrderRequest(
                side=Side.BUY if sign > 0 else Side.SELL,
                price=price,
                quantity=quantity,
                order_type=OrderType.IOC,
            )
        )
        self._orders[order_id] = [sign, price, quantity, False, True]
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
        self._mids.append(mid)

        signal = 0
        if MOVE_TICKS > 0 and len(self._mids) > LOOKBACK:
            move = mid - self._mids[0]
            if move >= MOVE_TICKS:
                signal = 1
            elif move <= -MOVE_TICKS:
                signal = -1
        if FLOW_ENTRY:
            net = 0
            for trade in trades:
                if trade.taker_owner == 'market' and trade.quantity >= MIN_TRADE:
                    net += trade.quantity if trade.book_side == 'ask' else -trade.quantity
            if FLOW_WINDOW_MS > 0:
                if net != 0:
                    self._flow.append((now, net))
                    self._flow_sum += net
                while self._flow and self._flow[0][0] < now - FLOW_WINDOW_MS * 1000:
                    self._flow_sum -= self._flow.popleft()[1]
                net = self._flow_sum
            if net >= MIN_FLOW:
                signal = 1
            elif net <= -MIN_FLOW:
                signal = -1

        late = (now - self._start_us) / 1_000_000 > SESSION_S - WIND_DOWN_S
        if LOSS_STOP > 0 and not self._stopped and self._cash + self._pos * mid < -LOSS_STOP:
            self._stopped = True
        if self._stopped:
            late = True  # flatten and start nothing, as at the end
        if MAX_RUNS_PER_MIN > 0:
            while self._runs and self._runs[0] < now - 60_000_000:
                self._runs.popleft()
            if len(self._runs) >= MAX_RUNS_PER_MIN:
                signal = 0
        if self._dir != 0:
            if (mid - self._best_mid) * self._dir > 0:
                self._best_mid = mid
            end = late
            if TRAIL_TICKS > 0 and (self._best_mid - mid) * self._dir >= TRAIL_TICKS:
                end = True
            if TP_TICKS > 0 and (mid - self._entry_mid) * self._dir >= TP_TICKS:
                end = True
            if HOLD_MS > 0 and now - self._entry_us >= HOLD_MS * 1000:
                end = True
            if signal == -self._dir:
                end = True
            if end:
                self._dir = 0
                self._cool_until = now + COOLDOWN_MS * 1000
                if FLIP and signal != 0 and not late:
                    self._start_run(signal, now, mid)
        elif signal != 0 and not late and now >= self._cool_until:
            self._start_run(signal, now, mid)

        if self._taker_id is not None:
            return
        if MAX_SPREAD > 0 and best_ask - best_bid > MAX_SPREAD and self._dir != 0:
            return
        if MIN_TOUCH > 0 and self._dir != 0 and not self._stopped and not late:
            touch = 0
            for order in (snapshot.asks if self._dir * MAX_POS > self._pos else snapshot.bids):
                if order.owner != 'market':
                    continue
                if order.price != (best_ask if self._dir * MAX_POS > self._pos else best_bid):
                    break
                touch += order.quantity
            if touch < MIN_TOUCH:
                return
        target = self._dir * MAX_POS
        want = target - self._pos
        if want > 0:
            self._taker_id = self._send(1, best_ask + CROSS, want)
        elif want < 0:
            self._taker_id = self._send(-1, best_bid - CROSS, -want)

    def _start_run(self, sign: int, now: int, mid: float) -> None:
        self._runs.append(now)
        self._dir = sign
        self._entry_us = now
        self._entry_mid = mid
        self._best_mid = mid

    def on_private_order_update(self, event: PrivateOrderEvent) -> None:
        order = self._orders.get(event.order_id)
        if order is None:
            return
        status = event.status
        if status == OrderStatus.PARTIALLY_FILLED or status == OrderStatus.FILLED:
            filled = event.filled_quantity
            self._pos += filled if order[0] > 0 else -filled
            self._cash -= (filled if order[0] > 0 else -filled) * event.fill_price
            order[2] = event.remaining_quantity
            if status == OrderStatus.FILLED or event.remaining_quantity == 0:
                self._orders.pop(event.order_id, None)
                if event.order_id == self._taker_id:
                    self._taker_id = None
        elif status == OrderStatus.CANCELED or status == OrderStatus.REJECTED:
            self._orders.pop(event.order_id, None)
            if event.order_id == self._taker_id:
                self._taker_id = None
