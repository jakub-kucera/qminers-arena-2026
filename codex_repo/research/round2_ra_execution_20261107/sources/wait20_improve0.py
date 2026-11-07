"""Experimental passive-first RA execution. Prior scores do not apply."""

from __future__ import annotations

from collections import deque

from simulator.models import OrderBookSnapshot, OrderRequest, OrderStatus, OrderType, PrivateOrderEvent, Side, Trade
from simulator.strategy import BaseStrategy


MIN_LOTS = 500  # an aggressive order this large (one call's net), or a window's net this large, sets the big signal
FLOW_MS = 250  # > 0: the big signal fires on the net market-taker lots over this window; 0: on one call's net alone
SQRT = 0  # 1: weight each order's lots by sqrt(lots / SQRT_REF) before the window sum
SQRT_REF = 500
CONSUME = 1  # 1: clear the window when the signal fires; 0: keep it, re-firing on every order while past MIN_LOTS
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
STOP = 3  # > 0: flat once the mid has moved this many ticks against the position since the big signal was set


class FlowTrendStrategy(BaseStrategy):
    """Hold MAX_POS lots the way of the recent big aggressive flow and/or the minute-scale trend."""

    def __init__(self) -> None:
        super().__init__()
        self._exec_target=None
        self._exec_deadline=0
        self._exec_passive=False
        self._exec_accepted=False
        self._exec_cancel=False
        self._pos = 0
        self._orders = {}  # id -> [sign, price, left]
        self._start_us = None
        self._hists = [deque() for _ in LOOKBACKS_MS]
        self._bands = [0] * len(LOOKBACKS_MS)
        self._big = 0
        self._big_us = 0
        self._big_mid = 0.0  # the mid when the big signal was set (STOP)
        self._stopped = False  # the stop has fired: flat until the next big order
        self._flow = deque()  # (time_us, signed weighted lots) of the aggressive orders in the window (FLOW_MS)
        self._flow_sum = 0
        self._fires = 0
        self._multi_fires = 0
        self._arms = 0
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
            OrderRequest(side=Side.BUY if sign > 0 else Side.SELL, price=price, quantity=quantity, order_type=OrderType.LIMIT if self._exec_passive else OrderType.IOC)
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

        net = 0
        for trade in trades:
            if trade.taker_owner == 'market':
                net += trade.quantity if trade.book_side == 'ask' else -trade.quantity
        flow = net
        if SQRT and net:
            flow = net * (abs(net) / SQRT_REF) ** 0.5
        orders_in_window = 1
        if FLOW_MS > 0:
            window = self._flow
            horizon = now - FLOW_MS * 1000
            while window and window[0][0] < horizon:
                self._flow_sum -= window.popleft()[1]
            if not window:
                self._flow_sum = 0
            if flow:
                window.append((now, flow))
                self._flow_sum += flow
            flow = self._flow_sum if net else 0
            orders_in_window = len(window)
        fired = 0
        if flow >= MIN_LOTS:
            if self._big != 1 or self._stopped:
                self._big_mid = mid
                self._stopped = False
                self._arms += 1
            self._big = 1
            self._big_us = now
            fired = 1
        elif flow <= -MIN_LOTS:
            if self._big != -1 or self._stopped:
                self._big_mid = mid
                self._stopped = False
                self._arms += 1
            self._big = -1
            self._big_us = now
            fired = 1
        if fired:
            self._fires += 1
            if orders_in_window > 1:
                self._multi_fires += 1
            if FLOW_MS > 0 and CONSUME:
                self._flow.clear()
                self._flow_sum = 0
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
        if STOP > 0:
            if not self._stopped and self._big != 0 and self._pos != 0 and self._big * (self._big_mid - mid) >= STOP:
                self._stopped = True
            if self._stopped:
                target = 0
        self._execute(now,target,best_bid,best_ask)

    def _execute(self,now,target,bid,ask):
        changed=target!=self._exec_target
        if changed:
            self._exec_target=target
            self._exec_deadline=now+20000
        if self._taker_id is not None:
            if self._exec_passive and self._exec_accepted and not self._exec_cancel:
                if changed or target==self._pos or now>=self._exec_deadline:
                    self.cancel_order(self._taker_id)
                    self._exec_cancel=True
            return
        want=target-self._pos
        if not want:
            return
        # Stops flatten immediately; directional entries/flips get one short grace period.
        self._exec_passive=target!=0 and now<self._exec_deadline
        self._exec_accepted=False
        self._exec_cancel=False
        sign=1 if want>0 else -1
        if self._exec_passive:
            price=min(ask-1,bid+0) if sign>0 else max(bid+1,ask-0)
        else:
            price=ask if sign>0 else bid
        self._taker_id=self._send(sign,price,abs(want))

    def on_private_order_update(self, event: PrivateOrderEvent) -> None:
        order = self._orders.get(event.order_id)
        if order is None:
            return
        if event.order_id==self._taker_id and event.status==OrderStatus.ACCEPTED:
            self._exec_accepted=True
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