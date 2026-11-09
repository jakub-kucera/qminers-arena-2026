"""R3-S1 (8 Nov, round 3): a passive maker on the latent filter's gap, the first non-taker of round 3.

experiments.taker.r3_edges: at a 1-tick spread, a fill at the touch earns +0.44-0.48 ticks a lot (1 s) when the latent
filter's gap (E[latent] - mid) is on the maker's side, and -0.02 to -0.83 when it is against, on rounds 1, 2 and 3. So
the bot quotes the touch only on the favoured side: a bid at the best market bid while gap > GAP_ON (kept while
gap > GAP_OFF, the queue place), an ask at the best market ask while gap < -GAP_ON. No take, ever. The position
moves with the gap and comes back when it turns; |position + every live order on a side| stays within LIMIT (orders
being cancelled count until the cancel lands), so the 100-lot penalty never starts. Quotes come off when the
market's spread is above MAX_SPREAD. KEEP2 keeps a quote the touch moved away from by a tick; LEVEL2 also posts
lots a tick behind the favoured touch (a level-2 fill with the gap 0.6+ the maker's way earns +0.72 a lot at 1 s on
round 3, against +0.35 for one at the back of the touch's queue: `experiments.taker.r3_edges`). UNWIND > 0 also quotes the reducing side, at the touch, while |gap| < UNWIND
and |position| >= UNWIND_POS. The filter is R3-F1's (candidates/round3/r3_F1_latent_filter.py, experiments/filter/latent_filter.py).
"""
from math import isfinite

from simulator.models import OrderRequest, OrderStatus, OrderType, Side
from simulator.strategy import BaseStrategy

QUOTE = 100  # lots a quote (round3_public, GAP_ON 0.6, GAP_OFF -0.3: QUOTE 20 / 50 / 100 22.4k / 41.4k / 48.7k)
LIMIT = 100  # |position + live lots on the side| at most this (the penalty starts above 100)
GAP_ON = 0.6  # quote the bid when gap > GAP_ON, the ask when gap < -GAP_ON (QUOTE 50: 0 / 0.3 / 0.6 / 1.0 21.6k / 31.5k / 41.4k / 39.5k)
GAP_OFF = -0.3  # keep a resting bid while gap > GAP_OFF (an ask while gap < -GAP_OFF); GAP_ON 0.6: -0.6 44.5k
MAX_SPREAD = 1  # quote only while the market's spread is at most this many ticks
KEEP2 = 0  # 1: a quote the touch moved away from by one tick stays (its queue place on the new second level)
LEVEL2 = 0  # > 0: also post this many lots one tick behind the favoured touch (r3_edges: +0.72 a lot at 1 s, gap 0.6+)
UNWIND = 0.0  # > 0: also quote the reducing side while |gap| < UNWIND ...
UNWIND_POS = 50  # ... and |position| >= UNWIND_POS
FILTER_W = 8  # the filter's grid: lb within bid - W .. bid + W
FILTER_RATE = 2.0  # the latent's random walk, steps a second each way
FILTER_EPS = 0.01  # the likelihood floor (an insert the model cannot explain)
FILTER_PI = (0.55, 0.39, 0.06)  # P(k): an insert k ticks behind the latent touch (round 1's offsets)
FILTER_IMPACT = 3.0  # x tape_gen's impact table (round 1's 5-s mid move by size); round 3's best 3
FILTER_SQRT_C = 0.0  # > 0: the latent moves FILTER_SQRT_C * sqrt(lots) instead of the table
FILTER_DEPTH = 6  # only inserts within this many ticks of the previous touch are observed
FILTER_TABLE = ((10, 0.097), (30, 0.111), (60, 0.161), (120, 0.254), (250, 0.349), (500, 0.468), (1000, 0.704), (10**9, 0.903))


