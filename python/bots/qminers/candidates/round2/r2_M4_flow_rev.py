"""R2-M4 (7 Nov, round 2, the fable worktree): R2-RA (the flow-window signal on R2-M3: the net market-taker lots over FLOW_MS 250 ms, MIN_LOTS 500) plus R2-RC's stop-and-reverse (STOP_REVERSE 1: after the 3-tick stop the real target is the OTHER side at MAX_POS until the next big signal, instead of flat; a move of 3 ticks against the last big order is itself the new momentum). Each alone on round 2 public: the window 165,459 (in 136,152 / out 29,307), the reverse 141,002 (in 117,270 / out 23,732), against R2-M3's 130,251 (107,499 / 22,752). STOP_REVERSE 0 is R2-RA exactly. RA's notes follow.
R2-RA (7 Nov, round 2): R2-M3 (r2_M3_flow_stop_gated.py, below) with the big signal's trigger generalised to a flow
window. FLOW_MS > 0: the signal fires toward the side whose net signed market-taker lots over the last FLOW_MS
milliseconds (bought lots minus sold lots across every aggressive order in the window, one call's net being one
order) reach MIN_LOTS, so three 200-lot buys within half a second count like one 600-lot buy. SQRT 1 weights each
order's lots by sqrt(lots / SQRT_REF) before the window sum (a 2,000-lot order counts 2x, a 125-lot order 0.5x; a
500-lot order 1x, so MIN_LOTS keeps its meaning). CONSUME 1 clears the window when the signal fires, so a flip or a
re-arm after the stop needs MIN_LOTS of fresh flow, as the base's needs a fresh big order; CONSUME 0 keeps the
window, and the signal re-fires on every aggressive order while the window's net is past MIN_LOTS. A fire needs an
aggressive order in the call (the window's net cannot cross the threshold by expiry alone). FLOW_MS 0 is R2-M3
exactly (130,251 on round 2's public tape, to the cent; SQRT 1 with MIN_LOTS 500 there too, the weight being 1 at
500 lots and monotonic). The firings are counted on the instance (_fires, _multi_fires: fires whose window held more
than one order, _arms: fires that changed the side or re-armed after a stop).
Round 2's public tape, chosen on the first 75% (`--grid FLOW_MS=0,250,500,1000,2000 --grid MIN_LOTS=500,800`, then
FLOW_MS=50,100,150,200,350 at MIN_LOTS 500, then `--grid SQRT=0,1 --grid MIN_LOTS=400,500,650 --grid FLOW_MS=150,250`,
all `--holdout 0.25`), MIN_LOTS 500, SQRT 0, CONSUME 1: FLOW_MS 250 165,459 (in 136,152 / out 29,307; 2,704 fills,
384,300 lots, breach 0, max drawdown 14,844 against R2-M3's 17,140), 150 165,480 (130,652 / 34,828), 100 164,037
(127,100 / 36,937), 200 159,827 (127,312 / 32,515), 350 147,480 (125,877 / 21,603), 50 147,452 (115,159 / 32,293),
500 136,466 (112,950 / 23,516), 0 130,251 (107,499 / 22,752), 1000 119,034 (108,039 / 10,995), 2000 81,400 (71,878 /
9,522). MIN_LOTS 800 below 500 at every window (250: 93,242), 400 and 650 below it on the first 75% at 150 and 250
(400 / 250: 139,708, in 123,645; 650 / 250: 159,782, in 116,455, out 43,327). SQRT 1 below SQRT 0 in every cell (500 /
250: 129,902, in 107,325). CONSUME 0 at 250: 161,665 (in 133,680), at 500: 118,818. The mirrored public tape 165,459
with 2,704 fills, to the cent. 500-s segments against R2-M3: ahead in 8 of 12, mean +2,934, t 1.18, worst -13,232
(segment 4, 2,168 against 15,400). Firings on the public tape: 3,956 (3,422 with more than one order in the window,
1,936 changed the side or re-armed after a stop) against R2-M3's 2,813 (1,427). Round 1's tapes not run.
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
STOP_REVERSE = 0  # 1: after a stop, hold MAX_POS the other way until the next big signal instead of staying flat
STOP = 3  # > 0: flat once the mid has moved this many ticks against the position since the big signal was set


class FlowTrendStrategy(BaseStrategy):
    """Hold MAX_POS lots the way of the recent big aggressive flow and/or the minute-scale trend."""

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
        gate_closed = False
        if SELF_GATE:
            sign = 1 if target > 0 else -1 if target < 0 else 0
            if sign != self._shadow_pos:
                step = sign - self._shadow_pos
                self._shadow_cash -= step * (best_ask if step > 0 else best_bid)
                self._shadow_pos = sign
            if self._shadow_cash + self._shadow_pos * mid <= GATE_TICKS:
                target = 0
                gate_closed = True
        if STOP > 0:
            if not self._stopped and self._big != 0 and self._pos != 0 and self._big * (self._big_mid - mid) >= STOP:
                self._stopped = True
            if self._stopped:
                target = -self._big * MAX_POS if (STOP_REVERSE and not gate_closed) else 0
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
