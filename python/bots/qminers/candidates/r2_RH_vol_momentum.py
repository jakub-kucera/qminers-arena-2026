"""R2-RH (7 Nov, round 2, the fable worktree): R2-M3 with the position scaled by the price's speed, the opposite of the maker's rule: fast = the mid's |change| in ticks a second decayed over VOL_US (the ticks and the elapsed microseconds each decayed, their ratio); the target is MAX_POS lots when fast is at least VOL_HI ticks a second, LOW_POS lots when at least VOL_LO, 0 below (VOL_HI 0 = off = R2-M3 exactly). Why: on round 2 public the momentum agent's PnL concentrates in fast periods (49k of 117k in the 500-s crash) and a big order's impact is what it collects, so a slow stretch is spread paid for little impact. R2-M3's notes follow.
R2-M3 (7 Nov, round 2): R2-M2 (r2_M2_flow_trend.py, below) plus R2-FH1's stop (r2_FH1_flow_stop.py). The stop
(STOP > 0): once the mid has moved STOP ticks against the position since its big signal was set (the mid when the big
signal last changed side, or was set again after a stop), the real target is flat (one IOC at the touch) and stays
flat until the next big order of MIN_LOTS lots. It checks only while the bot holds a position, like FH1's, and acts on
the real target after the self-gate: the shadow keeps following the big signal unstopped, so the gate opens and closes
exactly as R2-M2's does. STOP 0 is R2-M2 exactly (116,620 on round 2's public tape, to the cent).
Round 2's public tape, MIN_LOTS 500 (`--grid STOP=0,2,3,4,5 --grid MIN_LOTS=400,500 --holdout 0.25`, chosen on the
first 75%): STOP 3 130,251 (in 107,499 / out 22,752; 2,052 fills, 282,934 lots, breach 0, max drawdown 17,140 against
19,543, 8 s), STOP 4 127,931, 5 125,109, 2 121,508, 0 116,620; MIN_LOTS 400 lower at every STOP. The stop adds
+13,631, the same as it adds to the ungated FH1 (118,374 -> 132,005). The mirrored public the same; round1.csv -1,242
and the rebuilt round-1 private tape 0, as R2-M2 (the gate is R2-M2's). First trade at 51 s, as R2-M2.
R2-M2 (7 Nov, round 2): follow the big aggressive orders and the minute-scale trend. On round 2's public tape an
aggressive order of 500+ lots moves the mid on by +1.2 to +2 ticks within 5 s (round 1: +0.5), and a move of 8+ ticks
over the last 60-120 s keeps going. Two signals, each -1, 0 or +1:
- big: the side of the last aggressive order of at least MIN_LOTS lots (one call's net market-taker flow), 0 once
  HOLD_MS have passed since it (HOLD_MS 0: never);
- trend: the mean over LOOKBACKS_MS of each lookback's band (+1 once the mid has risen ENTER_TICKS over it, -1 once it
  has fallen as much, else the last), 0 until the lookback has passed.
The target is MAX_POS x clip(W_BIG x big + W_TREND x trend, -1, 1), rounded; with GATE 1 the big signal counts only
when the trend agrees (target MAX_POS x big then, else 0). The position goes to the target by IOCs at the touch (CROSS
ticks through it), one in flight, when it is at least MIN_CHANGE lots away. The limit counts every order that can
still fill, so |position| never exceeds MAX_POS.
The self-gate (SELF_GATE 1): a one-lot shadow holds sign(target) at the touch it sees (bought at the ask, sold at the
bid), and the real target is 0 unless the shadow's PnL since the start is above GATE_TICKS. On round 1's tapes, where
these signals lose (the big orders move the mid +0.5 ticks, under the spread), the gate never opens; on round 2's it
costs about 1-2k.
Round 2's public tape at these defaults: +116,620 (in 95,379 / out 21,241; 1,940 fills, 276,900 lots, breach 0, 11 s);
round 1's: -1,242 with the gate (-157,078 without it). The trend is off (W_TREND 0): blended in, it only lowered the
PnL. Speed matters: at an order delay of 10 / 20 / 50 ms instead of the rules' 5, 111,195 / 91,114 / 38,121.
"""

from __future__ import annotations

from collections import deque

from simulator.models import OrderBookSnapshot, OrderRequest, OrderStatus, OrderType, PrivateOrderEvent, Side, Trade
from simulator.strategy import BaseStrategy


VOL_HI = 0.0  # ticks a second: full size at or above (0: off)
VOL_LO = 0.0  # ticks a second: LOW_POS lots between VOL_LO and VOL_HI, 0 below
LOW_POS = 50
VOL_US = 5000000  # the speed's decay
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
STOP = 3  # > 0: flat once the mid has moved this many ticks against the position since the big signal was set


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
        self._big_mid = 0.0  # the mid when the big signal was set (STOP)
        self._vol_mid = None  # the speed's state (VOL_HI)
        self._vol_us = 0
        self._vol_ticks = 0.0
        self._vol_time = 0.0
        self._stopped = False  # the stop has fired: flat until the next big order
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
        if VOL_HI > 0:
            if self._vol_mid is not None:
                dt = max(1, now - self._vol_us)
                decay = 2.718281828459045 ** (-dt / VOL_US)
                self._vol_ticks = self._vol_ticks * decay + abs(mid - self._vol_mid)
                self._vol_time = self._vol_time * decay + dt / 1_000_000
            self._vol_mid = mid
            self._vol_us = now

        net = 0
        for trade in trades:
            if trade.taker_owner == 'market':
                net += trade.quantity if trade.book_side == 'ask' else -trade.quantity
        if net >= MIN_LOTS:
            if self._big != 1 or self._stopped:
                self._big_mid = mid
                self._stopped = False
            self._big = 1
            self._big_us = now
        elif net <= -MIN_LOTS:
            if self._big != -1 or self._stopped:
                self._big_mid = mid
                self._stopped = False
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
        if VOL_HI > 0 and target != 0:
            fast = self._vol_ticks / self._vol_time if self._vol_time > 0 else 0.0
            if fast < VOL_LO:
                target = 0
            elif fast < VOL_HI:
                target = int(round(LOW_POS * (1 if target > 0 else -1)))
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
