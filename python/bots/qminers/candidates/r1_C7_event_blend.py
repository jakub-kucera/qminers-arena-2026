"""Round 1 candidate R1-C7 (7 Nov, 17:20): R1-C5 with an event-time learner blended in. The first ridge's label is
the mid's change at its LABEL_K-th (1) change after the observation (dropped if that change has not come within
LABEL_CAP_US, 5 s); a second ridge on the same features keeps C5's 400 ms clock-time label; the prediction is
(1 - BLEND_W) p_event + BLEND_W p_clock with BLEND_W 0.8 (each clamped to +-2). Rust ridge_maker LABEL_MODE=1 LABEL_K=1
BLEND_W=0.8 H2_US=400000 on C5's settings: 600,429.83 (in 453,238.83 +4.3k, out 147,191 +0.7k, penalty 1,620).
The notes of R1-C5 follow.

Round 1 candidate R1-C5 (7 Nov, 17:05): R1-C1b (the codex v2) with HORIZON_US 400000, MODEL_MEMORY_US 1e11 and the dead zone 0.18, the centre of the plateau of a Rust ridge_maker grid on the first 75% of round1.csv: 595,441.83 (penalty 1,720). The notes of R1-C1b follow.

Round-1 market maker with pipelined cancel/replace and charged risk.

The online fifteen-feature forecast uses matured 100 ms labels. Replacement
orders may be submitted while cancellations are in flight. Provisional
exposure targets 100 lots; actual and potential exposure may exceed 100.
The acceptance wall is 1000 lots. All actual time beyond 100 incurs the
native 10000-per-second penalty. IOC hedges also incur 5 ms latency.
This variant hedges excess inventory from private fills as well as public
updates. Results must be compared using net PnL after the full penalty.
"""
from collections import deque
from math import exp, ceil, floor, isfinite

from simulator.models import OrderRequest, OrderStatus, OrderType, Side
from simulator.strategy import BaseStrategy


