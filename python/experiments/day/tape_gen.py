"""A generative model of an Arena tape: fit it to a round's CSV, then draw new tapes in the starter's format (7 Nov, round 1).

The premise: the public tape and the private one are two draws of one generator, so a strategy should be chosen on many
draws of a fitted generator rather than on the one file. The model, fitted from a replay of the tape through our own
price-time book (experiments/day/tape_book.py, the starter's matching):

- **A latent price** (the test: at a 1-tick spread, a bid insert lands at the touch 80% of the time when the mid is up
  0.5 s later and 23% when it is down, asks the mirror image, while the PAST 2 s move changes nothing: inserts centre
  on a price the mid only follows). Modelled as a real-valued latent mid moved only by the aggressive orders: an order
  of q lots moves it impact(q) ticks its way, the mean 5 s mid move after such a trade on the real tape (round 1: 0.10
  for 10 lots or fewer up to 0.90 over 1,000); the reference bid `lb` is its floor. When `lb` moves, every resting
  order left on the wrong side of it (asks at or below the new lb, bids above) cancels within Exp(`stale_s`) (on top
  of its own clock). Calibrated on round 1 against the profile (the mid's changes a second, its move after a 1-tick
  move): `stale_s` 0.2 s, `jump_rate` 0 (no moves beyond the trades'); `informed` (default 0) sends that share of
  aggressive orders the way the book lags the latent mid; `f_buy_share` (default 0.5) the buys' share of them (a drift);
  `spread2` (default off) centres the inserts on the rounded latent mid one tick off it each side (a 2-tick book); `wide_table` (default off; dropped: the 2-tick share 9.5%) draws
  the inserts at a 2+ tick spread from the tape's own offsets there. Without `continuous` the latent mid moves in whole ticks.
- **Limit inserts (G)**: one Poisson stream (round 1: 180/s, the same rate at a 1- or 2-tick spread), the side a coin
  flip, bids at lb - k and asks at lb + 1 + k (k from round 1's offsets at a 1-tick spread: 0 55%, 1 39%, 2 6%),
  clamped one tick off the other touch (round 1 has no crossing G rows); the size from the empirical sizes of its offset
  class (inside / touch / one behind / deeper).
- **Cancels**: every G order gets a cancel row at insert time + a lifetime drawn from the empirical Insert->Cancel delays
  (round 1: all but 66 of 2.16M G orders have one, filled or not; median 0.34 s, the same by offset and size), so a
  cancel of an order already filled is kept, as in the real tape.
- **Aggressive orders (F)**: a Poisson stream (round 1: 8.0/s, inter-arrival CV 1.00, the side independent of the last:
  P(same) 0.501, and of the past 2 s move), the size from the empirical F sizes, the limit price the opposite touch plus
  an offset from its PMF (round 1: 0 ticks 52%, 1 tick 46%).

The result (IDEAS.md, "A generative model of round 1's tape"; `experiments.day.tape_eval` runs the candidates on
the draws): the profile and the candidates' PnL within ~15%, the order F3 < F5 < F6 kept, but F7 below F6 (on the
real tape above); the 2-tick spread's time share is a third of the real one. `--fit` prints the tests behind it.

**v2 (8 Nov, round 3; `experiments.day.gen_calibrate` calibrates it against a validation scoreboard)**: latent options,
all off by default (a draw without them is the same bytes as before) and all needing `continuous`, set in the params'
"latent" or by `--opts JSON`: Phase 1's structure (docs/GENERATOR_PLAN.md) — `impact_sqrt` c (a trade of q lots moves
the latent c sqrt(q), round 2 0.0365, instead of the table), `f_limit_latent` (an IOC's limit at the latent +- that many
ticks), scheduled jumps (`jx_rate_off` / `jx_rate_on` a second in a hidden two-state intensity chain with mean stays
`jx_dwell_off` / `jx_dwell_on` s; lognormal sizes `jx_median`, `jx_logsd` clipped to `jx_min` / `jx_max`; inserts
`jx_warn_k` ticks wider a side `jx_warn_s` s before each; stale orders cancelled within Exp(`jx_stale_s`) after it;
`jx_lead_extra` informed IOC orders a second the jump's way in the `jx_lead_s` s before it, or `jx_after_extra` in the
`jx_after_s` s after it (the real tape's: they follow the latent's jump), sizes at least `jx_lead_min`; the volatile
state's texture: `jx_on_k` wider inserts in it, `jx_warn_sd` a lognormal warning lead, `jx_false_rate` widenings with
no jump, `jx_diff_sd` diffusion); `--latent-out` writes the true latent every 10 ms; and generic ones — `impact_scale`, `impact_delay` / `impact_tau` (a share of the impact released over
time), `jump_df` (Student-t sizes for the `jump_rate` jumps), `jump_stale_s`, `drift_sd` / `drift_tau` (an OU drift),
`vol_states` / `vol_dwell_s` (a Markov volatility multiplier) and `vol_logsd` / `vol_logtau` (a log-OU one) on the
jumps (and the impact with `vol_impact`), `k_vol` (wider inserts at a high multiplier), `place_noise` (inserts
centred on a noisy latent). `--impact-cap` keeps a fitted size bin's impact above 1 tick.

**v3 size laws (opt-in):** `latent.f_size_law` and `latent.g_size_law` replace the
empirical size tables with named laws, measured by `gen_inventory`. Supported:
`{"law": "lognormal", "mu": 4.1, "sigma": 1.4, "rounding": "round"}` (normal
parameters of log size, rounded then clipped at one; floor/ceil also supported),
and `{"law": "uniform", "low": 20, "high": 40}` (inclusive integer bounds).
The F law also supplies informed orders, conditioned on `jx_lead_min`; G's law
applies at every offset. Round 3's G sizes/lifetimes are a mixture: do not replace
them with a single fitted lognormal. Absent these options, every v2 draw is unchanged.

    uv run python -m experiments.day.tape_gen --fit data/arena/round1/round1.csv --params-out P.json
    uv run python -m experiments.day.tape_gen --params P.json --seed N --seconds 12000 --out tape.csv [--opts JSON] \
        [--latent-out latent.csv]   # the true latent mid every 10 ms, the jump chain's state, the jumps since the last row
"""

