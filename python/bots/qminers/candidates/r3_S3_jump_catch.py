"""R3-S3 (8 Nov, round 3): a jump-catch taker, held for seconds, gated by the latent filter.

experiments.day.r3_edges: after a jump's onset the mid keeps going its way for 1-2 s (from onset + 1 s, +2.1 ticks
by + 2 s, t 5.9; then flat, no reversal at 30-120 s). On round3_public's 50-ms samples, the first 0.2-s mid move of
3+ ticks after 2 s without one, bought at the next ask and sold at the bid 0.5 / 1 / 2 s later, makes +0.5 / +1.1 /
+1.5 ticks a lot (327 a 6,000 s); with the filter's gap 2+ ticks the move's way and a 1-tick spread +1.7 / +2.8 / +4.1
(153). On round 2 the same loses (-0.5 to -1.2): its jumps came as wide-spread sweeps with the filter already caught
up (gap the move's way +0.5 against +2.1 on round 3). So this is a round-3 bet, kept for its low tie to the forecast
taker's 400-ms horizon. The bot: on that trigger (JUMP_TICKS in LOOK_US, REARM_US apart, gap >= GAP_MIN the move's
way, spread <= MAX_SPREAD) an IOC SLIP ticks through the far touch takes the position to QTY lots the move's way;
HOLD_US later an IOC EXIT_SLIP ticks through the touch flattens it (retried until flat). A trigger the other way flips.
"""
from collections import deque
from math import isfinite

from simulator.models import OrderRequest, OrderStatus, OrderType, Side
from simulator.strategy import BaseStrategy

QTY = 100  # the position a trigger takes (lots, at most 100: the penalty)
JUMP_TICKS = 3  # the mid's move that triggers ...
LOOK_US = 200_000  # ... within this window
REARM_US = 2_000_000  # triggers at least this far apart
GAP_MIN = 2.0  # the filter's gap (E[latent] - mid) at least this many ticks the move's way
MAX_SPREAD = 2  # the market's spread at the trigger at most this
HOLD_US = 2_000_000  # flatten this long after the entry
SLIP = 1  # the entry IOC's price: this many ticks through the far touch
EXIT_SLIP = 2  # the exit IOC's price: this many ticks through the touch
FILTER_W = 8  # the filter's grid: lb within bid - W .. bid + W
FILTER_RATE = 2.0  # the latent's random walk, steps a second each way
FILTER_EPS = 0.01  # the likelihood floor (an insert the model cannot explain)
FILTER_PI = (0.55, 0.39, 0.06)  # P(k): an insert k ticks behind the latent touch (round 1's offsets)
FILTER_IMPACT = 3.0  # x tape_gen's impact table (round 1's 5-s mid move by size); round 3's best 3
FILTER_SQRT_C = 0.0  # > 0: the latent moves FILTER_SQRT_C * sqrt(lots) instead of the table
FILTER_DEPTH = 6  # only inserts within this many ticks of the previous touch are observed
FILTER_TABLE = ((10, 0.097), (30, 0.111), (60, 0.161), (120, 0.254), (250, 0.349), (500, 0.468), (1000, 0.704), (10**9, 0.903))


class JumpCatchStrategy(BaseStrategy):
    def __init__(self):
        super().__init__()
        self.inventory = 0
        self._live = {}  # IOC id -> signed lots still able to fill
        self._known_market = {}
        self._cached_bid = self._cached_ask = None
        self._mids = deque()
        self._last_trigger = -10**12
        self._exit_at = None
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

    def _ioc(self, signed, price):
        if signed == 0 or price <= 0:
            return
        oid = self.send_order(OrderRequest(side=Side.BUY if signed > 0 else Side.SELL, price=price, quantity=abs(signed), order_type=OrderType.IOC))
        self._live[oid] = signed

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
        if bid is None or ask is None or bid >= ask or self._lf_p is None:
            return
        mid = (bid+ask)*0.5
        mids = self._mids
        mids.append((now, mid))
        while now - mids[0][0] > LOOK_US:
            mids.popleft()
        pending = sum(self._live.values())
        move = mid - mids[0][1]
        if abs(move) >= JUMP_TICKS and now - self._last_trigger >= REARM_US:
            self._last_trigger = now
            s = 1 if move > 0 else -1
            gap = self._lf_features(mid)[0]
            if gap*s >= GAP_MIN and ask-bid <= MAX_SPREAD:
                need = s*QTY - self.inventory - pending
                if need*s > 0:
                    self._ioc(need, ask+SLIP if s > 0 else bid-SLIP)
                self._exit_at = now + HOLD_US
                return
        if self._exit_at is not None and now >= self._exit_at and not self._live:
            if self.inventory == 0:
                self._exit_at = None
            else:
                self._ioc(-self.inventory, bid-EXIT_SLIP if self.inventory > 0 else ask+EXIT_SLIP)

    def on_private_order_update(self, event):
        signed = self._live.get(event.order_id)
        if signed is None:
            return
        s = 1 if signed > 0 else -1
        if event.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED):
            self.inventory += s*event.filled_quantity
            self._live[event.order_id] = s*event.remaining_quantity
            if event.status == OrderStatus.FILLED or event.remaining_quantity == 0:
                del self._live[event.order_id]
        elif event.status in (OrderStatus.CANCELED, OrderStatus.REJECTED):
            del self._live[event.order_id]
