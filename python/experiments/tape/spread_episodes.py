"""Two-tick spread episodes, price-improving inserts, the order-flow imbalance and the mid's autocorrelation on an
Arena tape (7 Nov, round 1): a price-time replay of the tape alone (no strategy).

    uv run python -m experiments.tape.spread_episodes data/arena/round1/round1.csv

Answers, for a maker that would quote one tick inside a two-tick spread: how the spread opens (a touch cleared by a
trade or by cancels), which side closes it (the side that moved stepping back, or the other side following), how long
it stays open, the size of the closing insert; the lots and the mid's move after price-improving inserts; the mid's move
after the touch's lots change (the order-flow imbalance over the last window); the depth behind the touch against the
size of the move once the touch clears; and the mid's autocorrelation at several horizons.
"""

from __future__ import annotations

import bisect
import csv
import statistics
import sys
from collections import defaultdict, deque


def best(book, bid):
    while book:
        p = max(book) if bid else min(book)
        if book[p]:
            return p
        del book[p]
    return None


def lots(book, p):
    q = book.get(p)
    return sum(e[1] for e in q) if q else 0


def main(path):
    bids, asks = defaultdict(deque), defaultdict(deque)  # price -> deque of [oid, vol]
    live = {}  # oid -> (side, price)
    times, mids = [], []
    episodes = []  # [t_open, how (trade/cancel), moved side, t_close, closer side, closer size, closer_kind]
    improvers = []  # [t, side, size, mid_before]
    ofi_rows = []  # [t, dbid, dask, mid]
    clears = []  # [t, side, depth_behind_before, mid_before]
    open_ep = None
    prev_bb = prev_ba = None
    prev_touch = (None, None, 0, 0)
    last_event_was_trade = False
    win = deque()  # (t, dbid_lots, dask_lots) at the touch
    with open(path) as f:
        r = csv.reader(f)
        next(r)
        n = 0
        for row in r:
            n += 1
            t = float(row[0])
            oid = int(row[2])
            bb, ba = best(bids, True), best(asks, False)
            bl, al = (lots(bids, bb) if bb is not None else 0), (lots(asks, ba) if ba is not None else 0)
            bl2 = lots(bids, bb - 1) if bb is not None else 0
            al2 = lots(asks, ba + 1) if ba is not None else 0
            traded = False
            kind = None
            size = 0
            side = None
            if row[1] == "Cancel":
                o = live.pop(oid, None)
                if o is None:
                    continue
                q = (bids if o[0] == "B" else asks).get(o[1])
                if q:
                    for e in q:
                        if e[0] == oid:
                            q.remove(e)
                            break
                kind = "cancel"
            else:
                side, vol, price, lif = row[3], int(row[4]), int(row[5]), row[6]
                size = vol
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
                        traded = True
                        if e[1] == 0:
                            q.popleft()
                            live.pop(e[0], None)
                if rem > 0 and lif == "G":
                    (bids if side == "B" else asks)[price].append([oid, rem])
                    live[oid] = (side, price)
                    # a price-improving insert (inside the old spread)
                    if bb is not None and ba is not None and ((side == "B" and bb < price < ba) or (side == "A" and bb < price < ba)):
                        improvers.append([t, side, rem, (bb + ba) / 2])
                kind = "insert"
            nbb, nba = best(bids, True), best(asks, False)
            if nbb is None or nba is None:
                continue
            mid = (nbb + nba) / 2
            if times and times[-1] == t:
                mids[-1] = mid
            else:
                times.append(t)
                mids.append(mid)
            # touch lot changes for the OFI (same prices only)
            nbl, nal = lots(bids, nbb), lots(asks, nba)
            if bb == nbb and ba == nba:
                win.append((t, nbl - bl, nal - al))
            else:
                win.append((t, 0, 0))
            while win and win[0][0] < t - 0.3:
                win.popleft()
            if n % 50 == 0 and bb is not None and ba is not None:
                ofi_rows.append([t, sum(w[1] for w in win), sum(w[2] for w in win), mid, nbl, nal])
            # clears
            if bb is not None and nbb < bb:
                clears.append([t, "B", bl2, (bb + ba) / 2, "trade" if traded else "cancel"])
            if ba is not None and nba > ba:
                clears.append([t, "A", al2, (bb + ba) / 2, "trade" if traded else "cancel"])
            # episodes
            if bb is None or ba is None:
                open_ep = None
                continue
            spread_before = ba - bb
            spread_after = nba - nbb
            if open_ep is None and spread_before == 1 and spread_after == 2:
                moved = "B" if nbb < bb else "A"
                open_ep = [t, "trade" if traded else "cancel", moved, None, None, 0, None]
            elif open_ep is not None and spread_after == 1:
                # who closed: the side that moved stepping back, or the other side following
                if nbb > bb:
                    closer = "B"
                elif nba < ba:
                    closer = "A"
                else:
                    closer = "?"
                open_ep[3] = t
                open_ep[4] = "moved-back" if closer == open_ep[2] else ("other-followed" if closer != "?" else "?")
                open_ep[5] = size
                open_ep[6] = kind
                episodes.append(open_ep)
                open_ep = None
            elif open_ep is not None and spread_after >= 3:
                open_ep = None  # widened further: drop it
    print(f"rows {n:,}; two-tick episodes {len(episodes):,}; improvers {len(improvers):,}; clears {len(clears):,}")

    def mid_at(tt):
        i = bisect.bisect_right(times, tt) - 1
        return mids[i] if i >= 0 else None

    # episodes
    by = defaultdict(list)
    for e in episodes:
        by[(e[1], e[4])].append(e)
    print("two-tick episodes by how they opened x who closed: n, median duration ms, p90 ms, median closer size, mid move 1 s after the close toward the moved side (+ = continued)")
    for k in sorted(by):
        es = by[k]
        d = [1000 * (e[3] - e[0]) for e in es]
        sz = [e[5] for e in es]
        mv = []
        for e in es:
            m0 = mid_at(e[3])
            m1 = mid_at(e[3] + 1.0)
            if m0 is not None and m1 is not None:
                sign = -1 if e[2] == "B" else 1  # the bid moved down: continued = down
                mv.append(sign * (m1 - m0))
        print(f"  {k[0]:>6} / {k[1]:>14}: n {len(es):6,}  dur med {statistics.median(d):7.1f} p90 {sorted(d)[int(0.9 * len(d)) - 1]:8.1f}"
              f"  closer size med {statistics.median(sz):5.0f}  move1s {statistics.mean(mv):+.3f}")
    # improvers
    print("price-improving inserts: by side, n, median lots, mean lots, mid move at 1 s and 5 s in the insert's direction (+ = the price went the way the improver leaned)")
    for s in ("B", "A"):
        rows = [x for x in improvers if x[1] == s]
        sign = 1 if s == "B" else -1
        m1 = [sign * (mid_at(x[0] + 1.0) - x[3]) for x in rows if mid_at(x[0] + 1.0) is not None]
        m5 = [sign * (mid_at(x[0] + 5.0) - x[3]) for x in rows if mid_at(x[0] + 5.0) is not None]
        print(f"  {s}: n {len(rows):6,}  lots med {statistics.median([x[2] for x in rows]):5.0f} mean {statistics.mean([x[2] for x in rows]):6.1f}"
              f"  move1s {statistics.mean(m1):+.3f}  move5s {statistics.mean(m5):+.3f}")
    szs = sorted(x[2] for x in improvers)
    print(f"  improver lots p50/p75/p90/p99: {szs[len(szs)//2]} / {szs[int(0.75*len(szs))]} / {szs[int(0.9*len(szs))]} / {szs[int(0.99*len(szs))]}")
    # OFI
    print("order-flow imbalance over the last 300 ms at the touch (dBid - dAsk lots), quintiles: n, mean OFI, mid move at 1 s, 5 s")
    rows = [x for x in ofi_rows if mid_at(x[0] + 5.0) is not None]
    rows.sort(key=lambda x: x[1] - x[2])
    k = len(rows) // 5
    for i in range(5):
        part = rows[i * k:(i + 1) * k]
        o = statistics.mean(x[1] - x[2] for x in part)
        m1 = statistics.mean(mid_at(x[0] + 1.0) - x[3] for x in part)
        m5 = statistics.mean(mid_at(x[0] + 5.0) - x[3] for x in part)
        print(f"  q{i + 1}: n {len(part):7,}  ofi {o:+8.1f}  move1s {m1:+.3f}  move5s {m5:+.3f}")
    print("touch imbalance (bid - ask)/(bid + ask) quintiles: mean imb, mid move at 1 s, 5 s")
    rows.sort(key=lambda x: (x[4] - x[5]) / max(1, x[4] + x[5]))
    for i in range(5):
        part = rows[i * k:(i + 1) * k]
        o = statistics.mean((x[4] - x[5]) / max(1, x[4] + x[5]) for x in part)
        m1 = statistics.mean(mid_at(x[0] + 1.0) - x[3] for x in part)
        m5 = statistics.mean(mid_at(x[0] + 5.0) - x[3] for x in part)
        print(f"  q{i + 1}: n {len(part):7,}  imb {o:+6.3f}  move1s {m1:+.3f}  move5s {m5:+.3f}")
    # clears: depth behind vs move size
    print("touch clears: by how (trade/cancel) x the depth behind the touch before it: n, mid move at 1 s in the clear's direction (+ = continued beyond the first tick), share that moved 2+ ticks by 1 s")
    bins = [(0, 100), (100, 300), (300, 800), (800, 2000), (2000, 10**9)]
    for how in ("trade", "cancel"):
        for lo, hi in bins:
            rows_c = [c for c in clears if c[4] == how and lo <= c[2] < hi]
            if not rows_c:
                continue
            mv = []
            for c in rows_c:
                m1 = mid_at(c[0] + 1.0)
                if m1 is None:
                    continue
                sign = -1 if c[1] == "B" else 1
                mv.append(sign * (m1 - c[3]))
            two = sum(1 for x in mv if x >= 1.5) / max(1, len(mv))
            print(f"  {how:>6} depth behind [{lo},{hi}): n {len(rows_c):6,}  move1s {statistics.mean(mv):+.3f}  2+ ticks {two:.1%}")
    # autocorrelation of mid changes
    print("mid change autocorrelation (lag 1) at horizons 1, 5, 10, 30, 60, 300 s")
    for h in (1, 5, 10, 30, 60, 300):
        xs = []
        tt = times[0]
        while tt + 2 * h <= times[-1]:
            a, b, c = mid_at(tt), mid_at(tt + h), mid_at(tt + 2 * h)
            xs.append((b - a, c - b))
            tt += h
        if len(xs) > 10:
            mx = statistics.mean(x for x, _ in xs)
            my = statistics.mean(y for _, y in xs)
            cov = sum((x - mx) * (y - my) for x, y in xs)
            vx = sum((x - mx) ** 2 for x, _ in xs)
            vy = sum((y - my) ** 2 for _, y in xs)
            print(f"  {h:4d} s: n {len(xs):6,}  autocorr {cov / (vx * vy) ** 0.5:+.3f}  sd {statistics.pstdev([x for x, _ in xs]):.2f}")


if __name__ == "__main__":
    main(sys.argv[1])
