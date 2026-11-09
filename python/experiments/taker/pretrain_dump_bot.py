"""The dataset bot of `experiments.taker.pretrain_forecast` (8 Nov, round 3): R3-F1 as it is, plus a dump of every ridge
observation's (features, label) once its 400-ms label matures, to a float64 binary file.

Run by `pretrain_forecast dump` through the starter's simulator (`exchange-simulator --strategy THIS --backtest TAPE`),
with PRETRAIN_DUMP = the output file and PRETRAIN_BASE = the bot to subclass (default R3-F1). A row: t (s), mid,
response (the mid's move to the first book event 400 ms or more later, clipped at +-20, as the bot's own label),
the online ridge's forecast stored at the observation, inventory, the base bot's FEATURE_COUNT features, then EXTRA
cheap extras (`extras` below; the candidate P1 computes the same ones the same way).
"""
import atexit
import importlib.util
import os
from array import array
from math import exp, log1p
from pathlib import Path

_BASE = os.environ.get("PRETRAIN_BASE") or str(
    Path(__file__).resolve().parents[2] / "bots" / "qminers" / "candidates" / "r3_F1_latent_filter.py")
_spec = importlib.util.spec_from_file_location("pretrain_base_bot", _BASE)
_base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_base)

EXTRA = 14


class AExtras:
    """The extras' running state, updated on every valid book event before the forecast (the same code is in P1)."""

    def __init__(self):
        self.t = None
        self.mid = None
        self.v1 = self.v10 = 0.0
        self.t_wide = -10**12
        self.t_move = -10**12
        self.last_move = 0.0
        self.fsq = 0.0
        self.fbig = 0.0

    def update(self, now, bid, ask, trades):
        mid = (bid+ask)*0.5
        dt = 0 if self.t is None else max(0, now-self.t)
        self.t = now
        if dt:
            d1 = exp(-dt/1e6)
            self.v1 *= d1
            self.v10 *= exp(-dt/1e7)
            self.fsq *= d1
            self.fbig *= d1
        if self.mid is not None and mid != self.mid:
            move = mid-self.mid
            self.v1 += abs(move)
            self.v10 += abs(move)
            self.t_move = now
            self.last_move = move
        self.mid = mid
        if ask-bid >= 2:
            self.t_wide = now
        if trades:
            lots = {}
            for trade in trades:
                if trade.taker_owner != 'market':
                    continue
                row = lots.setdefault(trade.taker_order_id, [1 if trade.book_side == 'ask' else -1, 0])
                row[1] += trade.quantity
            for direction, q in lots.values():
                self.fsq += direction*q**0.5
                if q > abs(self.fbig):
                    self.fbig = direction*q

    def features(self, now, bot, snapshot, bid, ask):
        mid = (bid+ask)*0.5
        bq = aq = b2 = a2 = 0
        for orders, touch, sgn in ((snapshot.bids, bid, -1), (snapshot.asks, ask, 1)):
            q1 = q2 = 0
            for order in orders:
                if order.owner != 'market':
                    continue
                d = (order.price-touch)*sgn
                if d == 0:
                    q1 += order.quantity
                elif d == 1:
                    q2 += order.quantity
                elif d > 1:
                    break
            if sgn < 0:
                bq, b2 = q1, q2
            else:
                aq, a2 = q1, q2
        up = dn = 0.0
        raw = 0.0
        p = bot._lf_p
        if p is not None:
            base = bot._lf_base
            m = 0.0
            for i, v in enumerate(p):
                g = base+i+0.5-mid
                m += v*g
                if g >= 0.5:
                    up += v
                elif g <= -0.5:
                    dn += v
            raw = max(-10.0, min(10.0, m))
        fb = self.fbig
        return (min(5, ask-bid),
                log1p(bq)-log1p(aq),
                (log1p(bq)+log1p(aq))/5.0,
                min(20.0, self.v1)/5.0,
                min(200.0, self.v10)/50.0,
                min(10.0, (now-self.t_wide)/1e6),
                min(5.0, (now-self.t_move)/1e6),
                max(-5.0, min(5.0, self.last_move)),
                max(-50.0, min(50.0, self.fsq))/10.0,
                (1 if fb > 0 else -1 if fb < 0 else 0)*log1p(abs(fb))/5.0,
                up, dn, raw,
                log1p(b2)-log1p(a2))


class APretrainDump(_base.PassiveStrategy):
    def __init__(self):
        super().__init__()
        self._dump_path = os.environ.get("PRETRAIN_DUMP")
        self._dump_buf = array('d')
        self._dump_pending = {}
        self._x = AExtras()
        if self._dump_path:
            open(self._dump_path, "wb").close()
            atexit.register(self._dump_flush)

    def _dump_flush(self):
        if self._dump_path and self._dump_buf:
            with open(self._dump_path, "ab") as f:
                self._dump_buf.tofile(f)
            self._dump_buf = array('d')

    def _learn(self, now, mid):
        for observed_us, old_mid, features, stored in self._observations:
            if observed_us+self.HORIZON_US > now:
                break
            extra = self._dump_pending.pop(observed_us, None)
            if now-observed_us > self.HORIZON_US+1_000_000 or extra is None:
                continue
            response = max(-20.0, min(20.0, mid-old_mid))
            self._dump_buf.extend((observed_us*1e-6, old_mid, response, stored, extra[0]))
            self._dump_buf.extend(features)
            self._dump_buf.extend(extra[1])
            if len(self._dump_buf) > 400_000:
                self._dump_flush()
        super()._learn(now, mid)

    def on_order_book_change(self, snapshot, trades):
        before = self._last_observation_us
        n = len(self._observations)
        super().on_order_book_change(snapshot, trades)
        now = snapshot.timestamp_us
        bid, ask = self._cached_bid, self._cached_ask
        if self._cached_time != now or bid is None:
            return
        self._x.update(now, bid, ask, trades)
        if self._last_observation_us == now and before != now and self._observations:
            self._dump_pending[now] = (self.inventory, self._x.features(now, self, snapshot, bid, ask))
