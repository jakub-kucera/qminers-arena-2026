"""Structure in an Arena order tape: resting-order lifetimes by size and distance from the touch,
aggressive-order burstiness and sizes, mid reversion, and a ceiling (aggressive lots at the touch x half spread).

A price-time replay of the tape alone (no strategy).  Usage:
    uv run python -m experiments.tape.tape_structure data/arena/playground/sample_v2.csv
"""
import csv
import statistics
import sys
from collections import defaultdict, deque


def bucket_size(v):
    return "1-20" if v <= 20 else "21-40" if v <= 40 else "41-80" if v <= 80 else ">80"


def best(book, bid):
    while book:
        p = max(book) if bid else min(book)
        if book[p]:
            return p
        del book[p]
    return None


def main(path):
    bids, asks = defaultdict(deque), defaultdict(deque)  # price -> deque of [oid, vol]
    live = {}  # oid -> (t_insert, side, price, vol0, dist_at_insert)
    life = defaultdict(list)
    filled, cancelled, spreads = defaultdict(int), defaultdict(int), defaultdict(int)
    agg_times, agg_sizes, mids = [], [], []
    traded, touch_lots, half_spread_lots = 0, 0, 0.0
    with open(path) as f:
        r = csv.reader(f)
        next(r)
        for row in r:
            t = float(row[0])
            oid = int(row[2])
            if row[1] == "Cancel":
                o = live.pop(oid, None)
                if o is None:
                    continue
                q = (bids if o[1] == "B" else asks).get(o[2])
                if q:
                    for e in q:
                        if e[0] == oid:
                            q.remove(e)
                            break
                life[(bucket_size(o[3]), o[4])].append(t - o[0])
                cancelled[o[4]] += 1
                continue
            side, vol, price, kind = row[3], int(row[4]), int(row[5]), row[6]
            bb, ba = best(bids, True), best(asks, False)
            if bb is not None and ba is not None:
                spreads[ba - bb] += 1
                mids.append((t, (bb + ba) / 2))
            opp = asks if side == "B" else bids
            crosses = (side == "B" and ba is not None and price >= ba) or (side == "A" and bb is not None and price <= bb)
            if crosses or kind == "F":
                agg_times.append(t)
                agg_sizes.append(vol)
            rem = vol
            while rem > 0 and crosses:
                p = best(opp, side == "A")
                if p is None or (side == "B" and p > price) or (side == "A" and p < price):
                    break
                q = opp[p]
                touch = p == (ba if side == "B" else bb)
                while q and rem > 0:
                    e = q[0]
                    x = min(rem, e[1])
                    e[1] -= x
                    rem -= x
                    traded += x
                    if touch and bb is not None and ba is not None:
                        touch_lots += x
                        half_spread_lots += x * (ba - bb) / 2
                    if e[1] == 0:
                        q.popleft()
                        o = live.pop(e[0], None)
                        if o:
                            filled[o[4]] += 1
            if rem > 0 and kind == "G":
                ref = bb if side == "B" else ba
                d = "?" if ref is None else str(min(max(ref - price if side == "B" else price - ref, -1), 4))
                (bids if side == "B" else asks)[price].append([oid, rem])
                live[oid] = (t, side, price, vol, d)

    print("spread at inserts:", dict(sorted(spreads.items())[:5]))
    print(f"lots traded by aggressors {traded}; at the touch {touch_lots}; x half spread {half_spread_lots:.0f}")
    print("orders cancelled / fully filled, by distance from own touch at insert (-1 = improves it):")
    for d in sorted(set(cancelled) | set(filled)):
        print(f"  {d}: cancelled {cancelled[d]}, filled {filled[d]}")
    print("lifetime of cancelled resting orders (s): size, dist, n, p10, median, p90, share < 0.05 s")
    for k in sorted(life):
        v = sorted(life[k])
        n = len(v)
        if n >= 200:
            print(f"  {k[0]:>6} {k[1]:>2} {n:7d} {v[n // 10]:.3f} {v[n // 2]:.3f} {v[9 * n // 10]:.3f} {sum(x < 0.05 for x in v) / n:.3f}")
    gaps = [b - a for a, b in zip(agg_times, agg_times[1:])]
    m, s = statistics.mean(gaps), statistics.pstdev(gaps)
    print(f"aggressive orders {len(agg_times)}: gap mean {m:.3f} s, sd {s:.3f} (CV {s / m:.2f}; 1 = Poisson)")
    counts = defaultdict(int)
    for t in agg_times:
        counts[int(t)] += 1
    c = [counts[i] for i in range(int(agg_times[-1]) + 1)]
    cm, cv = statistics.mean(c), statistics.pvariance(c)
    print(f"  per-second counts: mean {cm:.2f}, var/mean {cv / cm:.2f} (1 = Poisson)")
    ac = [sum((c[i] - cm) * (c[i + L] - cm) for i in range(len(c) - L)) / ((len(c) - L) * cv) for L in (1, 2, 5, 10, 30, 60)]
    print("  autocorrelation of per-second counts at lags 1,2,5,10,30,60:", [round(a, 3) for a in ac])
    sz = defaultdict(int)
    for v in agg_sizes:
        sz[v] += 1
    print("  aggressive sizes (top 10):", sorted(sz.items(), key=lambda kv: -kv[1])[:10])
    sampled, j = [], 0
    for k in range(0, int(mids[-1][0]), 10):
        while j < len(mids) - 1 and mids[j + 1][0] <= k:
            j += 1
        sampled.append(mids[j][1])
    dm = [b - a for a, b in zip(sampled, sampled[1:])]
    mu, vd = statistics.mean(dm), statistics.pvariance(dm)
    a1 = sum((dm[i] - mu) * (dm[i + 1] - mu) for i in range(len(dm) - 1)) / ((len(dm) - 1) * vd)
    print(f"mid: range {min(sampled)}..{max(sampled)}, 10-s change sd {vd ** 0.5:.2f}, lag-1 autocorr {a1:.3f}")


if __name__ == "__main__":
    main(sys.argv[1])
