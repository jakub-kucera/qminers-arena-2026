"""R4-MH3 (8 Nov, round 4, 08:05): R4-MH1 with the second extra ridge at 600 ms instead of 1 s (Rust: F5's line and --set MH=1 --set MH_US1=100000 --set MH_US2=600000; round4_public 1,042,419, +13.0k over F5, 5 of 6 paired 1,000-s segments won; the round-4 synthetic tapes wide6 seed511-513 +6.1k / -1.2k / +7.1k; r3 -6.5k, r2 -0.4k, r1 +1.5k). The notes of R4-MH1 follow.

R4-MH1 (8 Nov, round 4, 07:55): R3-F5 plus two more ridges at 100 ms and 1 s whose forecasts enter the main ridge as two features (Rust: F5's line and --set MH=1 --set MH_US2=1000000; round4_public 1,051,494 against F5's 1,029,443, +22.1k, every paired 1,000-s segment won, t 1.99; r3 -4.8k, r2 -1.4k, r1 +1.2k, five r3b seeds -5.1k). Built from R3-F10's port with BLEND_W 0 and MH 1. The notes of R3-F10 follow.

R3-F10 (8 Nov, round 3, 05:00): R3-F5 plus Rust ridge_maker's multi-horizon options, ported line for line. BLEND_W (with H2_US): a second ridge on the same features at the H2_US horizon, unweighted (no Huber), prediction = (1-W) p1 + W p2 once it has MIN_LABELS labels. MH (with MH_US1 / MH_US2): two more unweighted ridges on the base features at those horizons, their clamped forecasts two more inputs of the main model. OBS_CAP: every model's observation queue (64: F5's). BLEND_W 0, MH 0, OBS_CAP 64 is R3-F5 exactly. The Rust twin: R3-F5's --set line and --set BLEND_W=.. --set H2_US=.. --set MH=.. --set MH_US1=.. --set MH_US2=.. --set OBS_CAP=.. (Rust's OBS_CAP 0 is 64). The notes of R3-F5 follow.

R3-F5 (8 Nov, round 3, 03:15): R3-F3 with a state-dependent take bar: TAKE_EDGE 0.25 instead of 0.15, except for TAKE_JUMP_HOLD_MS after the mid moved TAKE_JUMP ticks or more within TAKE_JUMP_MS (a jump), when the bar is TAKE_JUMP_EDGE 0.15 (F3's). The takes between 0.15 and 0.25 over half the spread lose on round 3's and round 2's tapes away from jumps (IDEAS.md, "R3-F5"); round 1's calm tape loses with it. TAKE_JUMP = 0 with TAKE_EDGE 0.15 is R3-F3 exactly. The Rust twin: R3-B1's --set line and --set FILTER=1 --set FT_EDGE=0.25 --set FT_JUMP=3 --set FT_JUMP_HOLD_MS=5000 --set FT_JUMP_EDGE=0.15. The notes of R3-F3 follow.

R3-F3 (8 Nov, round 3): R3-B1 (R2-L9 plus R2-L8's speed-switched one-lot quotes) plus R3-F1's latent-price filter: three ridge features from a hidden-Markov filter of the generator's latent reference bid (experiments/day/latent_filter.py, the offline copy; r3_F1_latent_filter.py, the same code on R2-L9). FILTER = 0 is R3-B1 exactly. The notes of R3-B1 follow.

R3-B1 (8 Nov, round 3, 00:30): R2-L9 (the Huber-robust pure taker, +873,719 on validation) plus R2-L8's speed-switched one-lot quotes: QUOTE_SIZE 1, used only while the 5-s decayed |mid change| rate is below QS_RATE 2.5 ticks/s, else none. QS_RATE 0 reproduces R2-L9 exactly (the rate is never below 0). The notes of R2-L9 follow.

T2-derived structural taker hypothesis: t2_liquidity_features. Original source supplied by another session. No validation score for this alteration; strict all-live reservation accounting retained.

Round-2 hypothesis; performance on round-2 data is unknown.
Uses only current/past public information and causally matured labels.
"""
from collections import deque
from math import exp, ceil, floor, isfinite

from simulator.models import OrderRequest, OrderStatus, OrderType, Side
from simulator.strategy import BaseStrategy

