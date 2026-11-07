"""Causal research challenger. Parameters are hypotheses, not a competition guarantee.

One bounded-state strategy; only public snapshots/private fills are used. MODE can
be maker, revert, ridge_ioc, ridge_maker, or record (offline feature collection).
Ridge coefficients are embedded by the research harness after chronological fit.
"""

from math import exp, floor, ceil, log1p
from simulator.models import OrderRequest, OrderStatus, OrderType, Side
from simulator.strategy import BaseStrategy

MODE = 'maker'
CAP = 80
SIZE = 20
SESSION_S = 5750.0
WIND_DOWN_S = 60
FLAT_S = 10
DECISION_US = 100_000
EDGE = 0.75
HOLD_US = 1_000_000
COEFFICIENTS = [0.0] * 9
INTERCEPT = 0.0


class ResearchStrategy(BaseStrategy):
    def __init__(self):
        super().__init__()
        self.position = 0
        self.orders = {}
        self.start = None
        self.last_event = None
        self.next_decision = 0
        self.flow = 0.0
        self.volume = 0.0
        self.ema_fast = None
        self.ema_slow = None
        self.last_feature_time = -1
        self.features = []
        self.last_bid = 0
        self.last_ask = 0
        self.last_depth = (0, 0)
        self.exit_time = 0

    def room(self, sign):
        outstanding = sum(o[2] for o in self.orders.values() if o[0] == sign)
        return max(0, CAP - sign * self.position - outstanding)

    def send(self, sign, price, qty, ioc=False):
        qty = min(qty, self.room(sign))
        if qty <= 0 or price <= 0:
            return
        oid = self.send_order(OrderRequest(side=Side.BUY if sign == 1 else Side.SELL,
                price=int(price), quantity=int(qty), order_type=OrderType.IOC if ioc else OrderType.LIMIT))
        self.orders[oid] = [sign, price, qty, False, ioc]

    def keep(self, sign, price):
        found = False
        for oid, order in list(self.orders.items()):
            if order[0] != sign or order[3] or order[4]:
                continue
            if price and order[1] == price and not found:
                found = True
            else:
                self.cancel_order(oid)
                order[3] = True
        if price and not found:
            self.send(sign, price, SIZE)

    def on_order_book_change(self, snapshot, trades):
        now = snapshot.timestamp_us
        if self.start is None:
            self.start = now
        if self.last_event is not None:
            decay = exp(-(now - self.last_event) / 1_000_000)
            self.flow *= decay
            self.volume *= decay
        self.last_event = now
        for trade in trades:
            if trade.taker_owner == 'market' and trade.maker_owner == 'market':
                self.flow += trade.quantity if trade.book_side == 'ask' else -trade.quantity
                self.volume += trade.quantity
        if now < self.next_decision:
            return
        bids = [o for o in snapshot.bids if o.owner == 'market']
        asks = [o for o in snapshot.asks if o.owner == 'market']
        if not bids or not asks:
            return
        self.next_decision = now + DECISION_US
        bid, ask = bids[0].price, asks[0].price
        if ask <= bid:
            return
        mid = (bid + ask) / 2
        spread = ask - bid
        bq = sum(o.quantity for o in bids if o.price == bid)
        aq = sum(o.quantity for o in asks if o.price == ask)
        bd = sum(o.quantity for o in bids if o.price >= bid - 4)
        ad = sum(o.quantity for o in asks if o.price <= ask + 4)
        if self.ema_fast is None:
            self.ema_fast = mid
            self.ema_slow = mid
        else:
            elapsed = max(0, now - self.last_feature_time) / 1_000_000
            self.ema_fast += (1 - exp(-elapsed)) * (mid - self.ema_fast)
            self.ema_slow += (1 - exp(-elapsed / 5)) * (mid - self.ema_slow)
        imbalance = (bq - aq) / max(1, bq + aq)
        self.features = [spread, imbalance, (bd - ad) / max(1, bd + ad),
                         self.flow / max(1, self.volume), mid - self.ema_fast,
                         mid - self.ema_slow, log1p(bq + aq), log1p(self.volume),
                         0.5 * spread * imbalance]
        self.last_feature_time = now
        self.last_bid, self.last_ask = bid, ask
        self.last_depth = (bq, aq)
        if MODE == 'record':
            return
        elapsed_s = (now - self.start) / 1_000_000
        if elapsed_s >= SESSION_S - FLAT_S:
            self.keep(1, 0)
            self.keep(-1, 0)
            # Wait for terminal acknowledgements before flattening; never net
            # a pending cancellation against a new order's exposure.
            if not self.orders and self.position:
                self.send(-1 if self.position > 0 else 1,
                          bid if self.position > 0 else ask, abs(self.position), True)
            return
        prediction = INTERCEPT + sum(a * b for a, b in zip(COEFFICIENTS, self.features))
        if MODE in ('maker', 'ridge_maker'):
            alpha = max(-2.0, min(2.0, prediction)) if MODE == 'ridge_maker' else 0.5 * spread * imbalance
            fair = mid + alpha - 2.0 * self.position / CAP
            bp = min(ask - 1, floor(fair - 0.5))
            ap = max(bid + 1, ceil(fair + 0.5))
            winding = elapsed_s >= SESSION_S - WIND_DOWN_S
            self.keep(1, bp if not winding or self.position < 0 else 0)
            self.keep(-1, ap if not winding or self.position > 0 else 0)
            return
        if self.orders:
            return
        winding = elapsed_s >= SESSION_S - WIND_DOWN_S
        if self.position:
            if winding or now >= self.exit_time:
                self.send(-1 if self.position > 0 else 1,
                          bid if self.position > 0 else ask, abs(self.position), True)
            return
        if winding:
            return
        signal = prediction if MODE == 'ridge_ioc' else self.ema_slow - mid
        if abs(signal) > spread / 2 + EDGE:
            self.send(1 if signal > 0 else -1, ask if signal > 0 else bid, SIZE, True)
            self.exit_time = now + HOLD_US

    def on_private_order_update(self, event):
        order = self.orders.get(event.order_id)
        if order is None:
            return
        if event.status in (OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED):
            self.position += order[0] * event.filled_quantity
            order[2] = event.remaining_quantity
        if event.status in (OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED):
            self.orders.pop(event.order_id, None)
