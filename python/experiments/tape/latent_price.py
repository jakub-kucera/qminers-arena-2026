"""Where the tape's new passive orders land against the touch, as an online signal of the mid's next move (7 Nov, round 1).

    uv run python -m experiments.tape.latent_price data/arena/round1/round1.csv [--train 0.75]

A teammate's finding: at a 1-tick spread a new market bid lands AT the touch 80% of the time when the mid is up 0.5 s
later and 23% when it is down (asks mirror): the generator's new orders centre on a latent price the mid follows. This
replays the tape (price-time, no strategy) and keeps, for several time constants TAU, exponentially decayed means of
what a bot sees in its snapshots:
  - A  : the share of new non-crossing bid inserts at (or inside) the bid touch minus the same share for asks;
  - R  : the same with the insert's distance to its own touch, clipped to [-3, +1] (deeper inserts count negative);
  - L  : the latent price: the decayed mean of new bid prices plus the decayed mean of new ask prices, halved, minus the
         mid (inserts clipped to within 4 ticks of the mid);
  - C  : the share of cancels hitting the bid touch minus the ask touch's (bids leaving the touch: latent down).
Sampled every 10 ms; for each the mid's move 0.1 / 0.5 / 1 / 5 s ahead. On the first TRAIN share: the correlation, the
slope through 0, and decile cut points; on the rest: the same correlation and the mean move per training decile.
Standard library only.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import math
import statistics
from collections import defaultdict, deque

TAUS = (0.1, 0.3, 1.0, 3.0)
HORIZONS = (0.1, 0.5, 1.0, 5.0)
STEP = 0.01


def best(book, bid):
    while book:
        p = max(book) if bid else min(book)
        if book[p]:
            return p
        del book[p]
    return None


class Decayed:
    """Per-key exponentially decayed sums of x and of the weights, one set per time constant."""

    def __init__(self, keys):
        self.t = 0.0
        self.s = {k: [0.0] * len(TAUS) for k in keys}
        self.w = {k: [0.0] * len(TAUS) for k in keys}

    def decay(self, t):
        dt = t - self.t
        if dt <= 0:
            return
        self.t = t
        for i, tau in enumerate(TAUS):
            f = math.exp(-dt / tau)
            for k in self.s:
                self.s[k][i] *= f
                self.w[k][i] *= f

    def add(self, k, x):
        s, w = self.s[k], self.w[k]
        for i in range(len(TAUS)):
            s[i] += x
            w[i] += 1.0

    def mean(self, k, i, default=0.0):
        w = self.w[k][i]
        return self.s[k][i] / w if w > 1e-9 else default


def main(path, train):
    bids, asks = defaultdict(deque), defaultdict(deque)
    live = {}
    ev_t, ev_mid = [], []
    samples = []  # (t, mid, {signal name: [per tau]})
    dec = Decayed(("bA", "aA", "bR", "aR", "bP", "aP", "bC", "aC"))
    next_sample = None
    with open(path) as f:
        r = csv.reader(f)
        next(r)
        for row in r:
            t = float(row[0])
            bb, ba = best(bids, True), best(asks, False)
            dec.decay(t)
            if next_sample is None:
                next_sample = t
            while bb is not None and ba is not None and t >= next_sample:
                mid = (bb + ba) / 2
                sig = {}
                sig["A"] = [dec.mean("bA", i, 0.5) - dec.mean("aA", i, 0.5) for i in range(len(TAUS))]
                sig["R"] = [dec.mean("bR", i) - dec.mean("aR", i) for i in range(len(TAUS))]
                sig["L"] = [(dec.mean("bP", i, mid - 1) + dec.mean("aP", i, mid + 1)) / 2 - mid for i in range(len(TAUS))]
                sig["C"] = [dec.mean("bC", i, 0.5) - dec.mean("aC", i, 0.5) for i in range(len(TAUS))]
                samples.append((next_sample, mid, sig))
                next_sample += STEP
            if row[1] == "Cancel":
                oid = int(row[2])
                o = live.pop(oid, None)
                if o is None:
                    continue
                q = (bids if o[0] == "B" else asks).get(o[1])
                if q:
                    for e in q:
                        if e[0] == oid:
                            q.remove(e)
                            break
                if bb is not None and ba is not None:
                    if o[0] == "B":
                        dec.add("bC", 1.0 if o[1] == bb else 0.0)
                    else:
                        dec.add("aC", 1.0 if o[1] == ba else 0.0)
            else:
                oid = int(row[2])
                side, vol, price, lif = row[3], int(row[4]), int(row[5]), row[6]
                crossing = (side == "B" and ba is not None and price >= ba) or (side == "A" and bb is not None and price <= bb)
                if not crossing and bb is not None and ba is not None and lif == "G":
                    mid = (bb + ba) / 2
                    if side == "B":
                        dec.add("bA", 1.0 if price >= bb else 0.0)
                        dec.add("bR", max(-3, min(1, price - bb)))
                        dec.add("bP", max(mid - 4, min(mid + 4, price)))
                    else:
                        dec.add("aA", 1.0 if price <= ba else 0.0)
                        dec.add("aR", max(-3, min(1, ba - price)))
                        dec.add("aP", max(mid - 4, min(mid + 4, price)))
                opp = asks if side == "B" else bids
                rem = vol
                while rem > 0:
                    p = best(opp, side == "A")
                    if p is None or (side == "B" and price < p) or (side == "A" and price > p):
                        break
                    q = opp[p]
                    while q and rem > 0:
                        e = q[0]
                        x = min(rem, e[1])
                        e[1] -= x
                        rem -= x
                        if e[1] == 0:
                            q.popleft()
                            live.pop(e[0], None)
                if rem > 0 and lif == "G":
                    (bids if side == "B" else asks)[price].append([oid, rem])
                    live[oid] = (side, price)
            nbb, nba = best(bids, True), best(asks, False)
            if nbb is not None and nba is not None:
                m = (nbb + nba) / 2
                if ev_t and ev_t[-1] == t:
                    ev_mid[-1] = m
                else:
                    ev_t.append(t)
                    ev_mid.append(m)

    def mid_at(t):
        j = bisect.bisect_right(ev_t, t) - 1
        return ev_mid[j] if j >= 0 else None

    cut = samples[int(len(samples) * train)][0]
    print(f"{len(samples)} samples every {STEP * 1000:.0f} ms; train t < {cut:.0f} s")
    end = ev_t[-1]
    for h in HORIZONS:
        moves = []
        for t, mid, sig in samples:
            if t + h > end:
                break
            moves.append(mid_at(t + h) - mid)
        print(f"\n== horizon {h} s (mean |move| {statistics.fmean(abs(x) for x in moves):.3f} ticks)")
        for name in ("A", "R", "L", "C"):
            for i, tau in enumerate(TAUS):
                tr_x, tr_y, te_x, te_y = [], [], [], []
                for (t, mid, sig), y in zip(samples, moves):
                    (tr_x if t < cut else te_x).append(sig[name][i])
                    (tr_y if t < cut else te_y).append(y)
                c_tr = statistics.correlation(tr_x, tr_y)
                c_te = statistics.correlation(te_x, te_y)
                b = sum(x * y for x, y in zip(tr_x, tr_y)) / max(1e-12, sum(x * x for x in tr_x))
                ss = sum((y - b * x) ** 2 for x, y in zip(te_x, te_y))
                r2 = 1 - ss / sum(y * y for y in te_y)
                qs = statistics.quantiles(tr_x, n=10)
                buckets = [[] for _ in range(10)]
                for x, y in zip(te_x, te_y):
                    buckets[bisect.bisect_right(qs, x)].append(y)
                dec_means = " ".join(f"{statistics.fmean(bk):+.2f}" if bk else "  nan" for bk in buckets)
                print(f"{name} tau {tau:>4}: corr in {c_tr:+.3f} out {c_te:+.3f}  slope {b:+.3f}  R2 out {r2:+.3f}  out move by in-decile: {dec_means}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("path")
    ap.add_argument("--train", type=float, default=0.75)
    a = ap.parse_args()
    main(a.path, a.train)
