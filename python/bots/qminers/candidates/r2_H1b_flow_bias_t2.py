"""R2-H1b (7 Nov, round 2): R2-H1's bias on R2-T2's code (the hybrid agent's final, commit 6918af5) instead of R2-T1's; not uploaded. R2-H1 (r2_H1_flow_bias.py, the T1-based version) is the one that scored +567,739.71 on validation. The notes follow.

R2-H1 (7 Nov, round 2): R2-T2 (r2_T2_take_only_safe.py: R2-T1's online ridge forecast take with its breach fixes,
TAKE_ROOM_LIVE 1 and CANCEL_FREE 0.0) biased by R2-RA's big-flow signal (r2_RA_flow_window.py). RA's state is kept
beside the ridge as RA keeps it: the side of the last window of FLOW_MS ms whose net market-taker lots reached
MIN_LOTS (the window cleared when it fires), a one-lot shadow holding that side whose PnL since the start must be
above GATE_TICKS (the self-gate, which stays shut on calm tapes), and a stop that drops the signal once the mid has
moved STOP ticks against it since it was set (until the next fire; checked while the gate is open). While the gated,
unstopped signal says +1 (-1), the take's threshold toward it is lowered by BIAS_AGREE ticks and the one against it
raised by BIAS_AGAINST (each side's own threshold: buy when the forecast beats need_buy, sell when it is under
-need_sell). BIAS_AGREE 0 / BIAS_AGAINST 0 is the base exactly (R2-T1 to the cent with TAKE_ROOM_LIVE 0 and
CANCEL_FREE 1.0, on a 410-s cut of the public tape); a large BIAS_AGREE is RA's hold taken by the base's takes (at most
TAKE_SZ lots every TAKE_GAP_MS while the spread is at most TAKE_MAXSPREAD), with the forecast in charge whenever the
signal is off. AGREE_MAXSPREAD > TAKE_MAXSPREAD lets the take toward the signal fire at wider spreads; FEAT_BIG 1 gives
the ridge the gated signal as a 30th feature (0 while the gate is shut, so the fit is the base's there).
Set: BIAS_AGREE 0.3, BIAS_AGAINST 0. Chosen on round 2's public tape on the T1 base (this file at commit 015c3c8,
`uv run python -m arena.qgrid FILE data/arena/round2/round2_public.csv --set ROOM_RESERVED=0 --grid
BIAS_AGREE=0.15,0.3,0.6,9 --grid BIAS_AGAINST=0,0.3,9`, on the first 75%; T1 191,984, in 135,839 / out 56,145; at
015c3c8 the T2 base's room fix was ROOM_RESERVED 1, with 223,794, in 164,498 / out 59,296): 0.3 / 0 207,065 (157,308 / 49,757), 0.15 / 0
211,585 (154,798 / 56,788), 0.3 / 0.3 203,398, 0.6 / 0 181,116, 9 / 9 (RA's hold inside T1) 181,855, 9 / 0 146,540;
single runs 0.2 / 0 227,828, 0.45 / 0 196,721; AGREE_MAXSPREAD 99 at 9 / 0.6 124,147; FEAT_BIG 1 with no bias 181,858.
This file, per tape (H1 / T2 / T1 / RA; `uv run exchange-simulator --strategy FILE --backtest CSV --log-dir logs/x
--no-logs`): round2_public 223,773 / 194,391 / 191,984 / 165,459; its mirror 223,586 / 192,774 / 187,246 / 165,459;
round1 171,176 / 171,802 / 164,194 / -527; the stitched 12,000-s tapes of `experiments.tape.tape_character stitch`
(IDEAS.md, "Why R2-E2 lost"): high-vol half x4 569,111 / 495,028 / 514,873 / 510,494, public twice 466,113 / 423,096 /
421,081 / 338,278, high-vol half 1.25x faster 608,688 / 550,352 / 547,196 / 562,176. Breach 0 on every tape. Ahead of
T1, T2 and RA on every round-2 tape; round 1 626 under T2 (the gate opens briefly there). The T1 base with only the
take's room fix (no bias) is 182,966 on the public, 510,027 on the high-vol half, 568,827 on its 1.25x: the gain is
the bias's. R2-T2's and R2-T1's notes follow.
R2-T2 (7 Nov, round 2): R2-T1 without its position breaches: the take's room is EXPOSURE - pos - every live same-side
order's lots (TAKE_ROOM_LIVE 1), and an order being cancelled counts in full toward EXPOSURE until the cancel lands
(CANCEL_FREE 0.0). Numbers: IDEAS.md, the R2-T2 row.
R2-T1 (7 Nov, round 2, the fable worktree): the forecast take ALONE. R2-E2's file (R1-C12's online ridge of the 400-ms mid move on 29 features, a forecast take, queue keeping) with its quoting reduced to one lot (QUOTE_SIZE 1), EXPOSURE 100, TAKE_EDGE 0.15, TAKE_SZ 200, TAKE_GAP_MS 50, and a new module knob TAKE_MAXSPREAD (the take fires only while the spread is at most this many ticks; 99: off). Why: on round 2's public tape the same model quoting makes -87,574 while its take alone makes 185,818 (first 75% 122,759, last 25% 63,059: the best held-out figure of any candidate), 142,017 on round 1 and 335-363k on the drift-free draws (`arena.qsim_rust ridge_maker ... --set QUOTE_SIZE=1`, the grid in CANDIDATES.md); forecast_quality on this tape: at a 1-tick spread a prediction of 0.75-1.25 ticks is followed by a 1.1-1.6 tick move in 0.4 s (net of the half spread +0.6 to +1.1, hit 72-75%), at a 2+ tick spread the net is negative in every bin (-0.4 to -2.6), which the spread gate removes. E2's notes follow.
R2-E2: R2-E1 (r2_E1_low_exposure.py) plus R2-Q1's queue keeping (r2_Q1_keep_slice.py), for round 2.

R2-E1 is R2-FT1 (R1-C12's online ridge of the 400-ms mid move on 29 causal
microstructure features, quoted as a market maker, plus a forecast take) with
its literals as named constants (EXPOSURE: the lots the quoting, the skew, the
withdrawal, the take and the hedge aim at; POSITION_LIMIT stays the 1,000 wall).
Added from R2-Q1, one rule in `_quote`: an accepted order resting at the
market's touch that the quoting would cancel (the forecast stepped back into
the dead zone, or turned inside) is not cancelled while the forecast toward its
side (fair before the dead zone, minus the mid, signed) is at least -KEEP_TH;
it is shrunk by modify_order to KEEP_LOTS instead, which keeps its place in the
queue, and the side's room behind it is posted as before. A kept slice counts
its target lots toward EXPOSURE while the modify is in flight. Records are
[sign, price, lots, accepted, cancelling, sent, exempt_until, modify_target].
Set for round 2: EXPOSURE 30, DEAD_ZONE 0.18, KEEP_LOTS 20, KEEP_TH 0.3.
The Rust twin: ridge_maker (rust/arena_sim/src/strategies/ridge_maker.rs)
--set POSITION_LIMIT=1000 --set CANCEL_FREE=1.0 --set HEDGE=1
--set MODEL_MEMORY_US=100000000000 --set HORIZON_US=400000 --set QUOTEFEAT=1
--set FLOWGRP=2 --set FLOWGRP_CAP=20 --set FLOWGRP_US=1000000 --set FT_SZ=200
--set FT_GAP_MS=50 --set SKEW_K=0.025 --set FT_EDGE=0.25 --set QUOTE_SIZE=200
--set EXPOSURE=30 --set DEAD_ZONE=0.18 --set KEEP_LOTS=20 --set KEEP_TH=0.3.
Numbers: see IDEAS.md.
"""
from collections import deque
from math import exp, ceil, floor, isfinite