class PassiveStrategy(BaseStrategy):
    FEATURE_COUNT = 15
    HORIZON_US = 400000
    OBSERVATION_INTERVAL_US = 20000
    MIN_LABELS = 200
    MODEL_MEMORY_US = 100000000000
    POSITION_LIMIT = 1000
    QUOTE_SIZE = 200
    REQUOTE_US = 0
    LABEL_K = 1
    LABEL_CAP_US = 5_000_000
    BLEND_W = 0.8
    H2_US = 400000

    def __init__(self):
        super().__init__()
        self.inventory = 0
        self.cash = 0
        self._orders = {}
        self._hedge_id = None
        self._cached_bid = self._cached_ask = self._cached_time = None
        self._desired_buy = self._desired_sell = None
        self._desired_time = None
        self._last_observation_us = -100000
        # the event-time model (no maxlen: LABEL_CAP_US bounds it) and the clock-time one (C5's)
        self._models = [self._new_model(deque()), self._new_model(deque(maxlen=64))]
        self._mid_changes = 0
        self._last_mid = None
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

    def _new_model(self, observations):
        n = self.FEATURE_COUNT
        return {"obs": observations, "last_fit_us": None, "last_label_us": None, "labels": 0, "mass": 0.0,
                "xx": [[0.0] * n for _ in range(n)], "xy": [0.0] * n, "weights": [0.0] * n}

    def _learn(self, m, event, now, mid):
        observations = m["obs"]
        while observations:
            if event:
                # event time: the label is the mid at its LABEL_K-th change after the observation
                observed_us, old_mid, features, count = observations[0]
                if count + self.LABEL_K <= self._mid_changes:
                    observations.popleft()
                    if now - observed_us > self.LABEL_CAP_US:
                        continue
                elif now - observed_us > self.LABEL_CAP_US:
                    observations.popleft()
                    continue
                else:
                    break
            else:
                # Labels mature strictly after observation + horizon. Large gaps
                # are discarded instead of silently changing the prediction horizon.
                if observations[0][0] + self.H2_US > now:
                    break
                observed_us, old_mid, features, count = observations.popleft()
                if now - observed_us > self.H2_US + 1_000_000:
                    continue
            elapsed = 0 if m["last_label_us"] is None else now - m["last_label_us"]
            decay = exp(-max(0, elapsed) / self.MODEL_MEMORY_US)
            m["last_label_us"] = now
            response = max(-20.0, min(20.0, mid - old_mid))
            m["mass"] = m["mass"] * decay + 1.0
            xy, xx = m["xy"], m["xx"]
            for i in range(self.FEATURE_COUNT):
                xy[i] = xy[i] * decay + features[i] * response
                row = xx[i]
                for j in range(self.FEATURE_COUNT):
                    row[j] = row[j] * decay + features[i] * features[j]
            m["labels"] += 1
        if m["labels"] < self.MIN_LABELS:
            return
        if m["last_fit_us"] is not None and now - m["last_fit_us"] < 1_000_000:
            return
        m["last_fit_us"] = now
        # Tiny positive-definite system; ridge protects near-constant or
        # correlated features. Solving here avoids per-event numpy overhead.
        ridge = max(10.0, 0.001 * m["mass"])
        matrix = [m["xx"][i][:] + [m["xy"][i]] for i in range(self.FEATURE_COUNT)]
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
            m["weights"] = weights

    def _hedge(self, now):
        if abs(self.inventory) <= 100 or self._hedge_id is not None:
            return
        if self._cached_time is None or now-self._cached_time > 100000:
            return
        sign = -1 if self.inventory > 0 else 1
        reserved = sum(r[2] for r in self._orders.values() if r[0] == sign)
        quantity = min(abs(self.inventory)-100,max(0,self.POSITION_LIMIT-sign*self.inventory-reserved))
        if quantity <= 0:
            return
        price = self._cached_ask+10 if sign > 0 else max(1,self._cached_bid-10)
        oid = self.send_order(OrderRequest(side=Side.BUY if sign > 0 else Side.SELL,
            price=price,quantity=quantity,order_type=OrderType.IOC))
        self._orders[oid] = [sign,price,quantity,False,False,now]
        self._hedge_id = oid

    def _cancel(self, order_id):
        record = self._orders[order_id]
        if record[3] and not record[4]:
            record[4] = True
            self.cancel_order(order_id)

    def _quote(self, now, sign, price):
        current = [(oid,r) for oid,r in self._orders.items() if r[0] == sign]
        changing = False
        for oid,record in current:
            if price is None or record[1] != price:
                self._cancel(oid)
                changing = True
        if len(current) >= 8:
            return
        if price is None or price <= 0 or now-self._last_action[sign] < self.REQUOTE_US:
            return
        reserved = sum(r[2] for r in self._orders.values() if r[0] == sign)
        effective=sum(ceil(r[2]*(1-1.0)) if r[4] else r[2] for r in self._orders.values() if r[0]==sign)
        quantity=min(self.QUOTE_SIZE,100-sign*self.inventory-effective,
                     self.POSITION_LIMIT-sign*self.inventory-reserved)
        if quantity <= 0 or (current and quantity < 1):
            return
        order_id = self.send_order(OrderRequest(side=Side.BUY if sign > 0 else Side.SELL,
            price=price, quantity=quantity, order_type=OrderType.LIMIT))
        self._orders[order_id] = [sign,price,quantity,False,False,now]
        self._last_action[sign] = now

    def on_order_book_change(self, snapshot, trades):
        now = snapshot.timestamp_us
        elapsed = 0 if self._last_us is None else max(0,now-self._last_us)
        self._last_us = now
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
        mid = (bid+ask)*0.5
        spread = ask-bid
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

        skew = 0.025 * self.inventory/100 * max(1.0,spread)
        if self._model_time is None or now-self._model_time > 10000000:
            self._fast_mid = self._slow_mid = mid
            for m in self._models:
                m["obs"].clear()
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
                  ofi,spread*imbalance,flow*abs(flow),imbalance*abs(imbalance),ofi*abs(ofi),count_imbalance,robust_imbalance,depth_count,depth_imbalance,depth_mid,count_imbalance*abs(count_imbalance),robust_imbalance*abs(robust_imbalance))
        if self._last_mid != mid:
            if self._last_mid is not None:
                self._mid_changes += 1
            self._last_mid = mid
        m1, m2 = self._models
        self._learn(m1,True,now,mid)
        self._learn(m2,False,now,mid)
        if now-self._last_observation_us >= self.OBSERVATION_INTERVAL_US:
            m1["obs"].append((now,mid,features,self._mid_changes))
            m2["obs"].append((now,mid,features,self._mid_changes))
            self._last_observation_us = now
        prediction = 0.25*spread*imbalance
        if m1["labels"] >= self.MIN_LABELS:
            prediction = max(-2.0,min(2.0,sum(w*x for w,x in zip(m1["weights"],features))))
            if m2["labels"] >= self.MIN_LABELS:
                p2 = max(-2.0,min(2.0,sum(w*x for w,x in zip(m2["weights"],features))))
                prediction = (1.0-self.BLEND_W)*prediction + self.BLEND_W*p2
        fair = mid + 1.0*prediction + 0.0*0.25*spread*imbalance - skew
        if abs(fair-mid) <= 0.18:
            fair = mid
        buy = min(bid,floor(fair-0.5))
        sell = max(ask,ceil(fair+0.5))
        if spread >= 2:
            if prediction-skew > 0.3:
                buy = min(ask-1,bid+1)
            elif prediction-skew < -0.3:
                sell = max(bid+1,ask-1)
        # Withdraw the side vulnerable to a persistent aggressive sweep.
        if flow < -1.1 or self.inventory >= 100:
            buy = None
        if flow > 1.1 or self.inventory <= -100:
            sell = None
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
            # Only send and cancel requests are used. A failed cancel can
            # arrive after the original order filled; unknown ids are ignored.
            if not record[3]:
                del self._orders[event.order_id]
            else:
                record[4] = False

        was_hedge = event.order_id == self._hedge_id
        if was_hedge and event.status in (OrderStatus.FILLED,OrderStatus.CANCELED,OrderStatus.REJECTED):
            self._hedge_id = None
        if (not was_hedge and self._desired_time is not None and 0 <= event.timestamp_us-self._desired_time <= 5000
                and event.status in (OrderStatus.CANCELED,)):
            self._quote(event.timestamp_us,1,self._desired_buy)
            self._quote(event.timestamp_us,-1,self._desired_sell)

        if was_hedge or event.status in (OrderStatus.FILLED,OrderStatus.PARTIALLY_FILLED):
            self._hedge(event.timestamp_us)
