"""Guarded IOC trend alternative for sparse/trending books. Strict 80-lot exposure.

Round-2 hypothesis; performance on round-2 data is unknown.
Uses only current/past public information and causally matured labels.
"""

from collections import deque
from math import exp, isfinite

from simulator.models import OrderRequest, OrderStatus, OrderType, Side
from simulator.strategy import BaseStrategy


class GuardedStrategy(BaseStrategy):
    POSITION_LIMIT = 100
    MAX_ORDER_SIZE = 100
    HORIZON_US = 2_000_000
    OBSERVATION_INTERVAL_US = 100_000
    MIN_LABELS = 200
    MIN_ORDER_INTERVAL_US = 20_000
    MODEL_MEMORY_US = 300_000_000

    def __init__(self):
        super().__init__()
        self.inventory = 0
        self.cash = 0
        self._pending_id = None
        self._pending_side = 0
        self._pending_remaining = 0
        self._last_order_us = -self.MIN_ORDER_INTERVAL_US
        self._flow_us = None
        self._flow_net = 0.0
        self._flow_volume = 0.0
        self._last_market_trade_us = None
        self._feature_us = None
        self._one_sided_since_us = None
        self._fast_mid = None
        self._slow_mid = None
        self._observations = deque(maxlen=64)
        self._last_observation_us = -self.OBSERVATION_INTERVAL_US
        self._last_fit_us = None
        self._last_label_us = None
        self._labels = 0
        self._mass = 0.0
        self._xx = [[0.0] * 3 for _ in range(3)]
        self._xy = [0.0] * 3
        self._weights = [0.0] * 3
        self._forecast = 0.0
        self._target = 0
        self._guard_pending = deque(maxlen=64)
        self._guard_observed_us = None
        self._guard_score = 0.0
        self._guard_last_scored_us = None
        self._guard_count = 0
        self._guard_scale = 1.0

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
            for i in range(3):
                self._xy[i] = self._xy[i] * decay + features[i] * response
                for j in range(3):
                    self._xx[i][j] = self._xx[i][j] * decay + features[i] * features[j]
            self._labels += 1
        if self._labels < self.MIN_LABELS:
            return
        if self._last_fit_us is not None and now - self._last_fit_us < 1_000_000:
            return
        self._last_fit_us = now
        # Tiny positive-definite system; ridge protects near-constant or
        # correlated features. Solving here avoids per-event numpy overhead.
        ridge = max(10.0, 0.05 * self._mass)
        matrix = [self._xx[i][:] + [self._xy[i]] for i in range(3)]
        for i in range(3):
            matrix[i][i] += ridge
        for col in range(3):
            pivot = matrix[col][col]
            if not isfinite(pivot) or pivot <= 1e-12:
                return
            for j in range(col, 4):
                matrix[col][j] /= pivot
            for i in range(3):
                if i == col:
                    continue
                factor = matrix[i][col]
                for j in range(col, 4):
                    matrix[i][j] -= factor * matrix[col][j]
        weights = [matrix[i][3] for i in range(3)]
        if all(isfinite(w) for w in weights):
            self._weights = weights

    def _guard_update(self, now, mid, spread):
        while self._guard_pending and self._guard_pending[0][0] + self.HORIZON_US <= now:
            observed, old_mid, old_spread, direction = self._guard_pending.popleft()
            if now - observed > self.HORIZON_US + 1_000_000:
                continue
            # Virtual forecast outcomes continue even when new exposure is
            # disabled. This is a quote-cost proxy, not realized trade PnL.
            edge = direction * (mid - old_mid) - max(spread, old_spread)
            edge = max(-20.0, min(20.0, edge))
            dt = self.OBSERVATION_INTERVAL_US if self._guard_last_scored_us is None else max(0, observed-self._guard_last_scored_us)
            self._guard_last_scored_us = observed
            alpha = 1.0 - exp(-min(dt, 5_000_000) / 20_000_000)
            self._guard_score += alpha * (edge - self._guard_score)
            self._guard_count += 1
        if self._guard_count >= 20:
            self._guard_scale = max(0.0, min(1.0, self._guard_score))

    def _send_toward(self, now, target, bid, ask, bid_quantity, ask_quantity):
        cap = int(self.POSITION_LIMIT * self._guard_scale)
        target = max(-cap, min(cap, target))

        if self._pending_id is not None or now - self._last_order_us < self.MIN_ORDER_INTERVAL_US:
            return
        target = max(-self.POSITION_LIMIT, min(self.POSITION_LIMIT, target))
        difference = target - self.inventory
        if difference == 0:
            return
        sign = 1 if difference > 0 else -1
        price = ask if sign > 0 else bid
        available = ask_quantity if sign > 0 else bid_quantity
        capacity = self.POSITION_LIMIT - sign * self.inventory
        quantity = min(abs(difference), self.MAX_ORDER_SIZE, available, capacity)
        if quantity <= 0 or price is None or price <= 0:
            return
        # Positive exchange latency guarantees the returned id is recorded
        # before ACCEPTED/fill callbacks. IOC residuals never rest.
        order_id = self.send_order(OrderRequest(
            side=Side.BUY if sign > 0 else Side.SELL,
            price=price, quantity=quantity, order_type=OrderType.IOC,
        ))
        self._pending_id = order_id
        self._pending_side = sign
        self._pending_remaining = quantity
        self._last_order_us = now

    def on_order_book_change(self, snapshot, trades):
        now = snapshot.timestamp_us
        if self._flow_us is not None:
            decay = exp(-max(0, now - self._flow_us) / 1_000_000)
            self._flow_net *= decay
            self._flow_volume *= decay
        self._flow_us = now
        for trade in trades:
            # Our own IOC fills are not independent buying/selling pressure.
            if trade.taker_owner != 'market':
                continue
            self._flow_net += trade.quantity if trade.book_side == 'ask' else -trade.quantity
            self._flow_volume += trade.quantity
            self._last_market_trade_us = trade.timestamp_us

        bid = ask = None
        bid_quantity = ask_quantity = 0
        for order in snapshot.bids:
            if order.owner != 'market':
                continue
            if bid is None:
                bid = order.price
            if order.price != bid:
                break
            bid_quantity += order.quantity
        for order in snapshot.asks:
            if order.owner != 'market':
                continue
            if ask is None:
                ask = order.price
            if order.price != ask:
                break
            ask_quantity += order.quantity

        # A one-sided book has no trustworthy mid. Reduce inventory only
        # when the opposite market side exists; never fabricate a price.
        if bid is None or ask is None:
            if self._one_sided_since_us is None:
                self._one_sided_since_us = now
            if now - self._one_sided_since_us >= 100_000 and (
                (self.inventory > 0 and bid is not None) or (self.inventory < 0 and ask is not None)
            ):
                self._send_toward(now, 0, bid, ask, bid_quantity, ask_quantity)
            return
        self._one_sided_since_us = None
        if bid >= ask:
            return
        mid = (bid + ask) * 0.5
        spread = ask - bid
        if self._feature_us is None or now - self._feature_us > 10_000_000:
            self._fast_mid = self._slow_mid = mid
            self._observations.clear()
        else:
            elapsed = max(0, now - self._feature_us)
            self._fast_mid += (1.0 - exp(-elapsed / 5000000)) * (mid - self._fast_mid)
            self._slow_mid += (1.0 - exp(-elapsed / 30000000)) * (mid - self._slow_mid)
        self._feature_us = now
        features = (
            self._flow_net / (1.0 + self._flow_volume),
            max(-5.0, min(5.0, self._fast_mid - self._slow_mid)),
            (bid_quantity - ask_quantity) / (bid_quantity + ask_quantity),
        )
        # Causal EMA displacement in ticks. Fixed hypotheses, no fitted path.
        signal = 1 * (self._fast_mid-self._slow_mid)
        if abs(signal) > max(1.0, spread) and spread <= 2:
            target = self.POSITION_LIMIT if signal > 0 else -self.POSITION_LIMIT
        elif self.inventory * signal > 0 and abs(signal) > 0.25:
            target = self.inventory
        else:
            target = 0
        self._target = target
        self._send_toward(now,target,bid,ask,bid_quantity,ask_quantity)

    def on_private_order_update(self, event):
        if event.order_id != self._pending_id:
            return
        if event.status in (OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED):
            self.inventory += self._pending_side * event.filled_quantity
            self.cash -= self._pending_side * event.filled_quantity * event.fill_price
            self._pending_remaining = event.remaining_quantity
        if event.status in (OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED):
            self._pending_id = None
            self._pending_side = 0
            self._pending_remaining = 0
