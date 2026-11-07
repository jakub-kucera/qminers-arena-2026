# Adds the execution ideas in team F4 at commit 5003a35; independent composite implementation.
"""Composite research policy: queue-preserving market making with causal forecasts.

Models are trained offline. Runtime uses public snapshots and private order events.
Every sent/live/cancelling order reserves exposure until a terminal acknowledgement.
"""
from math import exp, log1p
from struct import pack, unpack
from simulator.models import OrderRequest, OrderStatus, OrderType, Side
from simulator.strategy import BaseStrategy

CAP = 100
QUOTE = 200
SKEW = 100
SESSION_S = 12000.0
WIND_DOWN_S = 30
MODEL = 'learned'
SIZE_ALPHA = 0.0
TARGET_ALPHA = 40.0
EDGE_FLOOR = 0.15
TOPUP = 1
MIN_REFILL = 10
MAX_QUOTES = 200
INVENTORY_SIZE = 0
INSIDE_MODE = 'off'
INSIDE_THRESHOLD = 0.25
INVENTORY_IMPROVE = 50
REGIME_GUARD = 0
REGIME_MOVE = 2.0
REGIME_FLOW = 0.5
FEATURE_US = 100_000
STEP_INSIDE = 0
DEPLETE_LOTS = 0
BACK_POS = 95
COEF1 = [0.0] * 9
INTERCEPT1 = 0.0
COEF5 = [0.0] * 9
INTERCEPT5 = 0.0
TREE_BASE = 0.0
TREE_RATE = 0.08
TREES = []
WEIGHTS = [1.0, 0.0, 0.0, 0.0, 0.0]

ML_KIND = 'robust'
ML_HISTORY = True
ML_BASE = 0.0
ML_COEF = []
ML_MEAN = []
ML_STD = []
ML_W = []
ML_B = []
ML_TREES = []
ML_CB_SCALE = 1.0

ROBUST_MODELS = [{'kind': 'linear', 'coef': [0.01032554253923703, 0.2906671559188385, -0.08759413589706916, 0.2654621370041782, -0.007132168777094859, -0.011323168234015728, -0.000833849633638895, 0.001563241379857245, -0.07573923784996163, -0.015065263068001695, 0.02757585394176674, 0.13186756450003062, 0.002924669160285446, -0.009561249236984825, 0.0, 0.003650606296813438, 0.08130886709519074, -0.027873639662025194, -0.042641543663349255, -0.011008062353853319, -0.0037464866052913494, -0.0056113651087803754, 0.015211278672671066, 0.0011988839143968737], 'base': -0.0142454691348534}]
ROBUST_WEIGHTS = [1.0]
ROBUST_GUARD = 0.0

