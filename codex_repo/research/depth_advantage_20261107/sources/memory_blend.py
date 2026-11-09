"""Round-1 standalone submission: causal fair-price learning and passive execution.

Five features describe market trade flow, momentum, queue imbalance,
normalized order-flow imbalance, and spread-scaled imbalance. A regularized
online model learns 100 ms midpoint responses only after outcomes mature.
Up to eight orders per side share a strict +/-100-lot exposure budget;
pending orders and cancels retain their full remaining reservation.
No files, future rows, pre-fitted weights or session-end timing are used.
"""
from collections import deque
from math import exp, ceil, floor, isfinite

from simulator.models import OrderRequest, OrderStatus, OrderType, Side
from simulator.strategy import BaseStrategy


class PassiveStrategy(BaseStrategy):
    FEATURE_COUNT = 13
    HORIZON_US = 100000
    OBSERVATION_INTERVAL_US = 100000
    MIN_LABELS = 200
    MODEL_MEMORY_US = 300000000
    POSITION_LIMIT = 100
    QUOTE_SIZE = 200
    REQUOTE_US = 0

    def __init__(self):
        super().__init__()
        self.inventory = 0
        self.cash = 0
        self._orders = {}
        self._observations = deque(maxlen=64)
        self._last_observation_us = -100000
        self._last_fit_us = None
        self._last_label_us = None
        self._labels = 0
        self._mass = 0.0
        self._xx = [[0.0] * self.FEATURE_COUNT for _ in range(self.FEATURE_COUNT)]
        self._xy = [0.0] * self.FEATURE_COUNT
        self._weights = [0.0] * self.FEATURE_COUNT
        self._aux_observations = deque(maxlen=64)
        self._aux_last_observation_us = -100000
        self._aux_last_fit_us = None
        self._aux_last_label_us = None
        self._aux_labels = 0
        self._aux_mass = 0.0
        self._aux_xx = [[0.0] * self.FEATURE_COUNT for _ in range(self.FEATURE_COUNT)]
        self._aux_xy = [0.0] * self.FEATURE_COUNT
        self._aux_weights = [0.0] * self.FEATURE_COUNT
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

    def _learn_aux(self, now, mid):
        # Labels mature strictly after observation + horizon. Large gaps
        # are discarded instead of silently changing the prediction horizon.
        while self._aux_observations and self._aux_observations[0][0] + 100000 <= now:
            observed_us, old_mid, features = self._aux_observations.popleft()
            if now - observed_us > 100000 + 1_000_000:
                continue
            elapsed = 0 if self._aux_last_label_us is None else now - self._aux_last_label_us
            decay = exp(-max(0, elapsed) / 60000000)
            self._aux_last_label_us = now
            response = max(-20.0, min(20.0, mid - old_mid))
            self._aux_mass = self._aux_mass * decay + 1.0
            for i in range(self.FEATURE_COUNT):
                self._aux_xy[i] = self._aux_xy[i] * decay + features[i] * response
                for j in range(self.FEATURE_COUNT):
                    self._aux_xx[i][j] = self._aux_xx[i][j] * decay + features[i] * features[j]
            self._aux_labels += 1
        if self._aux_labels < self.MIN_LABELS:
            return
        if self._aux_last_fit_us is not None and now - self._aux_last_fit_us < 1_000_000:
            return
        self._aux_last_fit_us = now
        # Tiny positive-definite system; ridge protects near-constant or
        # correlated features. Solving here avoids per-event numpy overhead.
        ridge = max(10.0, 0.001 * self._aux_mass)
        matrix = [self._aux_xx[i][:] + [self._aux_xy[i]] for i in range(self.FEATURE_COUNT)]
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
            self._aux_weights = weights

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
        if changing or any(record[4] for oid,record in current):
            return
        if len(current) >= 8:
            return
        if price is None or price <= 0 or now-self._last_action[sign] < self.REQUOTE_US:
            return
        reserved = sum(r[2] for r in self._orders.values() if r[0] == sign)
        quantity = min(self.QUOTE_SIZE, self.POSITION_LIMIT-sign*self.inventory-reserved)
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
        for order in snapshot.bids:
            if order.owner != 'market':
                continue
            if bid is None:
                bid = order.price
            if order.price != bid:
                break
            bq += order.quantity
        for order in snapshot.asks:
            if order.owner != 'market':
                continue
            if ask is None:
                ask = order.price
            if order.price != ask:
                break
            aq += order.quantity
        if bid is None or ask is None or bid >= ask:
            self._previous_touch = None
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
                weight = min(100,order.quantity)
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

        skew = 0.05 * self.inventory/self.POSITION_LIMIT * max(1.0,spread)
        if self._model_time is None or now-self._model_time > 10000000:
            self._fast_mid = self._slow_mid = mid
            self._observations.clear()
            self._aux_observations.clear()
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
                  ofi,spread*imbalance,flow*abs(flow),imbalance*abs(imbalance),ofi*abs(ofi),count_imbalance,robust_imbalance,depth_count,depth_imbalance,depth_mid)
        self._learn(now,mid)
        self._learn_aux(now,mid)
        if now-self._last_observation_us >= self.OBSERVATION_INTERVAL_US:
            self._observations.append((now,mid,features))
            self._aux_observations.append((now,mid,features))
            self._last_observation_us = now
        prediction = 0.25*spread*imbalance
        if self._labels >= self.MIN_LABELS:
            prediction = max(-2.0,min(2.0,sum(w*x for w,x in zip(self._weights,features))))
        if self._aux_labels >= self.MIN_LABELS:
            auxiliary_prediction = max(-2.0,min(2.0,sum(w*x for w,x in zip(self._aux_weights,features))))
            prediction = 0.75*prediction + 0.25*auxiliary_prediction
        fair = mid + 1.0*prediction + 0.0*0.25*spread*imbalance - skew
        if abs(fair-mid) <= 0.1:
            fair = mid
        buy = min(bid,floor(fair-0.5))
        sell = max(ask,ceil(fair+0.5))
        # Withdraw the side vulnerable to a persistent aggressive sweep.
        if flow < -1.1 or self.inventory >= self.POSITION_LIMIT:
            buy = None
        if flow > 1.1 or self.inventory <= -self.POSITION_LIMIT:
            sell = None
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