from __future__ import annotations

import argparse
import heapq
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from experiments.day.tape_book import Book

SPREADS = (1, 2, 3)  # 3 stands for 3+
CLASSES = ("inside", "touch", "behind1", "deeper")
DEEPEST = -30
FIRST_ID = 1_000_001
LATENT_STEP = 0.01  # --latent-out's grid (s)
# the impact table's size bins (lots); fit() fills in each bin's mean mid move 5 s after (ticks, the trade's way)
IMPACT = [[10, 0.097], [30, 0.111], [60, 0.161], [120, 0.254], [250, 0.349], [500, 0.468], [1000, 0.704], [10**9, 0.903]]


def offset_class(d: int) -> str:
    return "inside" if d > 0 else "touch" if d == 0 else "behind1" if d == -1 else "deeper"


def _counts(counter: Counter) -> list[list[int]]:
    return [[int(k), int(v)] for k, v in sorted(counter.items())]


def fit(path: Path, jump_rate: float = 0.0, stale_s: float = 0.2, impact_cap: float = 1.0) -> dict:
    """Replay the tape through Book and collect every distribution the generator draws from, plus the tests."""
    book = Book()
    offsets = {s: Counter() for s in SPREADS}
    sizes = {c: Counter() for c in CLASSES}
    f_sizes, f_offsets = Counter(), Counter()
    inserted = {}
    lifetimes = []
    life_by_class = defaultdict(list)
    life_size = []
    n_g = n_f = n_cancel = 0
    g_by_spread = Counter()
    f_rows = []  # t, side, size
    sides = Counter()
    first = last = None
    mid_t, mid_v = [], []
    with path.open() as fh:
        next(fh)
        for line in fh:
            t, op, oid, side, vol, price, life = line.rstrip("\n").split(",")
            t = float(t)
            first = t if first is None else first
            last = t
            bb, ba = book.best
            spread = ba - bb if bb is not None and ba is not None else None
            if op == "Insert":
                sd = 0 if side == "B" else 1
                p, q = int(price), int(vol)
                if life == "F":
                    n_f += 1
                    opp = ba if sd == 0 else bb
                    f_sizes[q] += 1
                    if opp is not None:
                        f_offsets[(p - opp) if sd == 0 else (opp - p)] += 1
                    f_rows.append((t, sd, q, (bb + ba) / 2 if bb is not None and ba is not None else np.nan))
                    book.insert(oid, sd, p, q, True)
                    continue
                n_g += 1
                sides[sd] += 1
                inserted[oid] = (t, None, q)
                if spread is not None:
                    d = p - bb if sd == 0 else ba - p
                    s = min(spread, 3)
                    g_by_spread[s] += 1
                    offsets[s][max(DEEPEST, min(d, s - 1))] += 1
                    sizes[offset_class(d)][q] += 1
                    inserted[oid] = (t, offset_class(d), q)
                book.insert(oid, sd, p, q, False)
            else:
                n_cancel += 1
                rec = inserted.pop(oid, None)
                if rec is not None:
                    lifetimes.append(t - rec[0])
                    if rec[1]:
                        life_by_class[rec[1]].append(t - rec[0])
                    life_size.append((rec[2], t - rec[0]))
                book.cancel(oid)
            bb, ba = book.best
            if bb is not None and ba is not None and (not mid_v or mid_v[-1] != (bb + ba) / 2):
                mid_t.append(t)
                mid_v.append((bb + ba) / 2)
    duration = last - first if first is not None else 0.0
    lifetimes = np.array(lifetimes)
    f = np.array(f_rows)
    gaps = np.diff(f[:, 0])
    ls = np.array(life_size)
    small = ls[:, 0] <= np.median(ls[:, 0])
    mt, mv = np.array(mid_t), np.array(mid_v)
    after = mv[np.clip(np.searchsorted(mt, f[:, 0] + 5.0, side="right") - 1, 0, len(mv) - 1)]
    move5 = (after - f[:, 3]) * np.where(f[:, 1] == 0, 1, -1)
    impact, lo = [], 0
    for hi in [row[0] for row in IMPACT]:
        sel = (f[:, 2] > lo) & (f[:, 2] <= hi) & ~np.isnan(move5)
        impact.append([hi, round(float(np.clip(move5[sel].mean(), 0, impact_cap)), 4) if sel.any() else 0.0])
        lo = hi
    k_pmf = [[-d, c] for d, c in sorted(offsets[1].items()) if d <= 0]
    return {
        "source": str(path),
        "duration_s": duration,
        "g_rate": n_g / duration,
        "g_bid_share": sides[0] / max(1, n_g),
        "f_rate": n_f / duration,
        "offsets": {str(s): _counts(offsets[s]) for s in SPREADS},
        "sizes": {c: _counts(sizes[c]) for c in CLASSES},
        "lifetime_quantiles": np.quantile(lifetimes, np.linspace(0, 1, 2001)).round(6).tolist(),
        "f_sizes": _counts(f_sizes),
        "f_offsets": _counts(f_offsets),
        "latent": {"continuous": True, "stale_s": stale_s, "jump_rate": jump_rate, "jump_size": 0.5, "informed": 0.0,
                   "k_pmf": k_pmf, "impact": impact, "start_bid": 9999},
        "tests": {
            "g_inserts": n_g, "f_inserts": n_f, "cancels": n_cancel, "g_without_cancel": len(inserted),
            "g_rate_by_spread_state": {str(s): g_by_spread[s] for s in SPREADS},
            "lifetime_median_by_class": {c: float(np.median(v)) for c, v in life_by_class.items()},
            "lifetime_median_small_vs_large_orders": [float(np.median(ls[small, 1])), float(np.median(ls[~small, 1]))],
            "f_side_same_as_previous": float((f[1:, 1] == f[:-1, 1]).mean()),
            "f_interarrival_cv": float(gaps.std() / gaps.mean()),
            "f_per_1000s": np.histogram(f[:, 0], bins=max(1, int(duration // 1000)), range=(0, duration))[0].tolist(),
        },
    }


class Sampler:
    """Draws from a [[value, count], ...] table."""

    def __init__(self, table, rng: np.random.Generator) -> None:
        values = np.array([v for v, _ in table], dtype=np.int64)
        weights = np.array([c for _, c in table], dtype=float)
        self.values = values
        self.cdf = np.cumsum(weights) / weights.sum()
        self.rng = rng
        self.buffer = []

    def draw(self) -> int:
        if not self.buffer:
            u = self.rng.random(65536)
            self.buffer = self.values[np.searchsorted(self.cdf, u, side="right").clip(0, len(self.values) - 1)].tolist()
        return self.buffer.pop()


class SizeLawSampler:
    """Positive integer sizes from an explicit law; optional lower conditioning.

Uses its own random stream in generate(), so opting into a law does not consume
the v2 extension stream. Rejection conditioning preserves the law above minimum;
clamping would incorrectly create an atom at jx_lead_min.
"""

    def __init__(self, spec: dict, rng: np.random.Generator, minimum: int = 1):
        self.spec, self.rng = spec, rng
        self.minimum = max(1, int(minimum))
        self.buffer = []
        self.law = spec["law"]
        if self.law == "lognormal":
            self.mu, self.sigma = float(spec["mu"]), float(spec["sigma"])
            self.rounding = spec.get("rounding", "round")
            if self.rounding not in ("floor", "round", "ceil"):
                raise ValueError("size-law rounding must be floor, round or ceil")
            if not math.isfinite(self.mu) or not math.isfinite(self.sigma) or self.sigma <= 0:
                raise ValueError("lognormal size law needs finite mu and positive finite sigma")
            if self.minimum > 1:
                bound = self.minimum + {"floor": 0, "round": -.5, "ceil": -1}[self.rounding]
                survival = .5 * math.erfc((math.log(bound) - self.mu) / (self.sigma * math.sqrt(2)))
                if survival < 1e-4:
                    raise ValueError("size-law lower conditioning is too far into the tail (probability < 1e-4)")
        elif self.law == "uniform":
            self.low, self.high = int(spec["low"]), int(spec["high"])
            if self.low != spec["low"] or self.high != spec["high"] or self.low < 1 or self.high < self.low:
                raise ValueError("uniform size law needs positive inclusive integer low <= high")
            self.low = max(self.low, self.minimum)
            if self.low > self.high:
                raise ValueError("size-law minimum exceeds the uniform upper bound")
        else:
            raise ValueError(f"unsupported size law: {self.law!r}")

    def draw(self) -> int:
        while not self.buffer:
            if self.law == "uniform":
                values = self.rng.integers(self.low, self.high + 1, 4096)
            else:
                raw = self.rng.lognormal(self.mu, self.sigma, 4096)
                rounded = {"floor": np.floor, "round": np.rint, "ceil": np.ceil}[self.rounding](raw)
                if not np.isfinite(rounded).all() or np.any(rounded >= 2.0 ** 63):
                    raise ValueError("size law produced a non-finite or out-of-int64 quantity")
                values = np.maximum(1, rounded).astype(np.int64)
                values = values[values >= self.minimum]
            self.buffer = values.tolist()
        return self.buffer.pop()




def generate(params: dict, seed: int, seconds: float, out: Path, latent_out: Path | None = None) -> dict:
    """The latent model: a reference bid `lb` (the latent mid is lb + 0.5) that jumps one tick at `jump_rate` a second
    either way and, after an aggressive order of q lots, one tick its way with probability impact(q); limit bids land
    at lb - k, asks at lb + 1 + k (k from `k_pmf`), never crossing the book (clamped one tick off the other touch)."""
    rng = np.random.default_rng(seed)
    latent = params["latent"]
    g_rate, f_rate, j_rate = params["g_rate"], params["f_rate"], latent["jump_rate"]
    total = g_rate + f_rate + j_rate
    p_f, p_j = f_rate / total, (f_rate + j_rate) / total
    k_draw = Sampler(latent["k_pmf"], rng)
    impact_sizes = [row[0] for row in latent["impact"]]
    impact_probs = [row[1] for row in latent["impact"]]
    sizes = {c: Sampler(params["sizes"][c], rng) for c in CLASSES}
    f_sizes = Sampler(params["f_sizes"], rng)
    size_rng = np.random.default_rng([seed, 3])
    if latent.get("g_size_law"):
        g_sampler = SizeLawSampler(latent["g_size_law"], size_rng)
        sizes = {c: g_sampler for c in CLASSES}
    if latent.get("f_size_law"):
        f_sizes = SizeLawSampler(latent["f_size_law"], size_rng)
    f_offsets = Sampler(params["f_offsets"], rng)
    lq = np.array(params["lifetime_quantiles"])
    grid = np.linspace(0, 1, len(lq))
    bid_share = params["g_bid_share"]
    informed = latent.get("informed", 0.0)
    f_buy = latent.get("f_buy_share", 0.5)  # >0.5: more buys than sells, a drifting latent price
    spread2 = latent.get("spread2", False)  # True: bids at c - 1 - k, asks at c + 1 + k around c = round(latent mid): a 2-tick book
    stale = latent.get("stale_s", 0.0)  # >0: on a latent move, the orders it leaves on the wrong side cancel within Exp(stale_s)
    due = {}  # oid -> the cancel time that counts (only with stale_s); -1 once written while a second time is queued
    extra = set()  # orders with a second (earlier, stale) cancel time queued

    def restale(step: int, now: float, mean: float | None = None) -> None:
        # lb up: asks at or below lb are now under the latent ask; lb down: bids at or above lb + 1
        side = 1 if step > 0 else 0
        for price, queue in list(book.levels[side].items()):
            if (side == 1 and price <= lb) or (side == 0 and price >= lb + 1):
                for entry in queue:
                    if entry[1] > 0:
                        ct = now + rng.exponential(stale if mean is None else mean)
                        if ct < due[entry[0]] and entry[0] not in extra:
                            due[entry[0]] = ct
                            extra.add(entry[0])
                            heapq.heappush(cancels, (ct, entry[0]))
    lb = latent.get("start_bid", 9999)
    wide = {sp: Sampler(params["offsets"][str(sp)], rng) for sp in (2, 3)} if latent.get("wide_table") else None
    continuous = latent.get("continuous", False)  # True: a real-valued latent mid (lb + 0.5 at the start), moved by impact(q) itself
    level = lb + 0.5
    # v2 options (8 Nov, gen_calibrate; all off by default, so a draw without them is the same bytes as before)
    impact_scale = latent.get("impact_scale", 1.0)  # x the impact table
    delay = latent.get("impact_delay", 0.0)  # the share of a trade's impact released over Exp(impact_tau) s, not at once
    tau_i = latent.get("impact_tau", 5.0)
    jump_df = latent.get("jump_df", 0)  # > 0: the latent's own jumps are jump_size x Student-t(jump_df), not +-jump_size
    drift_sd = latent.get("drift_sd", 0.0)  # an OU drift of the latent (ticks a second, its stationary sd) ...
    drift_tau = latent.get("drift_tau", 300.0)  # ... and its mean-reversion time (s)
    vol_states = latent.get("vol_states", [1.0])  # volatility multipliers, a Markov chain over them ...
    vol_dwell = latent.get("vol_dwell_s", 600.0)  # ... leaving a state after Exp(vol_dwell_s) s for a uniformly drawn other one
    vol_logsd = latent.get("vol_logsd", 0.0)  # and/or a log-OU multiplier, sd of the log ...
    vol_logtau = latent.get("vol_logtau", 600.0)  # ... and its time (s)
    vol_impact = latent.get("vol_impact", 0)  # 1: the multiplier scales the trades' impact too (else only the jumps and drift)
    k_vol = latent.get("k_vol", 0.0)  # at a multiplier m > 1 an insert lands one tick further out with prob k_vol (m - 1)
    place_noise = latent.get("place_noise", 0.0)  # each insert centred on the latent + N(0, place_noise) ticks
    jump_stale = latent.get("jump_stale_s")  # the stale cancels after the latent's own jumps within Exp(jump_stale_s), not stale_s: how fast the book shows them
    impact_c = latent.get("impact_sqrt", 0.0)  # > 0: a trade of q lots moves the latent impact_c sqrt(q) ticks (Phase 1), not the table
    f_lim = latent.get("f_limit_latent", 0.0)  # > 0: an IOC's limit is the latent mid +- f_lim ticks, not the touch + an offset
    # scheduled jumps (Phase 1, round 2): lognormal sizes (median jx_median, log-sd jx_logsd, clipped to [jx_min, jx_max]),
    # a random sign, at jx_rate_off / jx_rate_on a second in a hidden two-state intensity chain (mean stays jx_dwell_off /
    # jx_dwell_on s); the inserts widen by jx_warn_k ticks a side jx_warn_s s before each jump; the orders it leaves
    # stale cancel within Exp(jx_stale_s)
    jx_rates = (latent.get("jx_rate_off", 0.0), latent.get("jx_rate_on", latent.get("jx_rate_off", 0.0)))
    jx_dwell = (latent.get("jx_dwell_off", 600.0), latent.get("jx_dwell_on", 300.0))
    jx_median, jx_logsd = latent.get("jx_median", 5.6), latent.get("jx_logsd", 0.85)
    jx_min, jx_max = latent.get("jx_min", 2.0), latent.get("jx_max", 100.0)
    jx_warn_s, jx_warn_k = latent.get("jx_warn_s", 0.0), latent.get("jx_warn_k", 0.0)
    jx_stale = latent.get("jx_stale_s", stale)
    # informed flow before a jump: jx_lead_extra more IOC orders a second, all the jump's way, in the jx_lead_s s before it
    # (round 2 public: in the 0.5 s before a 3+ tick jump, 7.4 IOC orders against 4.5 at the base rate, the big ones
    # 4 to 1 the jump's way)
    jx_lead_s, jx_lead_extra = latent.get("jx_lead_s", 0.5), latent.get("jx_lead_extra", 0.0)
    jx_lead_min = latent.get("jx_lead_min", 0)  # the informed orders' sizes from the IOC size table at or above this
    # informed flow after a jump: jx_after_extra IOC orders a second the jump's way in the jx_after_s s after it, while
    # the book still lags (round 2 public, jumps timed by the 0.1-s insert centre: the 500+ lot IOC orders 113 / 3 the
    # jump's way in the 0.1 s before the flagged bin and 110 / 9 in it, 43 / 30 from 0.5 to 0.2 s before: they follow
    # the latent's jump, they do not lead it)
    jx_after_s, jx_after_extra = latent.get("jx_after_s", 0.2), latent.get("jx_after_extra", 0.0)
    # the volatile state's own texture (Phase 1: wider placement throughout it, a warning of varying lead, widenings
    # with no jump after them): jx_on_k ticks a side wider inserts while in it; each warning lasts jx_warn_s x
    # exp(jx_warn_sd N(0,1)); jx_false_rate widenings a second with no jump in it; jx_diff_sd ticks per sqrt(s) of
    # Gaussian diffusion of the latent in it
    jx_on_k, jx_warn_sd = latent.get("jx_on_k", 0.0), latent.get("jx_warn_sd", 0.0)
    jx_false_rate, jx_diff_sd = latent.get("jx_false_rate", 0.0), latent.get("jx_diff_sd", 0.0)
    jx = jx_rates[0] > 0 or jx_rates[1] > 0
    timed = delay > 0 or drift_sd > 0 or len(vol_states) > 1 or vol_logsd > 0 or jx
    if (timed or impact_scale != 1.0 or jump_df or k_vol or place_noise or impact_c or f_lim) and not continuous:
        raise ValueError("tape_gen's v2 latent options need continuous: true")
    rng2 = np.random.default_rng([seed, 2])  # the v2 processes' own stream: the base stream stays as it was
    z2, u2 = [], []
    pending = mu = logx = 0.0
    state = 0
    mult = vol_states[0] if len(vol_states) else 1.0
    next_switch = rng2.exponential(vol_dwell) if len(vol_states) > 1 else math.inf
    t_last = 0.0
    jx_state = 0
    jx_switch = rng2.exponential(jx_dwell[0]) if jx and jx_rates[0] != jx_rates[1] else math.inf
    jx_next, jx_sign, lead = math.inf, 1, []
    warn_len = jx_warn_s
    false_until = -1.0
    false_next = rng2.exponential(1.0 / jx_false_rate) if jx and jx_false_rate > 0 else math.inf
    after = []  # (time, side) of the informed orders after the last jumps, latest first
    warn = False
    f_sizes2 = Sampler([row for row in params["f_sizes"] if row[0] >= jx_lead_min] or params["f_sizes"], rng2)
    if latent.get("f_size_law") and (jx_lead_extra or jx_after_extra):
        f_sizes2 = SizeLawSampler(latent["f_size_law"], size_rng, jx_lead_min)
    f_offsets2 = Sampler(params["f_offsets"], rng2)

    def schedule(now: float) -> None:
        # the next jump at the current intensity, its sign, and the informed orders before it (times, latest first)
        nonlocal jx_next, jx_sign, lead, warn_len
        r = jx_rates[jx_state]
        jx_next = now + rng2.exponential(1.0 / r) if r > 0 else math.inf
        jx_sign = 1 if rng2.random() < 0.5 else -1
        if jx_warn_sd:
            warn_len = jx_warn_s * math.exp(jx_warn_sd * rng2.standard_normal())
        lead = []
        if jx_lead_extra and jx_next < math.inf:
            lo = max(now, jx_next - jx_lead_s)
            lead = sorted(rng2.uniform(lo, jx_next, rng2.poisson(jx_lead_extra * (jx_next - lo))).tolist(), reverse=True)

    def inject(side: int, now: float) -> None:
        # one informed IOC order (its own size and offset draws), with its impact
        nonlocal oid
        bb, ba = book.best
        opp = ba if side == 0 else bb
        if opp is None:
            return
        q = f_sizes2.draw()
        e = f_offsets2.draw()
        price = opp + e if side == 0 else opp - e
        if f_lim:
            price = math.floor(level + f_lim + 0.5) if side == 0 else math.ceil(level - f_lim - 0.5)
        book.insert(oid, side, price, q, True)
        lines.append(f"{now:.6f},Insert,{oid},{'B' if side == 0 else 'A'},{q},{price},F\n")
        oid += 1
        prob = impact_c * math.sqrt(q) if impact_c else impact_probs[min(len(impact_probs) - 1, np.searchsorted(impact_sizes, q))]
        imp = prob * impact_scale * (mult if vol_impact else 1.0)
        shift(imp if side == 0 else -imp, now)

    if jx:
        schedule(0.0)

    def normal() -> float:
        nonlocal z2
        if not z2:
            z2 = rng2.standard_normal(65536).tolist()
        return z2.pop()

    def unif() -> float:
        nonlocal u2
        if not u2:
            u2 = rng2.random(65536).tolist()
        return u2.pop()

    def shift(delta: float, now: float, mean: float | None = None) -> None:
        # the latent mid moves by delta; when its floor changes, the stale orders cancel
        nonlocal level, lb
        level += delta
        new = math.floor(level)
        if new != lb:
            step = 1 if new > lb else -1
            lb = new
            if stale:
                restale(step, now, mean)
    book = Book()
    cancels = []  # heap of (time, oid)
    oid = FIRST_ID
    rows = 0
    batch = 65536
    gaps, us, life, jumps = [], [], [], []
    t = 0.0
    lines = []
    # --latent-out: the true latent every LATENT_STEP s (the value in force at that time), the jump chain's state, and
    # the latent's own jumps (signed ticks, summed) since the previous row; no random draws, so the tape is unchanged
    lat_fh = Path(latent_out).open("w") if latent_out else None
    lat_rows, lat_i, jump_acc = [], 0, 0.0
    if lat_fh:
        lat_fh.write("time,latent,state,jump\n")

    def latent_rows(until: float) -> None:
        nonlocal lat_i, jump_acc
        while lat_i * LATENT_STEP < until:
            lat_rows.append(f"{lat_i * LATENT_STEP:.2f},{level if continuous else lb + 0.5:.4f},{jx_state},{jump_acc:.4f}\n")
            jump_acc = 0.0
            lat_i += 1
        if len(lat_rows) > 100_000:
            lat_fh.writelines(lat_rows)
            lat_rows.clear()
    with out.open("w") as fh:
        fh.write("Time,Operation,OrderId,Side,Volume,Price,Lifespan\n")
        while True:
            if not gaps:
                gaps = rng.exponential(1.0 / total, batch).tolist()
                us = rng.random(batch).tolist()
                jumps = rng.random(batch).tolist()
            nxt = t + gaps.pop()
            while cancels and cancels[0][0] <= nxt:
                ct, cid = heapq.heappop(cancels)
                if ct >= seconds:
                    break
                if stale:
                    d = due.get(cid)
                    if d != ct:  # the other of an order's two cancel times: skip it (and forget the order once both are out)
                        if d == -1.0:
                            del due[cid]
                        continue
                    if cid in extra:
                        extra.discard(cid)
                        due[cid] = -1.0
                    else:
                        del due[cid]
                book.cancel(cid)
                lines.append(f"{ct:.6f},Cancel,{cid},,,,\n")
            if nxt >= seconds:
                break
            t = nxt
            if lat_fh:
                latent_rows(t)
            if timed:  # the v2 processes in continuous time: the delayed impact, the drift, the volatility multiplier
                dt = t - t_last
                t_last = t
                dl = 0.0
                if pending:
                    rel = pending * (1.0 - math.exp(-dt / tau_i))
                    pending -= rel
                    dl += rel
                if drift_sd:
                    a = math.exp(-dt / drift_tau)
                    mu = mu * a + drift_sd * math.sqrt(1.0 - a * a) * normal()
                    dl += mu * dt
                if t >= next_switch:
                    state = (state + 1 + int(unif() * (len(vol_states) - 1))) % len(vol_states)
                    next_switch = t + rng2.exponential(vol_dwell)
                if vol_logsd:
                    a = math.exp(-dt / vol_logtau)
                    logx = logx * a + vol_logsd * math.sqrt(1.0 - a * a) * normal()
                    mult = vol_states[state] * math.exp(logx)
                else:
                    mult = vol_states[state]
                if dl:
                    shift(dl, t)
                if jx:
                    while t >= jx_switch:  # the intensity state flips; the next jump redrawn at the new rate
                        jx_state = 1 - jx_state
                        jx_switch += rng2.exponential(jx_dwell[jx_state])
                        schedule(t)
                    while lead and lead[-1] <= t:
                        lead.pop()
                        inject(0 if jx_sign > 0 else 1, t)
                    while after and after[-1][0] <= t:
                        inject(after.pop()[1], t)
                    if t >= jx_next:
                        size = min(jx_max, max(jx_min, jx_median * math.exp(jx_logsd * normal())))
                        shift(jx_sign * size, t, jx_stale)
                        jump_acc += jx_sign * size
                        if jx_after_extra:
                            side_j = 0 if jx_sign > 0 else 1
                            new = rng2.uniform(t, t + jx_after_s, rng2.poisson(jx_after_extra * jx_after_s)).tolist()
                            after = sorted(after + [(x, side_j) for x in new], reverse=True)
                        schedule(t)
                    if jx_diff_sd and jx_state == 1:
                        shift(jx_diff_sd * math.sqrt(dt) * normal(), t)
                    if t >= false_next:  # a widening with no jump after it (acted on only in the volatile state)
                        if jx_state == 1:
                            false_until = t + (jx_warn_s * math.exp(jx_warn_sd * normal()) if jx_warn_sd else jx_warn_s)
                        false_next = t + rng2.exponential(1.0 / jx_false_rate)
                    warn = jx_next - t <= warn_len or t < false_until
            u = us.pop()
            bb, ba = book.best
            if u < p_f:
                side = 0 if u < p_f * f_buy else 1
                if informed and bb is not None and ba is not None and lb + 0.5 != (bb + ba) / 2 and jumps.pop() < informed:
                    side = 0 if lb + 0.5 > (bb + ba) / 2 else 1  # an informed order: the way the book lags the latent price
                opp = ba if side == 0 else bb
                if opp is None:
                    continue
                q = f_sizes.draw()
                e = f_offsets.draw()
                price = opp + e if side == 0 else opp - e
                if f_lim:  # the limit at the latent mid +- f_lim (it may not reach a lagging touch: no trade, impact all the same)
                    price = math.floor(level + f_lim + 0.5) if side == 0 else math.ceil(level - f_lim - 0.5)
                book.insert(oid, side, price, q, True)
                lines.append(f"{t:.6f},Insert,{oid},{'B' if side == 0 else 'A'},{q},{price},F\n")
                prob = impact_c * math.sqrt(q) if impact_c else impact_probs[min(len(impact_probs) - 1, np.searchsorted(impact_sizes, q))]
                if continuous:  # the latent mid moves by the bin's mean impact; the reference bid is its floor
                    imp = prob * impact_scale * (mult if vol_impact else 1.0)
                    if delay:  # part of it released later, by the timed update
                        pending += imp * delay if side == 0 else -imp * delay
                        imp *= 1.0 - delay
                    shift(imp if side == 0 else -imp, t)
                elif jumps.pop() < prob:
                    lb += 1 if side == 0 else -1
                    if stale:
                        restale(1 if side == 0 else -1, t)
            elif u < p_j:
                step = 1 if jumps.pop() < 0.5 else -1
                if continuous:
                    size = latent.get("jump_size", 1.0) * mult
                    delta = size * float(rng2.standard_t(jump_df)) if jump_df else step * size
                    shift(delta, t, jump_stale)
                    jump_acc += delta
                    continue
                lb += step
                if stale:
                    restale(step, t)
                continue
            else:
                side = 0 if (u - p_j) / (1 - p_j) < bid_share else 1
                k = k_draw.draw()
                if wide is not None and bb is not None and ba is not None and ba - bb >= 2:
                    # at a 2+ tick spread: the offset from the same side's touch, from the tape's own table there
                    d = min(wide[min(ba - bb, 3)].draw(), ba - bb - 1)
                    price = bb + d if side == 0 else ba - d
                    q = sizes[offset_class(d)].draw()
                    book.insert(oid, side, price, q, False)
                    lines.append(f"{t:.6f},Insert,{oid},{'B' if side == 0 else 'A'},{q},{price},G\n")
                    if not life:
                        life = np.interp(rng.random(batch), grid, lq).tolist()
                    ct = t + life.pop()
                    heapq.heappush(cancels, (ct, oid))
                    if stale:
                        due[oid] = ct
                    oid += 1
                    continue
                centre = level + place_noise * normal() if place_noise else level
                if spread2:
                    c = round(centre) if continuous else lb
                    lo_b, lo_a = c - 1, c + 1
                elif place_noise:
                    lo_b = math.floor(centre)
                    lo_a = lo_b + 1
                else:
                    lo_b, lo_a = lb, lb + 1
                if k_vol and mult > 1.0 and unif() < k_vol * (mult - 1.0):
                    k += 1
                if warn:  # a jump is coming: the inserts widen
                    w = int(jx_warn_k)
                    k += w + (1 if unif() < jx_warn_k - w else 0)
                if jx_on_k and jx_state == 1:  # the volatile state's wider placement
                    w = int(jx_on_k)
                    k += w + (1 if unif() < jx_on_k - w else 0)
                if side == 0:
                    price = lo_b - k
                    if ba is not None:
                        price = min(price, ba - 1)
                    d = price - bb if bb is not None else 0
                else:
                    price = lo_a + k
                    if bb is not None:
                        price = max(price, bb + 1)
                    d = ba - price if ba is not None else 0
                q = sizes[offset_class(d)].draw()
                book.insert(oid, side, price, q, False)
                lines.append(f"{t:.6f},Insert,{oid},{'B' if side == 0 else 'A'},{q},{price},G\n")
                if not life:
                    life = np.interp(rng.random(batch), grid, lq).tolist()
                ct = t + life.pop()
                heapq.heappush(cancels, (ct, oid))
                if stale:
                    due[oid] = ct
            oid += 1
            if len(lines) > 100_000:
                rows += len(lines)
                fh.writelines(lines)
                lines = []
        rows += len(lines)
        fh.writelines(lines)
    if lat_fh:
        latent_rows(seconds)
        lat_fh.writelines(lat_rows)
        lat_fh.close()
    return {"rows": rows, "seed": seed, "seconds": seconds, "out": str(out)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="experiments.day.tape_gen", description=__doc__.split("\n")[0])
    parser.add_argument("--fit", type=Path, help="fit the model to this tape (plain CSV) and write --params-out")
    parser.add_argument("--params-out", type=Path)
    parser.add_argument("--jump-rate", type=float, default=0.0, help="the latent mid's own +-0.5-tick steps a second, beyond the trades' impact (calibrated: 0)")
    parser.add_argument("--stale-s", type=float, default=0.2, help="the mean time a stale order takes to cancel after a latent move (calibrated: 0.2)")
    parser.add_argument("--impact-cap", type=float, default=1.0, help="the most a size bin's impact may be (ticks; round 1's fit: 1, round 2's 500+ lots measure 1.3-2.1)")
    parser.add_argument("--params", type=Path, help="a fitted model (JSON) to draw a tape from")
    parser.add_argument("--opts", help="JSON latent options merged into the params' (the v2 options above)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--seconds", type=float, help="the tape's length (default: the fitted tape's)")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--latent-out", type=Path, help="also write the true latent (time, latent, state, jump) every 10 ms")
    args = parser.parse_args(argv)
    if args.fit:
        if not args.params_out:
            parser.error("--fit needs --params-out")
        params = fit(args.fit, args.jump_rate, args.stale_s, args.impact_cap)
        args.params_out.write_text(json.dumps(params, indent=1))
        print(json.dumps(params["tests"], indent=1))
        print(f"g_rate {params['g_rate']:.2f}/s, f_rate {params['f_rate']:.3f}/s; wrote {args.params_out}")
        return 0
    if not (args.params and args.out):
        parser.error("give --fit DATA --params-out P.json, or --params P.json --out tape.csv")
    params = json.loads(args.params.read_text())
    params["latent"].update(json.loads(args.opts or "{}"))
    result = generate(params, args.seed, args.seconds or params["duration_s"], args.out, args.latent_out)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
