"""R2-E1: R2-FT1 (r2_FT1_forecast_take.py) at a low exposure, for round 2.

R2-FT1 is R1-C12 (an online ridge of the 400-ms mid move on 29 causal
microstructure features, quoted as a market maker) plus a forecast take. Here
its literals are named constants: EXPOSURE (the lots the quoting, the skew,
the withdrawal, the take and the hedge aim at; POSITION_LIMIT stays the 1,000
wall), DEAD_ZONE, INSIDE_TH, SKEW_K, QUOTE_SIZE, TAKE_EDGE, TAKE_SZ,
TAKE_GAP_MS, HEDGE_TICKS. Set for round 2's trending public tape: EXPOSURE 30,
DEAD_ZONE 0.3. With EXPOSURE 100 and DEAD_ZONE 0.18 it is R2-FT1 exactly.
The Rust twin: ridge_maker (rust/arena_sim/src/strategies/ridge_maker.rs)
--set POSITION_LIMIT=1000 --set CANCEL_FREE=1.0 --set HEDGE=1
--set MODEL_MEMORY_US=100000000000 --set HORIZON_US=400000 --set QUOTEFEAT=1
--set FLOWGRP=2 --set FLOWGRP_CAP=20 --set FLOWGRP_US=1000000 --set FT_SZ=200
--set FT_GAP_MS=50 --set SKEW_K=0.025 --set EXPOSURE=30 --set DEAD_ZONE=0.3
--set FT_EDGE=0.25 --set QUOTE_SIZE=200. Numbers: see IDEAS.md.
"""
from collections import deque
from math import exp, ceil, floor, isfinite

from simulator.models import OrderRequest, OrderStatus, OrderType, Side
from simulator.strategy import BaseStrategy


class PassiveStrategy(BaseStrategy):
    FEATURE_COUNT = 29
    HORIZON_US = 400000
    OBSERVATION_INTERVAL_US = 20000
    MIN_LABELS = 200
    MODEL_MEMORY_US = 100000000000
    POSITION_LIMIT = 1000
    QUOTE_SIZE = 200
    REQUOTE_US = 0
    EXPOSURE = 30        # R2-FT1: 100
    DEAD_ZONE = 0.3      # R2-FT1: 0.18
    INSIDE_TH = 0.3
    SKEW_K = 0.025
    FLOW_CUT = 1.1
    CANCEL_FREE = 1.0
    HEDGE_TICKS = 10
    HEDGE_STALE_US = 100000
    TAKE_EDGE = 0.25
    TAKE_SZ = 200
    TAKE_GAP_MS = 50
    TAKE_MODE = 0   # 0 any, 1 only to reduce, 2 only to open or add
    TAKE_INV = 0    # TAKE_MODE 1: the least |inventory| to reduce
    TAKE_THRU = 0

    def __init__(self):
        super().__init__()
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
        self._orders[oid] = [sign,price,quantity,False,False,now]
        self._hedge_id = oid

    def _take(self, now, signal, spread, bid, ask):
        need = self.TAKE_EDGE + 0.5*spread
        sign = 1 if signal > need else -1 if signal < -need else 0
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
        quantity = min(self.TAKE_SZ,room,self.POSITION_LIMIT-pos-reserved)
        if quantity <= 0:
            return
        price = ask+self.TAKE_THRU if sign > 0 else max(1,bid-self.TAKE_THRU)
        oid = self.send_order(OrderRequest(side=Side.BUY if sign > 0 else Side.SELL,
            price=price,quantity=quantity,order_type=OrderType.IOC))
        self._orders[oid] = [sign,price,quantity,False,False,now,now+1_000_000]
        self._take_last = now

    def _cancel(self, order_id):
        record = self._orders[order_id]
        if record[3] and not record[4]:
            record[4] = True
            self.cancel_order(order_id)

    def _quote(self, now, sign, price):
        current = [(oid,r) for oid,r in self._orders.items() if r[0] == sign]
        changing = False
        for oid,record in current:
            # A forecast take (record[6], its exemption's end) is not cancelled by the re-quote.
            if (price is None or record[1] != price) and now >= (record[6] if len(record) > 6 else 0):
                self._cancel(oid)
                changing = True
        if len(current) >= 8:
            return
        if price is None or price <= 0 or now-self._last_action[sign] < self.REQUOTE_US:
            return
        reserved = sum(r[2] for r in self._orders.values() if r[0] == sign)
        effective=sum(ceil(r[2]*(1-self.CANCEL_FREE)) if r[4] else r[2] for r in self._orders.values() if r[0]==sign)
        quantity=min(self.QUOTE_SIZE,self.EXPOSURE-sign*self.inventory-effective,
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
        self._learn(now,mid)
        if now-self._last_observation_us >= self.OBSERVATION_INTERVAL_US:
            self._observations.append((now,mid,features))
            self._last_observation_us = now
        prediction = 0.25*spread*imbalance
        if self._labels >= self.MIN_LABELS:
            prediction = max(-2.0,min(2.0,sum(w*x for w,x in zip(self._weights,features))))
        fair = mid + 1.0*prediction + 0.0*0.25*spread*imbalance - skew
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
