"""R2-RD (7 Nov, round 2): R2-M3 (r2_M3_flow_stop_gated.py, below) with the target sized by the signal. Three knobs,
each off by default (the defaults reproduce R2-M3 to the cent: 130,251.00, 2,052 fills on round 2's public tape):
- BIG2 > 0 (two tiers): a big order of at least BIG2 lots targets MAX_POS lots, one of MIN_LOTS to BIG2 - 1 lots
  SMALL_POS lots; the tier is the last big order's (TIER_KEEP 1: a same-side order never lowers it; a flip or a stop
  resets it). BIG2 0: always MAX_POS.
- CONFIRM2 1: the signal changes only when the last two big orders were on the same side (a double signal); a lone
  order keeps the previous target (also a stopped one: a stop lifts on a confirmed order only).
- SHADOW_SCALE 1: the target (after the self-gate) is scaled by the self-gate shadow's recent PnL, its tick-by-tick
  mark-to-market change decayed with the time constant SHADOW_S seconds: full size at SHADOW_FULL ticks or more, half
  size below SHADOW_HALF (linear between the two), flat below 0. Needs SELF_GATE 1 (the shadow).
The shadow, the self-gate's rule, the stop and the position accounting are R2-M3's.
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

import math
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
STOP = 3  # > 0: flat once the mid has moved this many ticks against the position since the big signal was set
BIG2 = 0  # > 0: a big order of at least this many lots targets MAX_POS, one of MIN_LOTS..BIG2-1 lots SMALL_POS; 0: always MAX_POS
SMALL_POS = 50  # the smaller tier's target
TIER_KEEP = 0  # 1: a same-side big order never lowers the tier; a flip or a stop resets it
CONFIRM2 = 0  # 1: the signal changes only when the last two big orders were on the same side
SHADOW_SCALE = 0  # 1: scale the target by the shadow's decayed PnL (time constant SHADOW_S seconds)
SHADOW_S = 60
SHADOW_FULL = 10  # full size at this many ticks of decayed shadow PnL or more
SHADOW_HALF = 5  # half size below this many ticks (linear up to SHADOW_FULL), flat below 0


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
        self._stopped = False  # the stop has fired: flat until the next big order
        self._taker_id = None
        self._shadow_pos = 0
        self._shadow_cash = 0.0
        self._size = MAX_POS  # the current tier's target (BIG2)
        self._last_side = 0  # the side of the last big order (CONFIRM2)
        self._shadow_pnl = 0.0  # the shadow's PnL at the last tick (SHADOW_SCALE)
        self._recent = 0.0  # the shadow's decayed PnL (SHADOW_SCALE)
        self._last_us = None
        self.n_small = 0  # diagnostics: big orders in the small tier
        self.n_unconfirmed = 0  # big orders not confirming the last one's side
        self.n_scaled = 0  # ticks at which the shadow scale cut the target

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

        net = 0
        for trade in trades:
            if trade.taker_owner == 'market':
                net += trade.quantity if trade.book_side == 'ask' else -trade.quantity
        side = 1 if net >= MIN_LOTS else -1 if net <= -MIN_LOTS else 0
        if side:
            confirmed = side
            if CONFIRM2:
                if self._last_side != side:
                    confirmed = 0
                    self.n_unconfirmed += 1
                self._last_side = side
            if confirmed:
                if BIG2 > 0 and abs(net) < BIG2:
                    tier = SMALL_POS
                    self.n_small += 1
                else:
                    tier = MAX_POS
                if self._big != confirmed or self._stopped:
                    self._big_mid = mid
                    self._stopped = False
                    self._size = tier
                elif tier > self._size or not TIER_KEEP:
                    self._size = tier
                self._big = confirmed
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

        size = self._size
        if GATE:
            target = size * big if big * trend > 0 else 0
        else:
            x = W_BIG * big + W_TREND * trend
            x = 1.0 if x > 1 else -1.0 if x < -1 else x
            target = int(round(size * x))
        if SELF_GATE:
            sign = 1 if target > 0 else -1 if target < 0 else 0
            if sign != self._shadow_pos:
                step = sign - self._shadow_pos
                self._shadow_cash -= step * (best_ask if step > 0 else best_bid)
                self._shadow_pos = sign
            if self._shadow_cash + self._shadow_pos * mid <= GATE_TICKS:
                target = 0
        if SHADOW_SCALE:
            pnl = self._shadow_cash + self._shadow_pos * mid
            if self._last_us is not None:
                self._recent *= math.exp(-(now - self._last_us) / (SHADOW_S * 1e6))
            self._recent += pnl - self._shadow_pnl
            self._shadow_pnl = pnl
            self._last_us = now
            recent = self._recent
            if recent < 0:
                scale = 0.0
            elif recent < SHADOW_HALF:
                scale = 0.5
            elif recent < SHADOW_FULL:
                scale = 0.5 + 0.5 * (recent - SHADOW_HALF) / (SHADOW_FULL - SHADOW_HALF)
            else:
                scale = 1.0
            if scale < 1.0 and target != 0:
                self.n_scaled += 1
                target = int(round(target * scale))
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
