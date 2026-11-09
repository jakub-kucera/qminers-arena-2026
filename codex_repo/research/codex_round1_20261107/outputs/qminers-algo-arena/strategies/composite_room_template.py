# Adds the execution ideas in team F4 at commit 5003a35; independent composite implementation.
"""Composite research policy: queue-preserving market making with causal forecasts.

Models are trained offline. Runtime uses public snapshots and private order events.
Every sent/live/cancelling order reserves exposure until a terminal acknowledgement.
"""
from math import exp, log1p
from simulator.models import OrderRequest, OrderStatus, OrderType, Side
from simulator.strategy import BaseStrategy

CAP = 100
QUOTE = 100
SKEW = 80
SESSION_S = 5750.0
WIND_DOWN_S = 60
MODEL = 'none'
SIZE_ALPHA = 0.0
TARGET_ALPHA = 0.0
EDGE_FLOOR = -100.0
TOPUP = 0
MIN_REFILL = 20
MAX_QUOTES = 4
INVENTORY_SIZE = 0
INSIDE_MODE = 'off'
INSIDE_THRESHOLD = 0.25
INVENTORY_IMPROVE = 50
REGIME_GUARD = 0
REGIME_MOVE = 2.0
REGIME_FLOW = 0.5
FEATURE_US = 100_000
STEP_INSIDE = 1
DEPLETE_LOTS = 0
BACK_POS = 1000
COEF1 = [0.0] * 9
INTERCEPT1 = 0.0
COEF5 = [0.0] * 9
INTERCEPT5 = 0.0
TREE_BASE = 0.0
TREE_RATE = 0.08
TREES = []
WEIGHTS = [1.0, 0.0, 0.0, 0.0, 0.0]


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

    def predict(self, x):
        linear1 = INTERCEPT1 + sum(a * b for a, b in zip(COEF1, x))
        if MODEL == 'linear':
            return max(-2.0, min(2.0, linear1))
        if MODEL == 'microprice':
            return max(-2.0, min(2.0, x[8]))
        linear5 = INTERCEPT5 + sum(a * b for a, b in zip(COEF5, x))
        boosted = TREE_BASE
        for tree in TREES:
            node = 0
            while tree[node][0] >= 0:
                row = tree[node]
                node = row[2] if x[row[0]] <= row[1] else row[3]
            boosted += TREE_RATE * tree[node][4]
        prediction = WEIGHTS[0] * linear1 + WEIGHTS[1] * linear5 + WEIGHTS[2] * boosted + WEIGHTS[3] * x[8]
        return max(-2.0, min(2.0, prediction))

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
        self.alpha = self.predict(self.features) if MODEL != 'none' else 0.0

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
        if mid - bp + self.alpha < EDGE_FLOOR:
            want_buy = False
        if ap - mid - self.alpha < EDGE_FLOOR:
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