class CompositeStrategy(BaseStrategy):
    def __init__(self):
        super().__init__()
        self.position = 0
        self.orders = {}
        self.start = None
        self.last_event = None
        self.next_feature = 0
        self.feature_time = -1
        self.flow = 0.0
        self.volume = 0.0
        self.ema1 = None
        self.ema5 = None
        self.features = [0.0] * 9
        self.alpha = 0.0
        self.feature_history = []
        self.bid_edge = 0.0
        self.ask_edge = 0.0

    def expand_features(self, now, mid, current):
        if not ML_HISTORY:
            return current
        self.feature_history.append((now, mid, current[:]))
        cutoff = now - 5_000_000
        while len(self.feature_history) > 1 and self.feature_history[1][0] <= cutoff:
            self.feature_history.pop(0)
        result = current[:]
        for lag in (250_000, 1_000_000, 5_000_000):
            chosen = self.feature_history[0]
            for row in self.feature_history:
                if row[0] > now - lag:
                    break
                chosen = row
            for index in (1, 2, 3, 8):
                result.append(current[index] - chosen[2][index])
            result.append(mid - chosen[1])
        return result

    def component(self, x, numeric, model):
        kind = model['kind']
        if kind == 'linear':
            return model['base'] + sum(a * b for a, b in zip(model['coef'], x))
        if kind == 'logit':
            z = [(b + sum(w * v for w, v in zip(row, x))) / model['temperature']
                 for row, b in zip(model['coef'], model['base'])]
            top = max(z)
            p = [exp(v - top) for v in z]
            return sum(a * b for a, b in zip(p, model['class_values'])) / sum(p)
        value = 0.0
        if kind == 'cat':
            for splits, leaves in model['trees']:
                index = 0
                for level, split in enumerate(splits):
                    if numeric[split[0]] > split[1]:
                        index += 1 << level
                value += leaves[index]
            return model['base'] + model['scale'] * value
        for tree in model['trees']:
            node = 0
            while tree[node][0] >= 0:
                f, threshold, left, right, leaf = tree[node]
                node = left if numeric[f] <= threshold else right
            value += tree[node][4]
        return value / len(model['trees'])

    def predict(self, x):
        numeric = unpack('f' * len(x), pack('f' * len(x), *x))
        values = [self.component(x, numeric, m) for m in ROBUST_MODELS]
        center = sum(w * v for w, v in zip(ROBUST_WEIGHTS, values))
        if ROBUST_GUARD:
            spread = sum(w * (v - center) ** 2 for w, v in zip(ROBUST_WEIGHTS, values)) ** .5
            magnitude = max(0.0, abs(center) - ROBUST_GUARD * spread)
            return magnitude if center >= 0 else -magnitude
        return center



    def update_features(self, snapshot, trades, bid, ask):
        now = snapshot.timestamp_us
        if self.last_event is not None:
            decay = exp(-(now - self.last_event) / 1_000_000)
            self.flow *= decay
            self.volume *= decay
        self.last_event = now
        for trade in trades:
            if trade.taker_owner == 'market' and trade.maker_owner == 'market':
                self.flow += trade.quantity if trade.book_side == 'ask' else -trade.quantity
                self.volume += trade.quantity
        if now < self.next_feature:
            return
        self.next_feature = now + FEATURE_US
        mid = (bid + ask) / 2
        spread = ask - bid
        bq = aq = bd = ad = 0
        for o in snapshot.bids:
            if o.owner == 'market':
                if o.price == bid:
                    bq += o.quantity
                if o.price >= bid - 4:
                    bd += o.quantity
        for o in snapshot.asks:
            if o.owner == 'market':
                if o.price == ask:
                    aq += o.quantity
                if o.price <= ask + 4:
                    ad += o.quantity
        if self.ema1 is None:
            self.ema1 = mid
            self.ema5 = mid
        else:
            seconds = max(0, now - self.feature_time) / 1_000_000
            self.ema1 += (1 - exp(-seconds)) * (mid - self.ema1)
            self.ema5 += (1 - exp(-seconds / 5)) * (mid - self.ema5)
        imbalance = (bq - aq) / max(1, bq + aq)
        self.features = [spread, imbalance, (bd - ad) / max(1, bd + ad),
            self.flow / max(1, self.volume), mid - self.ema1, mid - self.ema5,
            log1p(bq + aq), log1p(self.volume), 0.5 * spread * imbalance]
        self.feature_time = now
        values = self.expand_features(now, mid, self.features)
        if ML_KIND == 'fillcat':
            self.bid_edge = self.predict(values + [1.0])
            self.ask_edge = self.predict(values + [-1.0])
            self.alpha = max(-2.0, min(2.0, (self.bid_edge - self.ask_edge) / 2))
        else:
            self.alpha = max(-2.0, min(2.0, self.predict(values)))

    def keep(self, sign, price, desired):
        kept = 0
        available_quantity = 0
        for oid, order in list(self.orders.items()):
            if order[0] != sign or order[3]:
                continue
            if price and order[1] == price and (TOPUP or kept == 0):
                kept += 1
                available_quantity += order[2]
            else:
                self.cancel_order(oid)
                order[3] = True
        if not price or (kept and not TOPUP):
            return
        if TOPUP and kept >= MAX_QUOTES:
            return
        exposure = sum(o[2] for o in self.orders.values() if o[0] == sign)
        room = max(0, CAP - sign * self.position - exposure)
        quantity = min(room, max(0, int(desired) - available_quantity))
        if quantity <= 0 or (kept and quantity < MIN_REFILL):
            return
        oid = self.send_order(OrderRequest(side=Side.BUY if sign > 0 else Side.SELL,
            price=price, quantity=quantity, order_type=OrderType.LIMIT))
        self.orders[oid] = [sign, price, quantity, False]

    def on_order_book_change(self, snapshot, trades):
        now = snapshot.timestamp_us
        if self.start is None:
            self.start = now
        bid = ask = 0
        bid_lots = ask_lots = 0
        for order in snapshot.bids:
            if order.owner == 'market':
                if bid == 0:
                    bid = order.price
                elif order.price != bid:
                    break
                bid_lots += order.quantity
        for order in snapshot.asks:
            if order.owner == 'market':
                if ask == 0:
                    ask = order.price
                elif order.price != ask:
                    break
                ask_lots += order.quantity
        if not bid or not ask or ask <= bid:
            return
        if MODEL != 'none' or REGIME_GUARD:
            self.update_features(snapshot, trades, bid, ask)
        mid = (bid + ask) / 2
        bp, ap = (bid + 1, ask - 1) if STEP_INSIDE and ask - bid >= 3 else (bid, ask)
        target = max(-CAP / 2, min(CAP / 2, TARGET_ALPHA * self.alpha))
        inventory_error = self.position - target
        if inventory_error >= BACK_POS:
            bp = bid - 1
        if inventory_error <= -BACK_POS:
            ap = ask + 1
        winding = (now - self.start) / 1_000_000 > SESSION_S - WIND_DOWN_S
        want_buy = inventory_error < SKEW and not (winding and self.position >= 0)
        want_sell = inventory_error > -SKEW and not (winding and self.position <= 0)
        if DEPLETE_LOTS and bid_lots < DEPLETE_LOTS:
            want_buy = False
        if DEPLETE_LOTS and ask_lots < DEPLETE_LOTS:
            want_sell = False
        if REGIME_GUARD:
            trend = self.features[5]
            signed_flow = self.features[3]
            if trend > REGIME_MOVE and signed_flow > REGIME_FLOW:
                want_sell = False
            if trend < -REGIME_MOVE and signed_flow < -REGIME_FLOW:
                want_buy = False
        if ask - bid == 2:
            direction = 0
            if INSIDE_MODE in ('inventory', 'both'):
                if inventory_error >= INVENTORY_IMPROVE:
                    direction = -1
                elif inventory_error <= -INVENTORY_IMPROVE:
                    direction = 1
            if direction == 0 and INSIDE_MODE in ('alpha', 'both'):
                if self.alpha >= INSIDE_THRESHOLD:
                    direction = 1
                elif self.alpha <= -INSIDE_THRESHOLD:
                    direction = -1
            if direction == 1:
                bp = bid + 1
            elif direction == -1:
                ap = ask - 1
        buy_edge = self.bid_edge + bid - bp if ML_KIND == 'fillcat' else mid - bp + self.alpha
        if buy_edge < EDGE_FLOOR:
            want_buy = False
        sell_edge = self.ask_edge + ap - ask if ML_KIND == 'fillcat' else ap - mid - self.alpha
        if sell_edge < EDGE_FLOOR:
            want_sell = False
        buy_size = QUOTE * max(0.1, 1 + SIZE_ALPHA * self.alpha)
        sell_size = QUOTE * max(0.1, 1 - SIZE_ALPHA * self.alpha)
        if INVENTORY_SIZE:
            buy_size -= inventory_error
            sell_size += inventory_error
        self.keep(1, bp if want_buy else 0, buy_size)
        self.keep(-1, ap if want_sell else 0, sell_size)

    def on_private_order_update(self, event):
        order = self.orders.get(event.order_id)
        if order is None:
            return
        if event.status in (OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED):
            self.position += order[0] * event.filled_quantity
            order[2] = event.remaining_quantity
        if event.status in (OrderStatus.FILLED, OrderStatus.CANCELED):
            self.orders.pop(event.order_id, None)
        elif event.status == OrderStatus.REJECTED and event.remaining_quantity == 0:
            self.orders.pop(event.order_id, None)
