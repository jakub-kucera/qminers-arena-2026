"""R3-S2 (8 Nov, round 3): a two-sided touch maker that quotes only in quiet markets, with no forecast at all.

experiments.day.r3_edges: a one-lot fill at the front of the touch earns +0.17 ticks (1 s) in round 3's calm blocks and
+0.12 in volatile blocks away from jumps, but -0.70 within 3 s before to 10 s after a jump. With no quote within 10 s
of a 1-s mid move of 3+ ticks, a front fill at a 1-tick spread earns +0.14 / +0.23 (1 / 5 s) on round 3, +0.21 / +0.20
on round 2 and +0.23 / +0.23 on round 1. So the bot quotes QUOTE lots at both touches while the market's spread is at
most MAX_SPREAD, no 1-s mid move of JUMP_TICKS+ happened in the last COOL_S seconds, and the new inserts' width (mean
ask insert minus mean bid insert over the last 0.5 s, Phase 1's precursor of a jump) is below WIDTH_MAX. Past SKEW
lots it quotes only the side that reduces the position; |position + every live order on a side| stays within LIMIT.
"""
from collections import deque

from simulator.models import OrderRequest, OrderStatus, OrderType, Side
from simulator.strategy import BaseStrategy

QUOTE = 50  # lots a quote (round3_public: 20 / 50 19,400 / 31,843)
LIMIT = 100  # |position + live lots on the side| at most this (the penalty starts above 100)
SKEW = 60  # past this many lots, quote only the reducing side
MAX_SPREAD = 1  # quote only while the market's spread is at most this many ticks
JUMP_TICKS = 3  # a 1-s mid move of this many ticks is a jump ...
COOL_S = 10.0  # ... and no quote for this many seconds after one
WIDTH_MAX = 4.5  # no quote while the last 0.5 s of new inserts are this wide (ticks); 99: off
WIDTH_MIN_N = 10  # the width counts only with this many inserts on each side


class QuietMakerStrategy(BaseStrategy):
    def __init__(self):
        super().__init__()
        self.inventory = 0
        self._orders = {}  # id -> [sign, price, lots left, accepted, cancelling]
        self._known_market = set()
        self._mids = deque()  # (t_us, mid) over the last second
        self._last_jump = -10**12
        self._ins = deque()  # (t_us, sign, price) of new market inserts over the last 0.5 s
        self._sum = [0.0, 0.0]
        self._cnt = [0, 0]

    def _cancel(self, oid):
        rec = self._orders.get(oid)
        if rec is None or rec[4]:
            return
        rec[4] = True
        self.cancel_order(oid)

    def _sync(self, sign, price):
        have = False
        for oid, rec in list(self._orders.items()):
            if rec[0] != sign or rec[4]:
                continue
            if price is not None and rec[1] == price and not have:
                have = True
            else:
                self._cancel(oid)
        if price is None or have:
            return
        live = sum(rec[2] for rec in self._orders.values() if rec[0] == sign)
        qty = min(QUOTE, LIMIT - sign*self.inventory - live)
        if qty <= 0:
            return
        oid = self.send_order(OrderRequest(side=Side.BUY if sign > 0 else Side.SELL, price=price, quantity=qty, order_type=OrderType.LIMIT))
        self._orders[oid] = [sign, price, qty, False, False]

    def on_order_book_change(self, snapshot, trades):
        now = snapshot.timestamp_us
        bid = ask = None
        for o in snapshot.bids:
            if o.owner == 'market':
                bid = o.price
                break
        for o in snapshot.asks:
            if o.owner == 'market':
                ask = o.price
                break
        current = set()
        known = self._known_market
        for orders, k in ((snapshot.bids, 0), (snapshot.asks, 1)):
            for o in orders:
                if o.owner != 'market':
                    continue
                current.add(o.order_id)
                if o.order_id not in known:
                    self._ins.append((now, k, o.price))
                    self._sum[k] += o.price
                    self._cnt[k] += 1
        self._known_market = current
        while self._ins and now - self._ins[0][0] > 500_000:
            _, k, p = self._ins.popleft()
            self._sum[k] -= p
            self._cnt[k] -= 1
        if bid is None or ask is None or bid >= ask:
            self._sync(1, None)
            self._sync(-1, None)
            return
        mid = (bid+ask)*0.5
        mids = self._mids
        mids.append((now, mid))
        while now - mids[0][0] > 1_000_000:
            mids.popleft()
        if abs(mid - mids[0][1]) >= JUMP_TICKS:
            self._last_jump = now
        quiet = ask-bid <= MAX_SPREAD and now - self._last_jump > COOL_S*1e6
        if quiet and WIDTH_MAX < 99 and self._cnt[0] >= WIDTH_MIN_N and self._cnt[1] >= WIDTH_MIN_N:
            width = self._sum[1]/self._cnt[1] - self._sum[0]/self._cnt[0]
            quiet = width < WIDTH_MAX
        want_bid = quiet and self.inventory < SKEW
        want_ask = quiet and self.inventory > -SKEW
        self._sync(1, bid if want_bid else None)
        self._sync(-1, ask if want_ask else None)

    def on_private_order_update(self, event):
        rec = self._orders.get(event.order_id)
        if rec is None:
            return
        if event.status == OrderStatus.ACCEPTED:
            rec[3] = True
        elif event.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED):
            self.inventory += rec[0]*event.filled_quantity
            rec[2] = event.remaining_quantity
            if event.status == OrderStatus.FILLED or event.remaining_quantity == 0:
                del self._orders[event.order_id]
        elif event.status == OrderStatus.CANCELED:
            del self._orders[event.order_id]
        elif event.status == OrderStatus.REJECTED:
            if not rec[3]:
                del self._orders[event.order_id]
            else:
                rec[4] = False