QS_RATE = 2.5  # quote one lot only while the 5-s |mid change| rate is below this (ticks/s); else pure taker
TAKE_MAXSPREAD = 1  # the forecast take fires only while the spread is at most this many ticks (99: no limit)
TAKE_ROOM_LIVE = 1  # R2-T2: the take's room is EXPOSURE - pos - every live same-side order's lots (0: R2-T1, EXPOSURE - pos)
FILTER = 1  # R3-F1: the latent-price filter's three features in the ridge (0: R3-B1 exactly)
FILTER_W = 8  # the filter's grid: lb within bid - W .. bid + W
FILTER_RATE = 2.0  # the latent's random walk, steps a second each way
FILTER_EPS = 0.01  # the likelihood floor (an insert the model cannot explain)
FILTER_PI = (0.55, 0.39, 0.06)  # P(k): an insert k ticks behind the latent touch (round 1's offsets)
FILTER_IMPACT = 3.0  # x tape_gen's impact table (round 1's 5-s mid move by size); round 2's best 3
FILTER_SQRT_C = 0.0  # > 0: Phase 1's rule instead of the table, a fill of q lots moves lb FILTER_SQRT_C * sqrt(q) ticks (r1 0.024, r2 0.0365)
FILTER_DEPTH = 6  # only inserts within this many ticks of the previous touch are observed
# tape_gen's round-1 impact table: (max lots, mean 5-s mid move in ticks)
FILTER_TABLE = ((10, 0.097), (30, 0.111), (60, 0.161), (120, 0.254), (250, 0.349), (500, 0.468), (1000, 0.704), (10**9, 0.903))
TAKE_JUMP = 3.0  # R3-F5: a jump is the mid TAKE_JUMP ticks or more from the oldest mid within TAKE_JUMP_MS (0: off)
TAKE_JUMP_MS = 200
TAKE_JUMP_HOLD_MS = 5000  # for this long after a jump, the take's bar is TAKE_JUMP_EDGE (if lower than TAKE_EDGE)
TAKE_JUMP_EDGE = 0.15
BLEND_W = 0.0 # R3-F10: the second model's weight in the prediction (0: off, F5)
H2_US = 150000  # the second model's horizon
MH = 1 # 1: the forecasts of two more ridges at MH_US1 / MH_US2 as two more features of the main model (0: off, F5)
MH_US1 = 100000 
MH_US2 = 600000 
OBS_CAP = 64  # every model's observation queue (F5: 64); a horizon past OBS_CAP * 20 ms loses its labels
BASE_COUNT = 39 if FILTER else 36


class _Ridge:
    """An unweighted online ridge of the mid's change over horizon_us (Rust ridge_maker's m2 and MH models): the
    main model's label timing, decay, ridge and refit, without Huber's weights."""

    def __init__(self, horizon_us, n):
        self.horizon_us = horizon_us
        self.n = n
        self.observations = deque(maxlen=OBS_CAP)
        self.last_fit_us = self.last_label_us = None
        self.labels = 0
        self.mass = 0.0
        self.xx = [[0.0] * n for _ in range(n)]
        self.xy = [0.0] * n
        self.weights = [0.0] * n

    def learn(self, now, mid, min_labels, memory):
        n = self.n
        horizon = self.horizon_us
        observations = self.observations
        xx, xy = self.xx, self.xy
        rng = range(n)
        while observations and observations[0][0] + horizon <= now:
            observed_us, old_mid, features = observations.popleft()
            if now - observed_us > horizon + 1_000_000:
                continue
            elapsed = 0 if self.last_label_us is None else now - self.last_label_us
            decay = exp(-max(0, elapsed) / memory)
            self.last_label_us = now
            response = max(-20.0, min(20.0, mid - old_mid))
            self.mass = self.mass * decay + 1.0
            for i in rng:
                fi = features[i]
                xy[i] = xy[i] * decay + fi * response
                row = xx[i]
                xx[i] = [row[j] * decay + fi * features[j] for j in rng]
            self.labels += 1
        if self.labels < min_labels:
            return
        if self.last_fit_us is not None and now - self.last_fit_us < 1_000_000:
            return
        self.last_fit_us = now
        ridge = max(30.0, 0.003 * self.mass)
        matrix = [xx[i][:] + [xy[i]] for i in rng]
        for i in rng:
            matrix[i][i] += ridge
        for col in rng:
            top = matrix[col]
            pivot = top[col]
            if not isfinite(pivot) or pivot <= 1e-12:
                return
            top[col:] = [v / pivot for v in top[col:]]
            tail = top[col:]
            for i in rng:
                if i == col:
                    continue
                row = matrix[i]
                factor = row[col]
                row[col:] = [a - factor * b for a, b in zip(row[col:], tail)]
        weights = [matrix[i][n] for i in rng]
        if all(isfinite(w) for w in weights):
            self.weights = weights

    def forecast(self, features):
        return max(-2.0, min(2.0, sum(w * x for w, x in zip(self.weights, features))))


