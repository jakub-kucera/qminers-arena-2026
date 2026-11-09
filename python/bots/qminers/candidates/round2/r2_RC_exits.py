"""R2-RC (7 Nov, round 2): R2-M3 (r2_M3_flow_stop_gated.py, its docstring below) plus three exits behind knobs; with
TRAIL 0, STOP_REVERSE 0, TIME_S 0 it is R2-M3 to the cent (130,251 on round 2's public tape, 2,052 fills). The pick, the
defaults here: STOP_REVERSE 1 alone (STOP 3, TRAIL 0, TIME_S 0, the REV_* knobs off): 141,002 on the public tape (in 75%
117,270 / out 25% 23,732 against M3's 107,499 / 22,752; 2,036 fills; breach 0; max drawdown 14,944 against 17,140), the
mirror the same to the cent, round1.csv -1,242 as M3 (the gate). The stop fired 64 times; the gain is the cascades the
stop-out starts: +10,396 of the +10,751 in 2,000-2,500 s (one 2-s window at 2,467-2,469 s +5.4k where M3 sat flat),
elsewhere a wash (500-s segments: ahead in 6 of 12, t 0.99). Every TRAIL 4-30, with or without the stop or the reverse,
is below off; TIME_S 10 costs 1-2.5k and 3-5 s destroys the hold (big orders come every ~2 s, a 30-s gap never);
REV_STOP 2-10, REV_POS 50, REV_MAX_S 2-10 and REV_CROSS 1-2 are all below the plain reverse. Without the self-gate the
reverse adds the same (132,005 -> 142,302). The grids: logs/RC_grid1..10.csv.
- TRAIL > 0: a trailing stop. Flat (as the STOP: one IOC at the touch, no new target until the next big order) once the
  mid has given back TRAIL ticks from the best mid reached in the signal's direction since the big signal was set; the
  STOP measures from the signal's mid instead, so a winner that has run on is let run until it gives TRAIL back. Both
  can be on; the one that fires first stops. The high-water mark is tracked from the signal's setting, position or not,
  and the stop checks only while the bot holds a position, as the STOP does.
- STOP_REVERSE 1: after a stop (STOP's or TRAIL's) the real target is the opposite side at MAX_POS instead of 0, until
  the next big order resets the signal, and only while the self-gate is open (the gate is R2-M3's, untouched).
- TIME_S > 0: a time stop. The real target is 0 once no big order has come for TIME_S seconds (the position is always
  on the side of the last big order, so that is the position's side's last one); the next big order sets it again.
  Acts last, after the gate, the stop and the reverse.
Grid and results: the report of 7 Nov (data/arena/round2/CANDIDATES.md, "Trials").

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
TRAIL = 0  # > 0: flat once the mid has given back this many ticks from its best since the big signal was set
STOP_REVERSE = 1  # 1: after a stop, hold MAX_POS the other way until the next big order instead of staying flat
TIME_S = 0  # > 0: flat once no big order has come for this many seconds, until the next one
REV_STOP = 0  # > 0, with STOP_REVERSE: flat once the mid has moved this many ticks against the reversed position since the stop
REV_POS = 100  # with STOP_REVERSE: the reversed position's size in lots (at most MAX_POS)
REV_MAX_S = 0  # > 0, with STOP_REVERSE: reverse only when the stop fired within this many seconds of the signal's setting, else flat
REV_CROSS = 0  # > 0, with STOP_REVERSE: ticks through the touch for the reverse's IOCs instead of CROSS


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
        self._best_adv = 0.0  # the best big * mid since the big signal was set (TRAIL)
        self._stopped = False  # the stop has fired: flat (or reversed) until the next big order
        self._taker_id = None
        self._shadow_pos = 0
        self._shadow_cash = 0.0
        self._big_set_us = 0  # when the big signal was set (REV_MAX_S)
        self._rev_mid = 0.0  # the mid when the stop fired (REV_STOP)
        self._rev_stopped = False  # the reversed position's own stop has fired: flat until the next big order
        self._rev_ok = True  # the stop fired soon enough after the signal to reverse (REV_MAX_S)
        self.stop_fired = 0  # counts, for the report
        self.trail_fired = 0
        self.time_fired = 0
        self.rev_fired = 0

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
        if net >= MIN_LOTS:
            if self._big != 1 or self._stopped:
                self._big_mid = mid
                self._best_adv = mid
                self._big_set_us = now
                self._stopped = False
            self._big = 1
            self._big_us = now
        elif net <= -MIN_LOTS:
            if self._big != -1 or self._stopped:
                self._big_mid = mid
                self._best_adv = -mid
                self._big_set_us = now
                self._stopped = False
            self._big = -1
            self._big_us = now
        big = self._big
        if HOLD_MS > 0 and now - self._big_us > HOLD_MS * 1000:
            big = 0
        if TRAIL > 0 and self._big != 0 and self._big * mid > self._best_adv:
            self._best_adv = self._big * mid

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
        gate_open = True
        if SELF_GATE:
            sign = 1 if target > 0 else -1 if target < 0 else 0
            if sign != self._shadow_pos:
                step = sign - self._shadow_pos
                self._shadow_cash -= step * (best_ask if step > 0 else best_bid)
                self._shadow_pos = sign
            if self._shadow_cash + self._shadow_pos * mid <= GATE_TICKS:
                target = 0
                gate_open = False
        if STOP > 0 or TRAIL > 0:
            if not self._stopped and self._big != 0 and self._pos != 0:
                if STOP > 0 and self._big * (self._big_mid - mid) >= STOP:
                    self._stopped = True
                    self.stop_fired += 1
                elif TRAIL > 0 and self._best_adv - self._big * mid >= TRAIL:
                    self._stopped = True
                    self.trail_fired += 1
                if self._stopped:
                    self._rev_mid = mid
                    self._rev_stopped = False
                    self._rev_ok = REV_MAX_S <= 0 or now - self._big_set_us <= REV_MAX_S * 1000000
            if self._stopped:
                if STOP_REVERSE and gate_open and self._rev_ok and not self._rev_stopped:
                    if REV_STOP > 0 and self._pos != 0 and self._big * (mid - self._rev_mid) >= REV_STOP:
                        self._rev_stopped = True
                        self.rev_fired += 1
                    target = 0 if self._rev_stopped else -self._big * min(REV_POS, MAX_POS)
                else:
                    target = 0
        if TIME_S > 0 and now - self._big_us >= TIME_S * 1000000:
            if target != 0 and self._pos != 0:
                self.time_fired += 1
            target = 0
        if self._taker_id is not None:
            return
        want = target - self._pos
        cross = REV_CROSS if REV_CROSS > 0 and self._stopped and target != 0 else CROSS
        if want >= MIN_CHANGE or (want > 0 and target == MAX_POS):
            self._taker_id = self._send(1, best_ask + cross, want)
        elif -want >= MIN_CHANGE or (want < 0 and target == -MAX_POS):
            self._taker_id = self._send(-1, best_bid - cross, -want)

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