from simulator.models import OrderRequest, OrderStatus, OrderType, Side
from simulator.strategy import BaseStrategy

TAKE_MAXSPREAD = 1  # the forecast take fires only while the spread is at most this many ticks (99: no limit)
BIAS_AGREE = 0.3  # ticks off the take's threshold toward the gated big-flow signal
BIAS_AGAINST = 0  # ticks onto the take's threshold against it
AGREE_MAXSPREAD = 1  # while the signal is on, the take toward it fires up to this spread (T1's gate: TAKE_MAXSPREAD)
TAKE_ROOM_LIVE = 1  # R2-T2: the take's room is EXPOSURE - pos - every live same-side order's lots (0: R2-T1, EXPOSURE - pos)
FEAT_BIG = 0  # 1: the gated big-flow signal is also the ridge's 30th feature
MIN_LOTS = 500  # R2-RA: the window's net market-taker lots that set the big signal
FLOW_MS = 250  # R2-RA: the window
SELF_GATE = 1  # R2-RA: the signal counts only while its one-lot shadow is up more than GATE_TICKS since the start
GATE_TICKS = 10
STOP = 3  # R2-RA: the signal drops once the mid has moved this many ticks against it since it was set (0: off)


class PassiveStrategy(BaseStrategy):
    FEATURE_COUNT = 29
    HORIZON_US = 400000
    OBSERVATION_INTERVAL_US = 20000
    MIN_LABELS = 200
    MODEL_MEMORY_US = 100000000000
    POSITION_LIMIT = 1000
    QUOTE_SIZE = 1
    REQUOTE_US = 0
    EXPOSURE = 100
    DEAD_ZONE = 0.18     # R2-E1: 0.3
    INSIDE_TH = 0.3
    SKEW_K = 0.025
    FLOW_CUT = 1.1
    CANCEL_FREE = 0.0    # R2-T2: an order being cancelled counts in full toward EXPOSURE until the cancel lands (R2-T1: 1.0, free)
    HEDGE_TICKS = 10
    HEDGE_STALE_US = 100000
    TAKE_EDGE = 0.15
    TAKE_SZ = 200
    TAKE_GAP_MS = 50
    TAKE_MODE = 0   # 0 any, 1 only to reduce, 2 only to open or add
    TAKE_INV = 0    # TAKE_MODE 1: the least |inventory| to reduce
    TAKE_THRU = 0
    KEEP_LOTS = 20  # 0: off (R2-E1)
    KEEP_TH = 0.3

    def __init__(self):
        super().__init__()
        self.FEATURE_COUNT = 30 if FEAT_BIG else 29
        self.inventory = 0
        self.cash = 0
        self._orders = {}
        self._hedge_id = None
        self._cached_bid = self._cached_ask = self._cached_time = None
        self._known_market = {}
        self._new_counts = [0.0]*4
        self._new_values = [0.0]*4
        self._cancel_net = self._cancel_mass = 0.0
        self._new_quote_time = None
        self._second_group_net=[0.0,0.0,0.0]
        self._second_group_volume=[0.0,0.0,0.0]
        self._second_group_price=[0.0,0.0,0.0]
        self._second_rest_count_net=self._second_rest_count=0.0
        self._desired_buy = self._desired_sell = None
        self._desired_time = None
        self._observations = deque(maxlen=64)
        self._last_observation_us = -100000
        self._last_fit_us = None
        self._last_label_us = None
        self._labels = 0
        self._mass = 0.0
        self._xx = [[0.0] * self.FEATURE_COUNT for _ in range(self.FEATURE_COUNT)]
        self._xy = [0.0] * self.FEATURE_COUNT
        self._weights = [0.0] * self.FEATURE_COUNT
        self._fast_mid = self._slow_mid = None
        self._model_time = None
        self._ofi = 0.0
        self._ofi_time = None
        self._previous_touch = None

        self._last_action = {-1:-5000, 1:-5000}
        self._last_us = None
        self._net = self._volume = 0.0
        self._invalid_since = None
        self.queue_ahead = {}
        self._take_last = None
        self._qp_touch = {1: 0, -1: 0}
        self._qp_d = 0.0
        self._flow = deque()  # R2-RA's window: (time_us, one call's net market-taker lots)
        self._flow_sum = 0
        self._big = 0
        self._big_mid = 0.0
        self._stopped = False
        self._shadow_pos = 0
        self._shadow_cash = 0.0
        self._bias = 0

    def _learn(self, now, mid):
        # Labels mature strictly after observation + horizon. Large gaps
        # are discarded instead of silently changing the prediction horizon.
        while self._observations and self._observations[0][0] + self.HORIZON_US <= now:
            observed_us, old_mid, features = self._observations.popleft()
            if now - observed_us > self.HORIZON_US + 1_000_000:
                continue
            elapsed = 0 if self._last_label_us is None else now - self._last_label_us
            decay = exp(-max(0, elapsed) / self.MODEL_MEMORY_US)
            self._last_label_us = now
            response = max(-20.0, min(20.0, mid - old_mid))
            self._mass = self._mass * decay + 1.0
            for i in range(self.FEATURE_COUNT):
                self._xy[i] = self._xy[i] * decay + features[i] * response
                for j in range(self.FEATURE_COUNT):
                    self._xx[i][j] = self._xx[i][j] * decay + features[i] * features[j]
            self._labels += 1
        if self._labels < self.MIN_LABELS:
            return
        if self._last_fit_us is not None and now - self._last_fit_us < 1_000_000:
            return
        self._last_fit_us = now
        # Tiny positive-definite system; ridge protects near-constant or
        # correlated features. Solving here avoids per-event numpy overhead.
        ridge = max(10.0, 0.001 * self._mass)
        matrix = [self._xx[i][:] + [self._xy[i]] for i in range(self.FEATURE_COUNT)]
        for i in range(self.FEATURE_COUNT):
            matrix[i][i] += ridge
        for col in range(self.FEATURE_COUNT):
            pivot = matrix[col][col]
            if not isfinite(pivot) or pivot <= 1e-12:
                return
            for j in range(col, self.FEATURE_COUNT + 1):
                matrix[col][j] /= pivot
            for i in range(self.FEATURE_COUNT):
                if i == col:
                    continue
                factor = matrix[i][col]
                for j in range(col, self.FEATURE_COUNT + 1):
                    matrix[i][j] -= factor * matrix[col][j]
        weights = [matrix[i][self.FEATURE_COUNT] for i in range(self.FEATURE_COUNT)]
        if all(isfinite(w) for w in weights):
            self._weights = weights

    def _hedge(self, now):
        if abs(self.inventory) <= self.EXPOSURE or self._hedge_id is not None:
            return
        if self._cached_time is None or now-self._cached_time > self.HEDGE_STALE_US:
            return
        sign = -1 if self.inventory > 0 else 1
        reserved = sum(r[2] for r in self._orders.values() if r[0] == sign)
        quantity = min(abs(self.inventory)-self.EXPOSURE,max(0,self.POSITION_LIMIT-sign*self.inventory-reserved))
        if quantity <= 0:
            return
        price = self._cached_ask+self.HEDGE_TICKS if sign > 0 else max(1,self._cached_bid-self.HEDGE_TICKS)
        oid = self.send_order(OrderRequest(side=Side.BUY if sign > 0 else Side.SELL,
            price=price,quantity=quantity,order_type=OrderType.IOC))
        self._orders[oid] = [sign,price,quantity,False,False,now,0,0]
        self._hedge_id = oid

    def _take(self, now, signal, spread, bid, ask):
        bias = self._bias
        if spread > TAKE_MAXSPREAD and (bias == 0 or spread > AGREE_MAXSPREAD):
            return
        need = self.TAKE_EDGE + 0.5*spread
        need_buy = need - BIAS_AGREE if bias > 0 else need + BIAS_AGAINST if bias < 0 else need
        need_sell = need - BIAS_AGREE if bias < 0 else need + BIAS_AGAINST if bias > 0 else need
        if spread > TAKE_MAXSPREAD:  # past T1's spread gate only the take toward the signal fires
            if bias > 0:
                need_sell = 1e9
            else:
                need_buy = 1e9
        sign = 1 if signal > need_buy else -1 if signal < -need_sell else 0
        if sign == 0:
            return
        pos = sign*self.inventory
        if self.TAKE_MODE == 1:
            room = -pos if pos < 0 and -pos >= self.TAKE_INV else 0
        elif self.TAKE_MODE == 2:
            room = self.EXPOSURE-pos if pos >= 0 else 0
        else:
            room = self.EXPOSURE-pos
        reserved = sum(r[2] for r in self._orders.values() if r[0] == sign)
        if TAKE_ROOM_LIVE:
            room -= reserved  # R2-T2: every live same-side order (a one-lot quote, one being cancelled, the hedge) can fill first
        quantity = min(self.TAKE_SZ,room,self.POSITION_LIMIT-pos-reserved)
        if quantity <= 0:
            return
        price = ask+self.TAKE_THRU if sign > 0 else max(1,bid-self.TAKE_THRU)
        oid = self.send_order(OrderRequest(side=Side.BUY if sign > 0 else Side.SELL,
            price=price,quantity=quantity,order_type=OrderType.IOC))
        self._orders[oid] = [sign,price,quantity,False,False,now,now+1_000_000,0]
        self._take_last = now

    def _update_big(self, now, trades, bid, ask, mid):
        # R2-RA's big signal, self-gate and stop, as RA computes them; the result is self._bias (-1, 0, +1).
        net = 0
        for trade in trades:
            if trade.taker_owner == 'market':
                net += trade.quantity if trade.book_side == 'ask' else -trade.quantity
        window = self._flow
        horizon = now - FLOW_MS*1000
        while window and window[0][0] < horizon:
            self._flow_sum -= window.popleft()[1]
        if not window:
            self._flow_sum = 0
        if net:
            window.append((now, net))
            self._flow_sum += net
        flow = self._flow_sum if net else 0
        fired = 1 if flow >= MIN_LOTS else -1 if flow <= -MIN_LOTS else 0
        if fired:
            if self._big != fired or self._stopped:
                self._big_mid = mid
                self._stopped = False
            self._big = fired
            window.clear()
            self._flow_sum = 0
        bias = self._big
        if SELF_GATE:
            if bias != self._shadow_pos:
                step = bias-self._shadow_pos
                self._shadow_cash -= step*(ask if step > 0 else bid)
                self._shadow_pos = bias
            if self._shadow_cash+self._shadow_pos*mid <= GATE_TICKS:
                bias = 0
        if STOP > 0 and bias != 0:
            if not self._stopped and self._big*(self._big_mid-mid) >= STOP:
                self._stopped = True
        if self._stopped:
            bias = 0
        self._bias = bias

    def _cancel(self, order_id):
        record = self._orders[order_id]
        if record[3] and not record[4]:
            record[4] = True
            self.cancel_order(order_id)

    def _preserve(self, oid, record, sign, price):
        # Keep a resting touch order's queue place: shrink it to KEEP_LOTS instead of cancelling it.
        if price is None:
            return False
        if not record[3] or record[4] or oid == self._hedge_id or record[1] != self._qp_touch[sign]:
            return False
        if oid not in self.queue_ahead:
            return False
        if self.KEEP_LOTS > 0 and sign*self._qp_d >= -self.KEEP_TH:
            if record[2] > self.KEEP_LOTS and (record[7] == 0 or record[7] > self.KEEP_LOTS):
                self.modify_order(oid, self.KEEP_LOTS)
                record[7] = self.KEEP_LOTS
            return True
        return False

    def _quote(self, now, sign, price):
        current = [(oid,r) for oid,r in self._orders.items() if r[0] == sign]
        changing = False
        for oid,record in current:
            # A forecast take (record[6], its exemption's end) is not cancelled by the re-quote.
            if (price is None or record[1] != price) and now >= record[6]:
                if self._preserve(oid, record, sign, price):
                    continue
                self._cancel(oid)
                changing = True
        if len(current) >= 8:
            return
        if price is None or price <= 0 or now-self._last_action[sign] < self.REQUOTE_US:
            return
        reserved = sum(r[2] for r in self._orders.values() if r[0] == sign)
        effective=sum(ceil(r[2]*(1-self.CANCEL_FREE)) if r[4] else (min(r[2],r[7]) if r[7] > 0 else r[2])
                      for r in self._orders.values() if r[0]==sign)
        quantity=min(self.QUOTE_SIZE,self.EXPOSURE-sign*self.inventory-effective,
                     self.POSITION_LIMIT-sign*self.inventory-reserved)
        if quantity <= 0 or (current and quantity < 1):
            return
        order_id = self.send_order(OrderRequest(side=Side.BUY if sign > 0 else Side.SELL,
            price=price, quantity=quantity, order_type=OrderType.LIMIT))
        self._orders[order_id] = [sign,price,quantity,False,False,now,0,0]
        self._last_action[sign] = now

    def on_order_book_change(self, snapshot, trades):
        now = snapshot.timestamp_us
        elapsed = 0 if self._last_us is None else max(0,now-self._last_us)
        self._last_us = now
        second_group_decay=exp(-elapsed/1000000)
        for i in range(3):
            self._second_group_net[i]*=second_group_decay
            self._second_group_volume[i]*=second_group_decay
            self._second_group_price[i]*=second_group_decay
        self._second_rest_count_net*=second_group_decay
        self._second_rest_count*=second_group_decay
        if trades:
            visible={o.order_id:o for orders in (snapshot.bids,snapshot.asks) for o in orders if o.owner=='market'}
            arrivals={}
            for trade in trades:
                if trade.taker_owner!='market':
                    continue
                row=arrivals.setdefault(trade.taker_order_id,[1 if trade.book_side=='ask' else -1,0,0.0,0,0.0])
                row[1]+=trade.quantity
                row[2]+=trade.quantity*trade.price
                if trade.maker_owner=='user':
                    row[3]+=trade.quantity
                    row[4]+=trade.quantity*trade.price
            for oid,row in arrivals.items():
                direction,quantity,value,own,own_value=row
                group=0 if oid in visible else 1
                price=visible[oid].price if group==0 else value/max(1,quantity)
                quantity+=visible[oid].quantity if group==0 else 0
                weight=min(20,quantity)
                self._second_group_net[group]+=direction*weight
                self._second_group_volume[group]+=weight
                self._second_group_price[group]+=weight*price
                if group==0:
                    self._second_rest_count_net+=direction
                    self._second_rest_count+=1
                if own:
                    weight=min(20,own)
                    self._second_group_net[2]+=direction*weight
                    self._second_group_volume[2]+=weight
                    self._second_group_price[2]+=weight*own_value/own
        decay = exp(-elapsed/500_000)
        self._net *= decay
        self._volume *= decay
        for trade in trades:
            if trade.taker_owner == 'market':
                self._net += trade.quantity if trade.book_side == 'ask' else -trade.quantity
                self._volume += trade.quantity
        bid = ask = None
        bq = aq = 0
        # Feed order is price-time order: quantity preceding our id is ahead.
        self.queue_ahead = {}
        for orders in (snapshot.bids,snapshot.asks):
            level = None
            ahead = 0
            needed = {r[1] for r in self._orders.values()}
            market_touch = None
            for order in orders:
                if market_touch is not None and order.price != market_touch and order.price not in needed:
                    # Prices are sorted. Only scan farther when one of our
                    # orders is at that price or beyond it on this side.
                    farther = any((p < order.price if order.side == Side.BUY else p > order.price) for p in needed)
                    if not farther:
                        break
                if level != order.price:
                    level, ahead = order.price, 0
                if order.owner == 'user':
                    self.queue_ahead[order.order_id] = ahead
                else:
                    if market_touch is None:
                        market_touch = order.price
                    if order.side == Side.BUY:
                        if bid is None:
                            bid = order.price
                        if order.price == bid:
                            bq += order.quantity
                    else:
                        if ask is None:
                            ask = order.price
                        if order.price == ask:
                            aq += order.quantity
                ahead += order.quantity
        if bid is None or ask is None or bid >= ask:
            self._previous_touch = None
            self._desired_time = None
            if self._invalid_since is None:
                self._invalid_since = now
            if now-self._invalid_since >= 50_000:
                for order_id in list(self._orders):
                    self._cancel(order_id)
            return
        self._invalid_since = None
        dt=0 if self._new_quote_time is None else max(0,now-self._new_quote_time)
        self._new_quote_time=now
        decay_new=exp(-dt/500000)
        for i in range(4):
            self._new_counts[i]*=decay_new
            self._new_values[i]*=decay_new
        self._cancel_net*=decay_new
        self._cancel_mass*=decay_new
        current={o.order_id:o for orders in (snapshot.bids,snapshot.asks) for o in orders if o.owner=='market'}
        for oid,order in current.items():
            if oid in self._known_market:
                continue
            distance=bid-order.price if order.side==Side.BUY else order.price-ask
            if distance>3:
                continue
            index=0 if order.side==Side.BUY else 1
            self._new_counts[index]+=1
            self._new_values[index]+=order.price
            if order.quantity<=50:
                self._new_counts[index+2]+=1
                self._new_values[index+2]+=order.price
        traded={t.maker_order_id for t in trades if t.maker_owner=='market'}
        for oid,order in self._known_market.items():
            if oid in current or oid in traded:
                continue
            distance=bid-order.price if order.side==Side.BUY else order.price-ask
            if abs(distance)>3:
                continue
            self._cancel_net+=-1 if order.side==Side.BUY else 1
            self._cancel_mass+=1
        self._known_market=current
        mid = (bid+ask)*0.5
        spread = ask-bid
        self._update_big(now, trades, bid, ask, mid)
        flow = self._net/(1+self._volume)
        imbalance = (bq-aq)/(bq+aq)
        bn = an = bd_n = ad_n = 0
        br = ar = bd_r = ad_r = 0
        bd_value = ad_value = 0
        for orders in (snapshot.bids,snapshot.asks):
            for order in orders:
                if order.owner != 'market':
                    continue
                distance = bid-order.price if order.side == Side.BUY else order.price-ask
                if distance > 2:
                    break
                weight = min(20,order.quantity)
                if order.side == Side.BUY:
                    bd_n += 1
                    bd_r += weight
                    bd_value += weight*order.price
                    if distance == 0:
                        bn += 1
                        br += weight
                else:
                    ad_n += 1
                    ad_r += weight
                    ad_value += weight*order.price
                    if distance == 0:
                        an += 1
                        ar += weight
        count_imbalance = (bn-an)/max(1,bn+an)
        robust_imbalance = (br-ar)/max(1,br+ar)
        depth_count = (bd_n-ad_n)/max(1,bd_n+ad_n)
        depth_imbalance = (bd_r-ad_r)/max(1,bd_r+ad_r)
        depth_mid = (bd_value/max(1,bd_r)+ad_value/max(1,ad_r))*0.5-mid

        skew = self.SKEW_K * self.inventory/self.EXPOSURE * max(1.0,spread)
        if self._model_time is None or now-self._model_time > 10000000:
            self._fast_mid = self._slow_mid = mid
            self._observations.clear()
        else:
            dt=max(0,now-self._model_time)
            self._fast_mid += (1-exp(-dt/500000))*(mid-self._fast_mid)
            self._slow_mid += (1-exp(-dt/2000000))*(mid-self._slow_mid)
        self._model_time = now
        dt = 0 if self._ofi_time is None else max(0,now-self._ofi_time)
        self._ofi_time = now
        self._ofi *= exp(-dt/500000)
        if self._previous_touch is not None:
            old_bid,old_ask,old_bq,old_aq = self._previous_touch
            change = (bq if bid >= old_bid else 0) - (old_bq if bid <= old_bid else 0)
            change -= (aq if ask <= old_ask else 0)
            change += (old_aq if ask >= old_ask else 0)
            self._ofi += change/max(1,bq+aq,old_bq+old_aq)
        self._previous_touch = (bid,ask,bq,aq)
        ofi = max(-3,min(3,self._ofi))
        features=(flow,max(-5,min(5,self._fast_mid-self._slow_mid)),imbalance,
                  ofi,spread*imbalance,flow*abs(flow),imbalance*abs(imbalance),ofi*abs(ofi),count_imbalance,robust_imbalance,depth_count,depth_imbalance,depth_mid,count_imbalance*abs(count_imbalance),robust_imbalance*abs(robust_imbalance),(self._new_counts[0]-self._new_counts[1])/(1+self._new_counts[0]+self._new_counts[1]),
                  max(-5,min(5,((self._new_values[0]-mid*self._new_counts[0])/(1+self._new_counts[0])+(self._new_values[1]-mid*self._new_counts[1])/(1+self._new_counts[1]))*0.5)),
                  max(-5,min(5,((self._new_values[2]-mid*self._new_counts[2])/(1+self._new_counts[2])+(self._new_values[3]-mid*self._new_counts[3])/(1+self._new_counts[3]))*0.5)),
                  self._cancel_net/(1+self._cancel_mass),
                  max(-5,min(5,(self._new_values[0]+self._new_values[1]-mid*(self._new_counts[0]+self._new_counts[1]))/(1+self._new_counts[0]+self._new_counts[1]))),
                  (self._new_counts[2]-self._new_counts[3])/(1+self._new_counts[2]+self._new_counts[3]))
        features += (self._second_group_net[0]/(1+self._second_group_volume[0]),
                  self._second_group_net[1]/(1+self._second_group_volume[1]),
                  self._second_group_net[2]/(1+self._second_group_volume[2]),
                  self._second_group_volume[0]/(1+self._second_group_volume[0]+self._second_group_volume[1]),
                  max(-5,min(5,(self._second_group_price[0]-mid*self._second_group_volume[0])/(1+self._second_group_volume[0]))),
                  max(-5,min(5,(self._second_group_price[1]-mid*self._second_group_volume[1])/(1+self._second_group_volume[1]))),
                  max(-5,min(5,(self._second_group_price[2]-mid*self._second_group_volume[2])/(1+self._second_group_volume[2]))),
                  self._second_rest_count_net/(1+self._second_rest_count))
        if FEAT_BIG:
            features += (float(self._bias),)
        self._learn(now,mid)
        if now-self._last_observation_us >= self.OBSERVATION_INTERVAL_US:
            self._observations.append((now,mid,features))
            self._last_observation_us = now
        prediction = 0.25*spread*imbalance
        if self._labels >= self.MIN_LABELS:
            prediction = max(-2.0,min(2.0,sum(w*x for w,x in zip(self._weights,features))))
        fair = mid + 1.0*prediction + 0.0*0.25*spread*imbalance - skew
        self._qp_d = fair-mid
        self._qp_touch = {1: bid, -1: ask}
        if abs(fair-mid) <= self.DEAD_ZONE:
            fair = mid
        buy = min(bid,floor(fair-0.5))
        sell = max(ask,ceil(fair+0.5))
        if spread >= 2:
            if prediction-skew > self.INSIDE_TH:
                buy = min(ask-1,bid+1)
            elif prediction-skew < -self.INSIDE_TH:
                sell = max(bid+1,ask-1)
        # Withdraw the side vulnerable to a persistent aggressive sweep.
        if flow < -self.FLOW_CUT or self.inventory >= self.EXPOSURE:
            buy = None
        if flow > self.FLOW_CUT or self.inventory <= -self.EXPOSURE:
            sell = None
        if (self.TAKE_SZ > 0 and self._labels >= self.MIN_LABELS
                and (self._take_last is None or now-self._take_last >= self.TAKE_GAP_MS*1000)):
            self._take(now,prediction-skew,spread,bid,ask)
        self._cached_bid,self._cached_ask,self._cached_time = bid,ask,now
        self._hedge(now)
        self._desired_buy,self._desired_sell,self._desired_time = buy,sell,now
        self._quote(now,1,buy)
        self._quote(now,-1,sell)

    def on_private_order_update(self, event):
        record = self._orders.get(event.order_id)
        if record is None:
            return
        if event.status == OrderStatus.ACCEPTED:
            record[3] = True
        elif event.status in (OrderStatus.FILLED,OrderStatus.PARTIALLY_FILLED):
            self.inventory += record[0]*event.filled_quantity
            self.cash -= record[0]*event.filled_quantity*event.fill_price
            record[2] = event.remaining_quantity
            if event.status == OrderStatus.FILLED:
                del self._orders[event.order_id]
        elif event.status == OrderStatus.CANCELED:
            del self._orders[event.order_id]
        elif event.status == OrderStatus.REJECTED:
            # A failed cancel or modify can arrive after the original order
            # filled; unknown ids are ignored.
            if not record[3]:
                del self._orders[event.order_id]
            else:
                record[4] = False
                record[7] = 0
        elif event.status == OrderStatus.MODIFIED:
            record[2] = event.remaining_quantity
            record[7] = 0

        was_hedge = event.order_id == self._hedge_id
        if was_hedge and event.status in (OrderStatus.FILLED,OrderStatus.CANCELED,OrderStatus.REJECTED):
            self._hedge_id = None
        if (not was_hedge and self._desired_time is not None and 0 <= event.timestamp_us-self._desired_time <= 5000
                and event.status in (OrderStatus.CANCELED,)):
            self._quote(event.timestamp_us,1,self._desired_buy)
            self._quote(event.timestamp_us,-1,self._desired_sell)

        if was_hedge or event.status in (OrderStatus.FILLED,OrderStatus.PARTIALLY_FILLED):
            self._hedge(event.timestamp_us)