class PassiveStrategy(BaseStrategy):
    IMPACT_HORIZONS=(500000,)
    HUBER_DELTA=6.0
    FEATURE_COUNT = BASE_COUNT + (2 if MH else 0)
    HORIZON_US = 400000
    OBSERVATION_INTERVAL_US = 20000
    MIN_LABELS = 200
    MODEL_MEMORY_US = 100000000000
    POSITION_LIMIT = 100
    QUOTE_SIZE = 1
    REQUOTE_US = 0
    EXPOSURE = 100
    DEAD_ZONE = 0.18     # R2-E1: 0.3
    INSIDE_TH = 0.3
    SKEW_K = 0.025
    FLOW_CUT = 1.1
    CANCEL_FREE = 0.0    # R2-T2: an order being cancelled counts in full toward EXPOSURE until the cancel lands (R2-T1: 1.0, free)
    HEDGE_TICKS = 10
    HEDGE_STALE_US = 100000
    TAKE_EDGE = 0.25  # R3-F3: 0.15; R3-F5: 0.25 away from jumps
    TAKE_SZ = 200
    TAKE_GAP_MS = 50
    TAKE_MODE = 0   # 0 any, 1 only to reduce, 2 only to open or add
    TAKE_INV = 0    # TAKE_MODE 1: the least |inventory| to reduce
    TAKE_THRU = 0
    KEEP_LOTS = 20  # 0: off (R2-E1)
    KEEP_TH = 0.3

    def __init__(self):
        super().__init__()
        self._qs_mid = None
        self._qs_t = 0
        self._qs_rate = 0.0
        self._jump_mids = deque()
        self._jump_until = -10**18
        self._impact_time=None
        self._impact_net=[0.0]*len(self.IMPACT_HORIZONS)
        self._impact_volume=[0.0]*len(self.IMPACT_HORIZONS)
        self._impact_frame=()
        self.inventory = 0
        self.cash = 0
        self._orders = {}
        self._distribution_time=self._distribution_mid=None
        self._distribution_seen={}
        self._distribution_fresh_count=[0.0]*8
        self._distribution_fresh_value=[0.0]*8
        self._distribution_frame=((),())
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
        self._observations = deque(maxlen=OBS_CAP)
        self._m2 = _Ridge(H2_US, self.FEATURE_COUNT) if BLEND_W > 0 else None
        self._mh = (_Ridge(MH_US1, BASE_COUNT), _Ridge(MH_US2, BASE_COUNT)) if MH else ()
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
        self._qp_touch = {1: 0, -1: 0}
        self._qp_d = 0.0
        self._lf_n = 2*FILTER_W+1
        self._lf_p = None
        self._lf_base = 0
        self._lf_t = None
        total = sum(FILTER_PI)
        self._lf_pi = tuple(x/total for x in FILTER_PI)
        self._lf_cum = (self._lf_pi[0], self._lf_pi[0]+self._lf_pi[1], 1.0)
        self._lf_moments = None

    # The latent-price filter (R3-F1): a probability vector over lb = _lf_base + i, i < _lf_n.
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

    def _distribution_features(self, now, snapshot, bid, ask, mid):
        if self._distribution_time is not None and now-self._distribution_time<5000 and mid==self._distribution_mid:
            return self._distribution_frame
        dt=0 if self._distribution_time is None else max(0,now-self._distribution_time)
        decay=exp(-dt/200000)
        for i in range(8):
            self._distribution_fresh_count[i]*=decay
            self._distribution_fresh_value[i]*=decay
        seen={}
        counts=[[0.0]*4 for _ in range(2)]
        values=[[0.0]*4 for _ in range(2)]
        touch_counts=[[0.0]*4 for _ in range(2)]
        touch_volume=[0.0,0.0]
        young=[0.0,0.0]
        age=[0.0,0.0]
        age_mass=[0.0,0.0]
        far_count=[0.0,0.0]
        far_value=[0.0,0.0]
        max_size=[0.0,0.0]
        for side,orders in enumerate((snapshot.bids,snapshot.asks)):
            touch=bid if side==0 else ask
            for order in orders:
                if order.owner!='market':
                    continue
                distance=abs(order.price-touch)
                first=self._distribution_seen.get(order.order_id,now)
                seen[order.order_id]=first
                if distance>4:
                    far_count[side]+=1
                    far_value[side]+=order.price-mid
                    continue
                q=order.quantity
                group=0 if q<=10 else 1 if q<=50 else 2 if q<=200 else 3
                counts[side][group]+=1
                values[side][group]+=order.price-mid
                if distance==0:
                    touch_counts[side][group]+=1
                    touch_volume[side]+=q
                    max_size[side]=max(max_size[side],q)
                    age[side]+=min(2.0,(now-first)/1000000)
                    age_mass[side]+=1
                    if now-first<=100000:
                        young[side]+=1
                if order.order_id not in self._distribution_seen:
                    k=2*group+side
                    self._distribution_fresh_count[k]+=1
                    self._distribution_fresh_value[k]+=order.price
        self._distribution_seen=seen
        odd=[]
        even=[min(10,ask-bid),min(10000,sum(touch_volume))/1000]
        for g in range(4):
            b,a=counts[0][g],counts[1][g]
            odd.extend(((b-a)/(1+b+a),
                (values[0][g]+values[1][g])/(1+b+a),
                (touch_counts[0][g]-touch_counts[1][g])/(1+touch_counts[0][g]+touch_counts[1][g])))
            cb,ca=self._distribution_fresh_count[2*g:2*g+2]
            vb,va=self._distribution_fresh_value[2*g:2*g+2]
            odd.extend(((cb-ca)/(1+cb+ca),max(-10,min(10,(vb+va-mid*(cb+ca))/(1+cb+ca)))))
            even.extend((min(40,b+a)/10,min(80,cb+ca)/10))
        odd.extend(((young[0]-young[1])/(1+young[0]+young[1]),
            age[0]/(1+age_mass[0])-age[1]/(1+age_mass[1]),
            (far_value[0]+far_value[1])/(1+far_count[0]+far_count[1]),
            (max_size[0]-max_size[1])/(1+max_size[0]+max_size[1])))
        even.extend(((young[0]+young[1])/(1+sum(age_mass)),
            sum(age)/(1+sum(age_mass)),min(100,sum(far_count))/10))
        self._distribution_frame=(tuple(odd),tuple(even))
        self._distribution_time=now
        self._distribution_mid=mid
        return self._distribution_frame

    def _impact_features(self,now,trades):
        elapsed=0 if self._impact_time is None else max(0,now-self._impact_time)
        self._impact_time=now
        net=volume=0
        for trade in trades:
            if trade.taker_owner=='market':
                net+=trade.quantity if trade.book_side=='ask' else -trade.quantity
                volume+=trade.quantity
        values=[]
        for i,horizon in enumerate(self.IMPACT_HORIZONS):
            decay=exp(-elapsed/horizon)
            self._impact_net[i]=self._impact_net[i]*decay+net
            self._impact_volume[i]=self._impact_volume[i]*decay+volume
            signed=self._impact_net[i];gross=self._impact_volume[i]
            values.extend((max(-3.0,min(3.0,signed/500.0)),
                signed/(1+gross)*min(9.0,gross/500.0)**0.5))
        return tuple(values)

    def _learn(self, now, mid):
        # Labels mature strictly after observation + horizon. Large gaps
        # are discarded instead of silently changing the prediction horizon.
        # R3-F10: the same arithmetic as F5's loops, element for element, as list comprehensions (faster, the same bits)
        rng = range(self.FEATURE_COUNT)
        xx, xy = self._xx, self._xy
        while self._observations and self._observations[0][0] + self.HORIZON_US <= now:
            observed_us, old_mid, features, stored_forecast = self._observations.popleft()
            if now - observed_us > self.HORIZON_US + 1_000_000:
                continue
            elapsed = 0 if self._last_label_us is None else now - self._last_label_us
            decay = exp(-max(0, elapsed) / self.MODEL_MEMORY_US)
            self._last_label_us = now
            response = max(-20.0, min(20.0, mid - old_mid))
            residual=abs(response-stored_forecast)
            weight=min(1.0,self.HUBER_DELTA/max(1e-12,residual))
            self._mass = self._mass * decay + weight
            for i in rng:
                wf = weight * features[i]
                xy[i] = xy[i] * decay + wf * response
                row = xx[i]
                xx[i] = [row[j] * decay + wf * features[j] for j in rng]
            self._labels += 1
        if self._labels < self.MIN_LABELS:
            return
        if self._last_fit_us is not None and now - self._last_fit_us < 1_000_000:
            return
        self._last_fit_us = now
        # Tiny positive-definite system; ridge protects near-constant or
        # correlated features. Solving here avoids per-event numpy overhead.
        ridge = max(30.0, 0.003 * self._mass)
        matrix = [xx[i][:] + [xy[i]] for i in rng]
        for i in rng:
            matrix[i][i] += ridge
        for col in rng:
            top = matrix[col]
            pivot = top[col]
            if not isfinite(pivot) or pivot <= 1e-12:
                return
            top[col:] = [v / pivot for v in top[col:]]
            tail = top[col:]
            for i in rng:
                if i == col:
                    continue
                row = matrix[i]
                factor = row[col]
                row[col:] = [a - factor * b for a, b in zip(row[col:], tail)]
        weights = [matrix[i][self.FEATURE_COUNT] for i in rng]
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
        self._orders[oid] = [sign,price,quantity,False,False,now,0,0]
        self._hedge_id = oid

    def _take(self, now, signal, spread, bid, ask):
        if spread > TAKE_MAXSPREAD:
            return
        edge = self.TAKE_EDGE
        if TAKE_JUMP > 0 and now < self._jump_until:
            edge = min(edge, TAKE_JUMP_EDGE)
        need = edge + 0.5*spread
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
        if TAKE_ROOM_LIVE:
            room -= reserved  # R2-T2: every live same-side order (a one-lot quote, one being cancelled, the hedge) can fill first
        quantity = min(self.TAKE_SZ,room,self.POSITION_LIMIT-pos-reserved)
        if quantity <= 0:
            return
        price = ask+self.TAKE_THRU if sign > 0 else max(1,bid-self.TAKE_THRU)
        oid = self.send_order(OrderRequest(side=Side.BUY if sign > 0 else Side.SELL,
            price=price,quantity=quantity,order_type=OrderType.IOC))
        self._orders[oid] = [sign,price,quantity,False,False,now,now+1_000_000,0]
        self._take_last = now

    def _cancel(self, order_id):
        record = self._orders[order_id]
        if record[3] and not record[4]:
            record[4] = True
            self.cancel_order(order_id)

    def _preserve(self, oid, record, sign, price):
        # Keep a resting touch order's queue place: shrink it to KEEP_LOTS instead of cancelling it.
        if price is None:
            return False
        if not record[3] or record[4] or oid == self._hedge_id or record[1] != self._qp_touch[sign]:
            return False
        if oid not in self.queue_ahead:
            return False
        if self.KEEP_LOTS > 0 and sign*self._qp_d >= -self.KEEP_TH:
            if record[2] > self.KEEP_LOTS and (record[7] == 0 or record[7] > self.KEEP_LOTS):
                self.modify_order(oid, self.KEEP_LOTS)
                record[7] = self.KEEP_LOTS
            return True
        return False

    def _quote(self, now, sign, price):
        current = [(oid,r) for oid,r in self._orders.items() if r[0] == sign]
        changing = False
        for oid,record in current:
            # A forecast take (record[6], its exemption's end) is not cancelled by the re-quote.
            if (price is None or record[1] != price) and now >= record[6]:
                if self._preserve(oid, record, sign, price):
                    continue
                self._cancel(oid)
                changing = True
        if len(current) >= 8:
            return
        if price is None or price <= 0 or now-self._last_action[sign] < self.REQUOTE_US:
            return
        reserved = sum(r[2] for r in self._orders.values() if r[0] == sign)
        effective=reserved
        quantity=min(self.QUOTE_SIZE if self._qs_rate < QS_RATE else 0,self.EXPOSURE-sign*self.inventory-effective,
                     self.POSITION_LIMIT-sign*self.inventory-reserved)
        if quantity <= 0 or (current and quantity < 1):
            return
        order_id = self.send_order(OrderRequest(side=Side.BUY if sign > 0 else Side.SELL,
            price=price, quantity=quantity, order_type=OrderType.LIMIT))
        self._orders[order_id] = [sign,price,quantity,False,False,now,0,0]
        self._last_action[sign] = now

    def on_order_book_change(self, snapshot, trades):
        now = snapshot.timestamp_us
        elapsed = 0 if self._last_us is None else max(0,now-self._last_us)
        self._last_us = now
        self._impact_frame=self._impact_features(now,trades)
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
        if FILTER:
            self._lf_observe(now,snapshot,trades,current)
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
        if self._qs_mid is not None:
            k = exp(-max(0, now - self._qs_t) / 5000000)
            self._qs_rate = self._qs_rate * k + abs(mid - self._qs_mid) / 5.0
        self._qs_mid, self._qs_t = mid, now
        if TAKE_JUMP > 0:
            jumps = self._jump_mids
            jumps.append((now, mid))
            while jumps and jumps[0][0] < now - TAKE_JUMP_MS*1000:
                jumps.popleft()
            if jumps and abs(mid - jumps[0][1]) >= TAKE_JUMP:
                self._jump_until = now + TAKE_JUMP_HOLD_MS*1000
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
            if self._m2 is not None:
                self._m2.observations.clear()
            for model in self._mh:
                model.observations.clear()
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
        self._distribution_features(now,snapshot,bid,ask,mid)
        young=self._distribution_frame[0][20]
        dispersion=min(3.0,self._distribution_frame[1][-1])
        features+=(young,young*dispersion,flow*dispersion,count_imbalance*dispersion)
        features+=self._impact_frame+(max(-3.0,min(3.0,self._impact_net[0]/(1+(aq if self._impact_net[0]>=0 else bq)))),)
        if FILTER:
            features+=self._lf_features(mid)
        base = features
        if MH:
            # Rust: the MH models learn first, then their forecasts (0 before MIN_LABELS) extend the features
            extra = ()
            for model in self._mh:
                model.learn(now,mid,self.MIN_LABELS,self.MODEL_MEMORY_US)
            for model in self._mh:
                extra += (model.forecast(base) if model.labels >= self.MIN_LABELS else 0.0,)
            features = base+extra
        self._learn(now,mid)
        m2 = self._m2
        if m2 is not None:
            m2.learn(now,mid,self.MIN_LABELS,self.MODEL_MEMORY_US)
        if now-self._last_observation_us >= self.OBSERVATION_INTERVAL_US:
            stored_forecast=max(-2.0,min(2.0,sum(w*x for w,x in zip(self._weights,features))))
            self._observations.append((now,mid,features,stored_forecast))
            if m2 is not None:
                m2.observations.append((now,mid,features))
            for model in self._mh:
                model.observations.append((now,mid,base))
            self._last_observation_us = now
        prediction = 0.25*spread*imbalance
        if self._labels >= self.MIN_LABELS:
            prediction = max(-2.0,min(2.0,sum(w*x for w,x in zip(self._weights,features))))
            if m2 is not None and m2.labels >= self.MIN_LABELS:
                prediction = (1.0-BLEND_W)*prediction+BLEND_W*m2.forecast(features)
        fair = mid + 1.0*prediction + 0.0*0.25*spread*imbalance - skew
        self._qp_d = fair-mid
        self._qp_touch = {1: bid, -1: ask}
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
            # A failed cancel or modify can arrive after the original order
            # filled; unknown ids are ignored.
            if not record[3]:
                del self._orders[event.order_id]
            else:
                record[4] = False
                record[7] = 0
        elif event.status == OrderStatus.MODIFIED:
            record[2] = event.remaining_quantity
            record[7] = 0

        was_hedge = event.order_id == self._hedge_id
        if was_hedge and event.status in (OrderStatus.FILLED,OrderStatus.CANCELED,OrderStatus.REJECTED):
            self._hedge_id = None
        if (not was_hedge and self._desired_time is not None and 0 <= event.timestamp_us-self._desired_time <= 5000
                and event.status in (OrderStatus.CANCELED,)):
            self._quote(event.timestamp_us,1,self._desired_buy)
            self._quote(event.timestamp_us,-1,self._desired_sell)

        if was_hedge or event.status in (OrderStatus.FILLED,OrderStatus.PARTIALLY_FILLED):
            self._hedge(event.timestamp_us)