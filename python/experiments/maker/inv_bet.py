"""Inventory as a bet (7 Nov, round 1): does anything online predict the mid 0.5-30 s ahead, and what is a run's inventory worth?

Replays the tape's book (market orders only, price-time matching, F rows killed), samples it every DT s and computes, at each
sample: imb1 (the touch lots' imbalance), imb5 (over the 5 price levels from each touch), the signed aggressive lots over the
last 0.5 / 5 / 30 s, the signed lots inserted at or inside the touch and cancelled over the last 0.5 / 5 / 30 s, the mid's
change over the last 5 / 30 / 120 s and its distance from its 60 / 300 s mean. For each horizon: every feature's correlation
with the mid's move on the first 1 - HOLDOUT of the samples and on the rest, then an OLS on imb1, imb5, flow 0.5 s and flow 5 s
fitted on the first part (its weights, correlation in / out, and the realised move by forecast bucket on both parts).
With --trades (a full-logs run's trades.csv): the run's position at each sample against the mid's move ahead (corr, and the
position times the move per second), and its inventory PnL, sum of position x the mid's change, by quarter.

    uv run python -m experiments.maker.inv_bet data/arena/round1/round1.csv [--trades logs/r1_F8_full/trades.csv] [--holdout 0.25]
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import deque

DT = 0.1
HORIZONS = (0.5, 1, 2, 5, 10, 30)


def replay(path: str) -> list:
    """Rows [t, best bid, best ask, bid lots 5 levels, ask lots 5 levels, buy agg, sell agg, ins bid, ins ask, cxl bid, cxl ask]."""
    levels = {'B': {}, 'A': {}}
    queues: dict = {}
    orders: dict = {}
    best = {'B': None, 'A': None}
    acc = [0.0] * 6
    rows = []
    next_t = DT

    def refresh(side: str) -> None:
        lv = levels[side]
        best[side] = (max(lv) if side == 'B' else min(lv)) if lv else None

    def take(side: str, price: int, qty: int) -> int:
        other = 'A' if side == 'B' else 'B'
        filled = 0
        while qty > 0 and best[other] is not None and (best[other] <= price if side == 'B' else best[other] >= price):
            p = best[other]
            dq = queues[(other, p)]
            while qty > 0 and dq:
                oid = dq[0]
                o = orders[oid]
                x = min(qty, o[2])
                o[2] -= x
                qty -= x
                filled += x
                levels[other][p] -= x
                if o[2] == 0:
                    dq.popleft()
                    del orders[oid]
            if levels[other][p] <= 0:
                del levels[other][p]
                refresh(other)
        return filled

    with open(path) as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            t = float(row[0])
            while t >= next_t:
                bb, ba = best['B'], best['A']
                if bb is not None and ba is not None:
                    b5 = [levels['B'].get(bb - i, 0) for i in range(5)]
                    a5 = [levels['A'].get(ba + i, 0) for i in range(5)]
                    rows.append([next_t, bb, ba, b5, a5] + acc)
                acc = [0.0] * 6
                next_t += DT
            oid = row[2]
            if row[1] == 'Cancel':
                o = orders.pop(oid, None)
                if o is None:
                    continue
                side, p, q = o
                levels[side][p] -= q
                acc[4 if side == 'B' else 5] += q
                queues[(side, p)].remove(oid)
                if levels[side][p] <= 0:
                    del levels[side][p]
                    if p == best[side]:
                        refresh(side)
                continue
            side, q, p, life = row[3], int(row[4]), int(row[5]), row[6]
            filled = take(side, p, q)
            acc[0 if side == 'B' else 1] += filled
            q -= filled
            if q > 0 and life == 'G':
                bt = best[side]
                if bt is None or (p >= bt if side == 'B' else p <= bt):
                    acc[2 if side == 'B' else 3] += q
                orders[oid] = [side, p, q]
                levels[side][p] = levels[side].get(p, 0) + q
                queues.setdefault((side, p), deque()).append(oid)
                if bt is None or (p > bt if side == 'B' else p < bt):
                    best[side] = p
    return rows


def window_sum(x: list, w: float) -> list:
    k = int(round(w / DT))
    out, s = [], 0.0
    for i, v in enumerate(x):
        s += v
        if i >= k:
            s -= x[i - k]
        out.append(s)
    return out


def corr(x: list, y: list) -> float:
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    return sxy / math.sqrt(sxx * syy) if sxx > 0 and syy > 0 else 0.0


def ols(X: list, y: list) -> list:
    """Least squares through the normal equations (Gauss-Jordan); X rows include the constant."""
    m = len(X[0])
    A = [[0.0] * (m + 1) for _ in range(m)]
    for row, v in zip(X, y):
        for i in range(m):
            ri = row[i]
            for j in range(m):
                A[i][j] += ri * row[j]
            A[i][m] += ri * v
    for c in range(m):
        piv = max(range(c, m), key=lambda r: abs(A[r][c]))
        A[c], A[piv] = A[piv], A[c]
        for r in range(m):
            if r != c and A[c][c]:
                f = A[r][c] / A[c][c]
                for j in range(c, m + 1):
                    A[r][j] -= f * A[c][j]
    return [A[i][m] / A[i][i] for i in range(m)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('data')
    ap.add_argument('--trades', default=None)
    ap.add_argument('--holdout', type=float, default=0.25)
    args = ap.parse_args()
    rows = replay(args.data)
    n = len(rows)
    t = [r[0] for r in rows]
    mid = [(r[1] + r[2]) / 2 for r in rows]
    feats = {}
    feats['imb1'] = [(r[3][0] - r[4][0]) / max(1, r[3][0] + r[4][0]) for r in rows]
    feats['imb5'] = [(sum(r[3]) - sum(r[4])) / max(1, sum(r[3]) + sum(r[4])) for r in rows]
    agg = [r[5] - r[6] for r in rows]
    ins = [r[7] - r[8] for r in rows]
    cxl = [r[9] - r[10] for r in rows]
    for w in (0.5, 5, 30):
        feats[f'flow{w}'] = window_sum(agg, w)
        feats[f'ins{w}'] = window_sum(ins, w)
        feats[f'cxl{w}'] = window_sum(cxl, w)
    for w in (5, 30, 120):
        k = int(w / DT)
        feats[f'ret{w}'] = [mid[i] - mid[max(0, i - k)] for i in range(n)]
    for w in (60, 300):
        ma = window_sum(mid, w)
        k = int(w / DT)
        feats[f'dev{w}'] = [mid[i] - ma[i] / min(i + 1, k) for i in range(n)]
    cut = int((1 - args.holdout) * n)
    print(f'{n} samples every {DT} s; fit on the first {cut}, check on the last {n - cut}')
    model = ['imb1', 'imb5', 'flow0.5', 'flow5']
    for H in HORIZONS:
        k = int(round(H / DT))
        y = [mid[i + k] - mid[i] for i in range(n - k)]
        tr = range(0, cut - k)
        te = range(cut, n - k)
        yt = [y[i] for i in tr]
        yo = [y[i] for i in te]
        sd = math.sqrt(sum(v * v for v in yt) / len(yt))
        print(f'\nH {H} s, sd of the move {sd:.3f} ticks; feature corr in / out:')
        print('  ' + '  '.join(f'{nm} {corr([feats[nm][i] for i in tr], yt):+.3f}/{corr([feats[nm][i] for i in te], yo):+.3f}' for nm in feats))
        X = [[1.0] + [feats[nm][i] / (100 if nm.startswith('flow') else 1) for nm in model] for i in range(n - k)]
        beta = ols([X[i] for i in tr], yt)
        pred = [sum(b * x for b, x in zip(beta, X[i])) for i in range(n - k)]
        print(f'  OLS on {model} (flow per 100 lots): weights {[round(b, 3) for b in beta]}, corr in {corr([pred[i] for i in tr], yt):.3f} out {corr([pred[i] for i in te], yo):.3f}')
        for lo, hi in ((-9, -0.5), (-0.5, -0.25), (-0.25, 0.25), (0.25, 0.5), (0.5, 9)):
            mi = [y[i] for i in tr if lo <= pred[i] < hi]
            mo = [y[i] for i in te if lo <= pred[i] < hi]
            print(f'    forecast [{lo}, {hi}): in n {len(mi)} move {sum(mi) / max(1, len(mi)):+.3f} | out n {len(mo)} move {sum(mo) / max(1, len(mo)):+.3f}')
    if args.trades:
        fills = []
        with open(args.trades) as f:
            for r in csv.DictReader(f):
                if 'user' not in (r['taker_owner'], r['maker_owner']):
                    continue
                q = int(r['quantity'])
                buy = (r['taker_side'] == 'B') == (r['taker_owner'] == 'user')
                fills.append((int(r['timestamp_us']) / 1e6, q if buy else -q))
        pos, j, p = [], 0, 0
        for ti in t:
            while j < len(fills) and fills[j][0] <= ti:
                p += fills[j][1]
                j += 1
            pos.append(p)
        print(f'\nthe run: {len(fills)} fills, mean |position| {sum(abs(v) for v in pos) / n:.1f}')
        for H in (1, 5, 30):
            k = int(H / DT)
            fut = [mid[i + k] - mid[i] for i in range(n - k)]
            print(f'  H {H} s: corr(position, move ahead) {corr(pos[:n - k], fut):+.4f}; position x move per s {sum(a * b for a, b in zip(pos, fut)) / (n - k) / H:+.3f}')
        q4 = n // 4
        print('  inventory PnL (sum position x the mid change) by quarter:', [round(sum(pos[i] * (mid[i + 1] - mid[i]) for i in range(s * q4, min(n - 1, (s + 1) * q4)))) for s in range(4)])
        print('  corr(position, the imb1/imb5 forecast):', round(corr(pos, [0.383 * a - 0.213 * b for a, b in zip(feats['imb1'], feats['imb5'])]), 4))


if __name__ == '__main__':
    main()