class GapMakerStrategy(BaseStrategy):
    def __init__(self):
        super().__init__()
        self.inventory = 0
        self._orders = {}  # id -> [sign, price, lots left, accepted, cancelling]
        self._known_market = {}
        self._cached_bid = self._cached_ask = None
        self._lf_n = 2*FILTER_W+1
        self._lf_p = None
        self._lf_base = 0
        self._lf_t = None
        total = sum(FILTER_PI)
        self._lf_pi = tuple(x/total for x in FILTER_PI)
        self._lf_cum = (self._lf_pi[0], self._lf_pi[0]+self._lf_pi[1], 1.0)
        self._lf_moments = None

    # The latent-price filter, copied from R3-F1: a probability vector over lb = _lf_base + i, i < _lf_n.
    def _lf_advance(self, t):
        if self._lf_t is None:
            self._lf_t = t
            return
        dt = t-self._lf_t
        if dt <= 0:
            return
        self._lf_t = t
        a = FILTER_RATE*dt
        if a < 1e-9:
            return
        if a > 0.3:
            a = 0.3
        p = self._lf_p
        n = self._lf_n
        keep = 1.0-2.0*a
        q = [0.0]*n
        prev = 0.0
        for i in range(n):
            cur = p[i]
            q[i] = keep*cur+a*(prev+(p[i+1] if i+1 < n else 0.0))
            prev = cur
        q[0] += a*p[0]
        q[-1] += a*p[-1]
        self._lf_p = q

    def _lf_recenter(self, bid):
        n = self._lf_n
        shift = bid-FILTER_W-self._lf_base
        if shift == 0:
            return
        if abs(shift) >= n:
            self._lf_base = bid-FILTER_W
            self._lf_p = [0.0]*n
            self._lf_p[FILTER_W] = 1.0
            return
        p = self._lf_p
        q = [0.0]*n
        for i in range(n):
            j = i-shift
            j = 0 if j < 0 else n-1 if j >= n else j
            q[j] += p[i]
        self._lf_p = q
        self._lf_base += shift

    def _lf_trade(self, direction, lots):
        if FILTER_SQRT_C > 0:
            m = FILTER_SQRT_C*lots**0.5
        else:
            m = FILTER_IMPACT
            for top,value in FILTER_TABLE:
                if lots <= top:
                    m *= value
                    break
        if m <= 0:
            return
        whole = int(m)
        frac = m-whole
        p = self._lf_p
        n = self._lf_n
        q = [0.0]*n
        for i in range(n):
            v = p[i]
            if v == 0.0:
                continue
            j = i+direction*whole
            k = j+direction
            j = 0 if j < 0 else n-1 if j >= n else j
            k = 0 if k < 0 else n-1 if k >= n else k
            q[j] += v*(1.0-frac)
            q[k] += v*frac
        self._lf_p = q

    def _lf_insert(self, buy, price, bid, ask):
        p = self._lf_p
        n = self._lf_n
        base = self._lf_base
        eps = FILTER_EPS
        pi,cum = self._lf_pi,self._lf_cum
        total = 0.0
        if buy:
            clamp = ask-1
            if price >= clamp:
                for i in range(n):
                    d = base+i-clamp
                    v = p[i]*((eps+(cum[d] if d < 3 else 1.0)) if d >= 0 else eps)
                    p[i] = v
                    total += v
            else:
                for i in range(n):
                    k = base+i-price
                    v = p[i]*(eps+pi[k] if 0 <= k < 3 else eps)
                    p[i] = v
                    total += v
        else:
            clamp = bid+1
            if price <= clamp:
                for i in range(n):
                    d = clamp-1-base-i
                    v = p[i]*((eps+(cum[d] if d < 3 else 1.0)) if d >= 0 else eps)
                    p[i] = v
                    total += v
            else:
                for i in range(n):
                    k = price-1-base-i
                    v = p[i]*(eps+pi[k] if 0 <= k < 3 else eps)
                    p[i] = v
                    total += v
        if total <= 0 or not isfinite(total):
            self._lf_p = [1.0/n]*n
            return
        inv = 1.0/total
        for i in range(n):
            p[i] *= inv

    def _lf_observe(self, now, snapshot, trades, current):
        """Feed the snapshot's market taker fills and its new market orders (against the previous touch) to the filter."""
        bid,ask = self._cached_bid,self._cached_ask
        if bid is None or ask is None or bid >= ask:
            return
        if self._lf_p is None:
            self._lf_base = bid-FILTER_W
            self._lf_p = [0.0]*self._lf_n
            self._lf_p[FILTER_W] = 1.0
        changed = centred = False
        if trades:
            lots = {}
            for trade in trades:
                if trade.taker_owner != 'market':
                    continue
                row = lots.setdefault(trade.taker_order_id,[1 if trade.book_side == 'ask' else -1,0])
                row[1] += trade.quantity
            if lots:
                self._lf_advance(now*1e-6)
                changed = True
                for direction,quantity in lots.values():
                    self._lf_trade(direction,quantity)
        known = self._known_market
        for oid,order in current.items():
            if oid in known:
                continue
            buy = order.side == Side.BUY
            if abs(order.price-(bid if buy else ask)) > FILTER_DEPTH:
                continue
            if not centred:
                if not changed:
                    self._lf_advance(now*1e-6)
                self._lf_recenter(bid)
                changed = centred = True
            self._lf_insert(buy,order.price,bid,ask)
        if changed:
            self._lf_moments = None

    def _lf_features(self, mid):
        if self._lf_p is None:
            return (0.0,0.0,0.0)
        if self._lf_moments is None:
            m = s2 = 0.0
            for i,v in enumerate(self._lf_p):
                m += v*i
                s2 += v*i*i
            self._lf_moments = (self._lf_base+m, max(0.0,s2-m*m)**0.5)
        mean,sd = self._lf_moments
        gap = max(-5.0,min(5.0,mean+0.5-mid))
        return (gap,gap*abs(gap)/3.0,min(3.0,sd))

    def _cancel(self, oid):
        rec = self._orders.get(oid)
        if rec is None or rec[4]:
            return
        rec[4] = True
        self.cancel_order(oid)

    def _sync(self, sign, price):
        """Keep one quote on this side at `price` (None: none) and, with KEEP2, one a tick behind it (a quote the touch
        moved away from keeps its queue place there); with LEVEL2 > 0 post LEVEL2 lots a tick behind too; cancel the
        rest; post only within LIMIT."""
        behind = None if price is None or not (KEEP2 or LEVEL2) else price - sign
        have = have2 = False
        for oid, rec in list(self._orders.items()):
            if rec[0] != sign or rec[4]:
                continue
            if price is not None and rec[1] == price and not have:
                have = True
            elif behind is not None and rec[1] == behind and not have2:
                have2 = True
            else:
                self._cancel(oid)
        if price is None:
            return
        for want, at, lots in ((not have, price, QUOTE), (LEVEL2 > 0 and not have2, behind, LEVEL2)):
            if not want:
                continue
            live = sum(rec[2] for rec in self._orders.values() if rec[0] == sign)
            qty = min(lots, LIMIT - sign*self.inventory - live)
            if qty <= 0:
                return
            oid = self.send_order(OrderRequest(side=Side.BUY if sign > 0 else Side.SELL, price=at, quantity=qty, order_type=OrderType.LIMIT))
            self._orders[oid] = [sign, at, qty, False, False]

    def _resting(self, sign, price):
        return any(rec[0] == sign and rec[1] == price and not rec[4] for rec in self._orders.values())

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
        current = {o.order_id: o for orders in (snapshot.bids, snapshot.asks) for o in orders if o.owner == 'market'}
        self._lf_observe(now, snapshot, trades, current)
        self._known_market = current
        self._cached_bid, self._cached_ask = bid, ask
        if bid is None or ask is None or bid >= ask or ask-bid > MAX_SPREAD or self._lf_p is None:
            self._sync(1, None)
            self._sync(-1, None)
            return
        mid = (bid+ask)*0.5
        gap = self._lf_features(mid)[0]
        want_bid = gap > GAP_ON or (gap > GAP_OFF and (self._resting(1, bid) or (KEEP2 and self._resting(1, bid-1))))
        want_ask = gap < -GAP_ON or (gap < -GAP_OFF and (self._resting(-1, ask) or (KEEP2 and self._resting(-1, ask+1))))
        if UNWIND > 0 and abs(gap) < UNWIND and abs(self.inventory) >= UNWIND_POS:
            if self.inventory > 0:
                want_ask = True
            else:
                want_bid = True
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
                rec[4] = False  # a failed cancel: the order is still live
