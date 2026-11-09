"""Experimental M2 extension. Scores must come from its own replay."""

from __future__ import annotations

from collections import deque

from simulator.models import OrderBookSnapshot, OrderRequest, OrderStatus, OrderType, PrivateOrderEvent, Side, Trade
from simulator.strategy import BaseStrategy


MIN_LOTS = 500  # an aggressive order this large (one call's net) sets the big signal
HOLD_MS = 0  # > 0: the big signal lapses this long after its order
LOOKBACKS_MS = (60000, 90000, 120000)  # the trend's lookbacks
ENTER_TICKS = 8  # a move of at least this many ticks over a lookback sets its band
W_BIG = 1.0
W_TREND = 0.0
GATE = 0  # 1: hold the big signal only when the trend's sign agrees with it
MAX_POS = 100  # |position| cap, every order that can still fill counted
MIN_CHANGE = 1  # don't trade towards the target for fewer lots than this
CROSS = 0  # ticks through the touch for the IOC price
SELF_GATE = 1  # 1: trade only while a one-lot shadow of the signal is up more than GATE_TICKS since the start
GATE_TICKS = 10


class FlowTrendStrategy(BaseStrategy):
    """Hold MAX_POS lots the way of the last big aggressive order and/or the minute-scale trend."""

    def __init__(self) -> None:
        super().__init__()
        self._pos = 0
        self._orders = {}  # id -> [sign, price, left]
        self._start_us = None
        self._hists = [deque() for _ in LOOKBACKS_MS]
        self._bands = [0] * len(LOOKBACKS_MS)
        self._big = 0
        self._big_us = 0
        self._taker_id = None
        self._shadow_pos = 0
        self._shadow_cash = 0.0

    def _room(self, sign: int) -> int:
        exposure = 0
        for order in self._orders.values():
            if order[0] == sign:
                exposure += order[2]
        return MAX_POS - sign * self._pos - exposure

    def _send(self, sign: int, price: int, quantity: int):
        quantity = min(quantity, self._room(sign))
        if quantity <= 0 or price <= 0:
            return None
        order_id = self.send_order(
            OrderRequest(side=Side.BUY if sign > 0 else Side.SELL, price=price, quantity=quantity, order_type=OrderType.IOC)
        )
        self._orders[order_id] = [sign, price, quantity]
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

        visible={o.order_id:o for side in (snapshot.bids,snapshot.asks) for o in side if o.owner=='market'}
        aggressors={}
        for trade in trades:
            if trade.taker_owner=='market':
                row=aggressors.setdefault(trade.taker_order_id,[1 if trade.book_side=='ask' else -1,0])
                row[1]+=trade.quantity
        net=0
        for oid,(sign,quantity) in aggressors.items():
            if oid in visible:
                net+=sign*quantity
        if net >= MIN_LOTS:
            self._big = 1
            self._big_us = now
        elif net <= -MIN_LOTS:
            self._big = -1
            self._big_us = now
        big = self._big
        if HOLD_MS > 0 and now - self._big_us > HOLD_MS * 1000:
            big = 0

        trend = 0.0
        if W_TREND != 0 or GATE:
            elapsed = now - self._start_us
            for k in range(len(LOOKBACKS_MS)):
                lookback = LOOKBACKS_MS[k] * 1000
                hist = self._hists[k]
                hist.append((now, mid))
                horizon = now - lookback
                while len(hist) > 1 and hist[1][0] <= horizon:
                    hist.popleft()
                if elapsed >= lookback:
                    move = mid - hist[0][1]
                    if move >= ENTER_TICKS:
                        self._bands[k] = 1
                    elif move <= -ENTER_TICKS:
                        self._bands[k] = -1
            trend = sum(self._bands) / len(self._bands)

        if GATE:
            target = MAX_POS * big if big * trend > 0 else 0
        else:
            x = W_BIG * big + W_TREND * trend
            x = 1.0 if x > 1 else -1.0 if x < -1 else x
            target = int(round(MAX_POS * x))
        if SELF_GATE:
            sign = 1 if target > 0 else -1 if target < 0 else 0
            if sign != self._shadow_pos:
                step = sign - self._shadow_pos
                self._shadow_cash -= step * (best_ask if step > 0 else best_bid)
                self._shadow_pos = sign
            if self._shadow_cash + self._shadow_pos * mid <= GATE_TICKS:
                target = 0
        if self._taker_id is not None:
            return
        want = target - self._pos
        if want >= MIN_CHANGE or (want > 0 and target == MAX_POS):
            self._taker_id = self._send(1, best_ask + CROSS, want)
        elif -want >= MIN_CHANGE or (want < 0 and target == -MAX_POS):
            self._taker_id = self._send(-1, best_bid - CROSS, -want)

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