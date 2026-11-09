"""R2-RF (7 Nov, round 2, the fable worktree): R2-M3 plus R2-E2's online ridge forecast of the 400-ms mid move, used only
to time exits and re-entries. The model is r2_E2_low_exposure_keep.py's (R1-C12's), copied: 29 causal book and flow
features from the public feed, an observation every 20 ms labelled with the mid move 400 ms later, exponentially decayed
sums (MODEL_MEMORY_US) and a ridge fit (Gauss-Jordan) every second once MIN_LABELS (200) labels are in. It learns on the
tape it trades, nothing is pre-fitted, and its forecast (clipped to +-2 ticks) is unavailable until then: the rules below
do nothing without it. Three knobs, each 0 = off; at 0/0/0 the file is R2-M3 to the cent (130,251 on round 2's public
tape; the model still runs, it only costs time):
- PRED_STOP (ticks): while the bot holds a position on the big signal's side, a forecast beyond PRED_STOP against it
  flattens the position by one IOC at the touch, and the bot stays flat until the next big order of MIN_LOTS lots (the
  3-tick stop's `_stopped` rule, checked right after it);
- PRED_ENTER (ticks): a move towards a non-zero target (an entry, a re-entry after a stop, a flip) waits while the
  forecast disagrees with the target's side by more than PRED_ENTER (the target becomes the position held), and goes as
  soon as the forecast agrees or is within the band;
- PRED_FLIP (ticks): a forecast beyond PRED_FLIP against the held side flips the big signal (big, big_mid, the stop's
  reference, as a big order the other way would) without waiting for one: the stop's cousin on the other side. It is
  checked where the big orders are, before the stops, so with both on a forecast beyond PRED_FLIP flips and one between
  PRED_STOP and PRED_FLIP stops.
The self-gate, the stop and the position accounting are R2-M3's untouched (the shadow follows the big signal, forecast
flips included). The counters `_fired` (forecast stops, entry delays and their microseconds, forecast flips) are for the
report only. Numbers: see IDEAS.md.
R2-M3's notes follow.
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
from math import exp, isfinite

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
PRED_STOP = 0.0  # > 0: flat (until the next big order) once the forecast is this far against the held side
PRED_ENTER = 0.0  # > 0: an entry waits while the forecast is more than this against the target's side
PRED_FLIP = 0.0  # > 0: flip the big signal once the forecast is this far against the held side

# The forecast model (R2-E2's, R1-C12's): the 400-ms mid move from 29 features, ridge-fitted online.
FEATURE_COUNT = 29
HORIZON_US = 400000
OBSERVATION_INTERVAL_US = 20000
MIN_LABELS = 200
MODEL_MEMORY_US = 100000000000


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
        self._fired = [0, 0, 0, 0]  # forecast stops, entry delays (episodes), delayed microseconds, forecast flips
        self._delay_since = None
        # The forecast model's state (R2-E2's).
        self._known_market = {}
        self._new_counts = [0.0] * 4
        self._new_values = [0.0] * 4
        self._cancel_net = self._cancel_mass = 0.0
        self._new_quote_time = None
        self._second_group_net = [0.0, 0.0, 0.0]
        self._second_group_volume = [0.0, 0.0, 0.0]
        self._second_group_price = [0.0, 0.0, 0.0]
        self._second_rest_count_net = self._second_rest_count = 0.0
        self._observations = deque(maxlen=64)
        self._last_observation_us = -100000
        self._last_fit_us = None
        self._last_label_us = None
        self._labels = 0
        self._mass = 0.0
        self._xx = [[0.0] * FEATURE_COUNT for _ in range(FEATURE_COUNT)]
        self._xy = [0.0] * FEATURE_COUNT
        self._weights = [0.0] * FEATURE_COUNT
        self._fast_mid = self._slow_mid = None
        self._model_time = None
        self._ofi = 0.0
        self._ofi_time = None
        self._previous_touch = None
        self._last_us = None
        self._net = self._volume = 0.0

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

    # ------------------------------------------------------------------ the forecast model (R2-E2's code)

    def _learn(self, now, mid):
        # Labels mature strictly after observation + horizon. Large gaps
        # are discarded instead of silently changing the prediction horizon.
        while self._observations and self._observations[0][0] + HORIZON_US <= now:
            observed_us, old_mid, features = self._observations.popleft()
            if now - observed_us > HORIZON_US + 1_000_000:
                continue
            elapsed = 0 if self._last_label_us is None else now - self._last_label_us
            decay = exp(-max(0, elapsed) / MODEL_MEMORY_US)
            self._last_label_us = now
            response = max(-20.0, min(20.0, mid - old_mid))
            self._mass = self._mass * decay + 1.0
            for i in range(FEATURE_COUNT):
                self._xy[i] = self._xy[i] * decay + features[i] * response
                for j in range(FEATURE_COUNT):
                    self._xx[i][j] = self._xx[i][j] * decay + features[i] * features[j]
            self._labels += 1
        if self._labels < MIN_LABELS:
            return
        if self._last_fit_us is not None and now - self._last_fit_us < 1_000_000:
            return
        self._last_fit_us = now
        # Tiny positive-definite system; ridge protects near-constant or
        # correlated features. Solving here avoids per-event numpy overhead.
        ridge = max(10.0, 0.001 * self._mass)
        matrix = [self._xx[i][:] + [self._xy[i]] for i in range(FEATURE_COUNT)]
        for i in range(FEATURE_COUNT):
            matrix[i][i] += ridge
        for col in range(FEATURE_COUNT):
            pivot = matrix[col][col]
            if not isfinite(pivot) or pivot <= 1e-12:
                return
            for j in range(col, FEATURE_COUNT + 1):
                matrix[col][j] /= pivot
            for i in range(FEATURE_COUNT):
                if i == col:
                    continue
                factor = matrix[i][col]
                for j in range(col, FEATURE_COUNT + 1):
                    matrix[i][j] -= factor * matrix[col][j]
        weights = [matrix[i][FEATURE_COUNT] for i in range(FEATURE_COUNT)]
        if all(isfinite(w) for w in weights):
            self._weights = weights

    def _forecast(self, snapshot, trades, now):
        """R2-E2's feature update, learning and prediction on this book event; None until MIN_LABELS labels are in
        (or when the book has no valid touch). The forecast is the 400-ms mid move in ticks, clipped to +-2."""
        elapsed = 0 if self._last_us is None else max(0, now - self._last_us)
        self._last_us = now
        second_group_decay = exp(-elapsed / 1000000)
        for i in range(3):
            self._second_group_net[i] *= second_group_decay
            self._second_group_volume[i] *= second_group_decay
            self._second_group_price[i] *= second_group_decay
        self._second_rest_count_net *= second_group_decay
        self._second_rest_count *= second_group_decay
        if trades:
            visible = {o.order_id: o for orders in (snapshot.bids, snapshot.asks) for o in orders if o.owner == 'market'}
            arrivals = {}
            for trade in trades:
                if trade.taker_owner != 'market':
                    continue
                row = arrivals.setdefault(trade.taker_order_id, [1 if trade.book_side == 'ask' else -1, 0, 0.0, 0, 0.0])
                row[1] += trade.quantity
                row[2] += trade.quantity * trade.price
                if trade.maker_owner == 'user':
                    row[3] += trade.quantity
                    row[4] += trade.quantity * trade.price
            for oid, row in arrivals.items():
                direction, quantity, value, own, own_value = row
                group = 0 if oid in visible else 1
                price = visible[oid].price if group == 0 else value / max(1, quantity)
                quantity += visible[oid].quantity if group == 0 else 0
                weight = min(20, quantity)
                self._second_group_net[group] += direction * weight
                self._second_group_volume[group] += weight
                self._second_group_price[group] += weight * price
                if group == 0:
                    self._second_rest_count_net += direction
                    self._second_rest_count += 1
                if own:
                    weight = min(20, own)
                    self._second_group_net[2] += direction * weight
                    self._second_group_volume[2] += weight
                    self._second_group_price[2] += weight * own_value / own
        decay = exp(-elapsed / 500_000)
        self._net *= decay
        self._volume *= decay
        for trade in trades:
            if trade.taker_owner == 'market':
                self._net += trade.quantity if trade.book_side == 'ask' else -trade.quantity
                self._volume += trade.quantity
        # The market's touch and its quantity on each side (E2 scans the same way, with its queue bookkeeping).
        bid = ask = None
        bq = aq = 0
        for orders in (snapshot.bids, snapshot.asks):
            for order in orders:
                if order.owner != 'market':
                    continue
                if order.side == Side.BUY:
                    if bid is None:
                        bid = order.price
                    if order.price == bid:
                        bq += order.quantity
                    else:
                        break
                else:
                    if ask is None:
                        ask = order.price
                    if order.price == ask:
                        aq += order.quantity
                    else:
                        break
        if bid is None or ask is None or bid >= ask:
            self._previous_touch = None
            return None
        dt = 0 if self._new_quote_time is None else max(0, now - self._new_quote_time)
        self._new_quote_time = now
        decay_new = exp(-dt / 500000)
        for i in range(4):
            self._new_counts[i] *= decay_new
            self._new_values[i] *= decay_new
        self._cancel_net *= decay_new
        self._cancel_mass *= decay_new
        current = {o.order_id: o for orders in (snapshot.bids, snapshot.asks) for o in orders if o.owner == 'market'}
        for oid, order in current.items():
            if oid in self._known_market:
                continue
            distance = bid - order.price if order.side == Side.BUY else order.price - ask
            if distance > 3:
                continue
            index = 0 if order.side == Side.BUY else 1
            self._new_counts[index] += 1
            self._new_values[index] += order.price
            if order.quantity <= 50:
                self._new_counts[index + 2] += 1
                self._new_values[index + 2] += order.price
        traded = {t.maker_order_id for t in trades if t.maker_owner == 'market'}
        for oid, order in self._known_market.items():
            if oid in current or oid in traded:
                continue
            distance = bid - order.price if order.side == Side.BUY else order.price - ask
            if abs(distance) > 3:
                continue
            self._cancel_net += -1 if order.side == Side.BUY else 1
            self._cancel_mass += 1
        self._known_market = current
        mid = (bid + ask) * 0.5
        spread = ask - bid
        flow = self._net / (1 + self._volume)
        imbalance = (bq - aq) / (bq + aq)
        bn = an = bd_n = ad_n = 0
        br = ar = bd_r = ad_r = 0
        bd_value = ad_value = 0
        for orders in (snapshot.bids, snapshot.asks):
            for order in orders:
                if order.owner != 'market':
                    continue
                distance = bid - order.price if order.side == Side.BUY else order.price - ask
                if distance > 2:
                    break
                weight = min(20, order.quantity)
                if order.side == Side.BUY:
                    bd_n += 1
                    bd_r += weight
                    bd_value += weight * order.price
                    if distance == 0:
                        bn += 1
                        br += weight
                else:
                    ad_n += 1
                    ad_r += weight
                    ad_value += weight * order.price
                    if distance == 0:
                        an += 1
                        ar += weight
        count_imbalance = (bn - an) / max(1, bn + an)
        robust_imbalance = (br - ar) / max(1, br + ar)
        depth_count = (bd_n - ad_n) / max(1, bd_n + ad_n)
        depth_imbalance = (bd_r - ad_r) / max(1, bd_r + ad_r)
        depth_mid = (bd_value / max(1, bd_r) + ad_value / max(1, ad_r)) * 0.5 - mid

        if self._model_time is None or now - self._model_time > 10000000:
            self._fast_mid = self._slow_mid = mid
            self._observations.clear()
        else:
            dt = max(0, now - self._model_time)
            self._fast_mid += (1 - exp(-dt / 500000)) * (mid - self._fast_mid)
            self._slow_mid += (1 - exp(-dt / 2000000)) * (mid - self._slow_mid)
        self._model_time = now
        dt = 0 if self._ofi_time is None else max(0, now - self._ofi_time)
        self._ofi_time = now
        self._ofi *= exp(-dt / 500000)
        if self._previous_touch is not None:
            old_bid, old_ask, old_bq, old_aq = self._previous_touch
            change = (bq if bid >= old_bid else 0) - (old_bq if bid <= old_bid else 0)
            change -= (aq if ask <= old_ask else 0)
            change += (old_aq if ask >= old_ask else 0)
            self._ofi += change / max(1, bq + aq, old_bq + old_aq)
        self._previous_touch = (bid, ask, bq, aq)
        ofi = max(-3, min(3, self._ofi))
        features = (flow, max(-5, min(5, self._fast_mid - self._slow_mid)), imbalance,
                    ofi, spread * imbalance, flow * abs(flow), imbalance * abs(imbalance), ofi * abs(ofi), count_imbalance, robust_imbalance, depth_count, depth_imbalance, depth_mid, count_imbalance * abs(count_imbalance), robust_imbalance * abs(robust_imbalance), (self._new_counts[0] - self._new_counts[1]) / (1 + self._new_counts[0] + self._new_counts[1]),
                    max(-5, min(5, ((self._new_values[0] - mid * self._new_counts[0]) / (1 + self._new_counts[0]) + (self._new_values[1] - mid * self._new_counts[1]) / (1 + self._new_counts[1])) * 0.5)),
                    max(-5, min(5, ((self._new_values[2] - mid * self._new_counts[2]) / (1 + self._new_counts[2]) + (self._new_values[3] - mid * self._new_counts[3]) / (1 + self._new_counts[3])) * 0.5)),
                    self._cancel_net / (1 + self._cancel_mass),
                    max(-5, min(5, (self._new_values[0] + self._new_values[1] - mid * (self._new_counts[0] + self._new_counts[1])) / (1 + self._new_counts[0] + self._new_counts[1]))),
                    (self._new_counts[2] - self._new_counts[3]) / (1 + self._new_counts[2] + self._new_counts[3]))
        features += (self._second_group_net[0] / (1 + self._second_group_volume[0]),
                     self._second_group_net[1] / (1 + self._second_group_volume[1]),
                     self._second_group_net[2] / (1 + self._second_group_volume[2]),
                     self._second_group_volume[0] / (1 + self._second_group_volume[0] + self._second_group_volume[1]),
                     max(-5, min(5, (self._second_group_price[0] - mid * self._second_group_volume[0]) / (1 + self._second_group_volume[0]))),
                     max(-5, min(5, (self._second_group_price[1] - mid * self._second_group_volume[1]) / (1 + self._second_group_volume[1]))),
                     max(-5, min(5, (self._second_group_price[2] - mid * self._second_group_volume[2]) / (1 + self._second_group_volume[2]))),
                     self._second_rest_count_net / (1 + self._second_rest_count))
        self._learn(now, mid)
        if now - self._last_observation_us >= OBSERVATION_INTERVAL_US:
            self._observations.append((now, mid, features))
            self._last_observation_us = now
        if self._labels < MIN_LABELS:
            return None
        return max(-2.0, min(2.0, sum(w * x for w, x in zip(self._weights, features))))

    # ------------------------------------------------------------------ R2-M3's path, the forecast rules added

    def on_order_book_change(self, snapshot: OrderBookSnapshot, trades: list[Trade]) -> None:
        now = snapshot.timestamp_us
        if self._start_us is None:
            self._start_us = now
        pred = self._forecast(snapshot, trades, now)  # always learning; the rules read it only when on
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
                self._stopped = False
            self._big = 1
            self._big_us = now
        elif net <= -MIN_LOTS:
            if self._big != -1 or self._stopped:
                self._big_mid = mid
                self._stopped = False
            self._big = -1
            self._big_us = now
        elif (PRED_FLIP > 0 and pred is not None and not self._stopped and self._big * self._pos > 0
              and -self._big * pred >= PRED_FLIP):
            # The forecast against the held side flips the big signal, as a big order the other way would.
            self._big = -self._big
            self._big_mid = mid
            self._big_us = now
            self._fired[3] += 1
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
        if PRED_STOP > 0 and pred is not None:
            if not self._stopped and self._big * self._pos > 0 and -self._big * pred >= PRED_STOP:
                self._stopped = True
                self._fired[0] += 1
            if self._stopped:
                target = 0
        if PRED_ENTER > 0:
            delaying = False
            if pred is not None and target != 0:
                side = 1 if target > 0 else -1
                if side * self._pos < MAX_POS and -side * pred > PRED_ENTER:
                    target = self._pos
                    delaying = True
            if delaying:
                if self._delay_since is None:
                    self._delay_since = now
                    self._fired[1] += 1
            elif self._delay_since is not None:
                self._fired[2] += now - self._delay_since
                self._delay_since = None
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
