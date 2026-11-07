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
  aggressive orders the way the book lags the latent mid; `wide_table` (default off; dropped: the 2-tick share 9.5%) draws
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

    uv run python -m experiments.day.tape_gen --fit data/arena/round1/round1.csv --params-out P.json
    uv run python -m experiments.day.tape_gen --params P.json --seed N --seconds 12000 --out tape.csv
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
# the impact table's size bins (lots); fit() fills in each bin's mean mid move 5 s after (ticks, the trade's way)
IMPACT = [[10, 0.097], [30, 0.111], [60, 0.161], [120, 0.254], [250, 0.349], [500, 0.468], [1000, 0.704], [10**9, 0.903]]


def offset_class(d: int) -> str:
    return "inside" if d > 0 else "touch" if d == 0 else "behind1" if d == -1 else "deeper"


def _counts(counter: Counter) -> list[list[int]]:
    return [[int(k), int(v)] for k, v in sorted(counter.items())]


def fit(path: Path, jump_rate: float = 0.0, stale_s: float = 0.2) -> dict:
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
        impact.append([hi, round(float(np.clip(move5[sel].mean(), 0, 1)), 4) if sel.any() else 0.0])
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




def generate(params: dict, seed: int, seconds: float, out: Path) -> dict:
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
    f_offsets = Sampler(params["f_offsets"], rng)
    lq = np.array(params["lifetime_quantiles"])
    grid = np.linspace(0, 1, len(lq))
    bid_share = params["g_bid_share"]
    informed = latent.get("informed", 0.0)
    stale = latent.get("stale_s", 0.0)  # >0: on a latent move, the orders it leaves on the wrong side cancel within Exp(stale_s)
    due = {}  # oid -> the cancel time that counts (only with stale_s); -1 once written while a second time is queued
    extra = set()  # orders with a second (earlier, stale) cancel time queued

    def restale(step: int, now: float) -> None:
        # lb up: asks at or below lb are now under the latent ask; lb down: bids at or above lb + 1
        side = 1 if step > 0 else 0
        for price, queue in list(book.levels[side].items()):
            if (side == 1 and price <= lb) or (side == 0 and price >= lb + 1):
                for entry in queue:
                    if entry[1] > 0:
                        ct = now + rng.exponential(stale)
                        if ct < due[entry[0]] and entry[0] not in extra:
                            due[entry[0]] = ct
                            extra.add(entry[0])
                            heapq.heappush(cancels, (ct, entry[0]))
    lb = latent.get("start_bid", 9999)
    wide = {sp: Sampler(params["offsets"][str(sp)], rng) for sp in (2, 3)} if latent.get("wide_table") else None
    continuous = latent.get("continuous", False)  # True: a real-valued latent mid (lb + 0.5 at the start), moved by impact(q) itself
    level = lb + 0.5
    book = Book()
    cancels = []  # heap of (time, oid)
    oid = FIRST_ID
    rows = 0
    batch = 65536
    gaps, us, life, jumps = [], [], [], []
    t = 0.0
    lines = []
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
            u = us.pop()
            bb, ba = book.best
            if u < p_f:
                side = 0 if u < p_f / 2 else 1
                if informed and bb is not None and ba is not None and lb + 0.5 != (bb + ba) / 2 and jumps.pop() < informed:
                    side = 0 if lb + 0.5 > (bb + ba) / 2 else 1  # an informed order: the way the book lags the latent price
                opp = ba if side == 0 else bb
                if opp is None:
                    continue
                q = f_sizes.draw()
                e = f_offsets.draw()
                price = opp + e if side == 0 else opp - e
                book.insert(oid, side, price, q, True)
                lines.append(f"{t:.6f},Insert,{oid},{'B' if side == 0 else 'A'},{q},{price},F\n")
                prob = impact_probs[min(len(impact_probs) - 1, np.searchsorted(impact_sizes, q))]
                if continuous:  # the latent mid moves by the bin's mean impact; the reference bid is its floor
                    level += prob if side == 0 else -prob
                    new = math.floor(level)
                    if new != lb:
                        step = 1 if new > lb else -1
                        lb = new
                        if stale:
                            restale(step, t)
                elif jumps.pop() < prob:
                    lb += 1 if side == 0 else -1
                    if stale:
                        restale(1 if side == 0 else -1, t)
            elif u < p_j:
                step = 1 if jumps.pop() < 0.5 else -1
                if continuous:
                    level += step * latent.get("jump_size", 1.0)
                    new = math.floor(level)
                    if new == lb:
                        continue
                    step = 1 if new > lb else -1
                    lb = new
                else:
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
                if side == 0:
                    price = lb - k
                    if ba is not None:
                        price = min(price, ba - 1)
                    d = price - bb if bb is not None else 0
                else:
                    price = lb + 1 + k
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
    return {"rows": rows, "seed": seed, "seconds": seconds, "out": str(out)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="experiments.day.tape_gen", description=__doc__.split("\n")[0])
    parser.add_argument("--fit", type=Path, help="fit the model to this tape (plain CSV) and write --params-out")
    parser.add_argument("--params-out", type=Path)
    parser.add_argument("--jump-rate", type=float, default=0.0, help="the latent mid's own +-0.5-tick steps a second, beyond the trades' impact (calibrated: 0)")
    parser.add_argument("--stale-s", type=float, default=0.2, help="the mean time a stale order takes to cancel after a latent move (calibrated: 0.2)")
    parser.add_argument("--params", type=Path, help="a fitted model (JSON) to draw a tape from")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--seconds", type=float, help="the tape's length (default: the fitted tape's)")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if args.fit:
        if not args.params_out:
            parser.error("--fit needs --params-out")
        params = fit(args.fit, args.jump_rate, args.stale_s)
        args.params_out.write_text(json.dumps(params, indent=1))
        print(json.dumps(params["tests"], indent=1))
        print(f"g_rate {params['g_rate']:.2f}/s, f_rate {params['f_rate']:.3f}/s; wrote {args.params_out}")
        return 0
    if not (args.params and args.out):
        parser.error("give --fit DATA --params-out P.json, or --params P.json --out tape.csv")
    params = json.loads(args.params.read_text())
    result = generate(params, args.seed, args.seconds or params["duration_s"], args.out)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
