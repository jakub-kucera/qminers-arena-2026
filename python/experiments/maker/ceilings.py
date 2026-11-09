"""Ceilings for a maker on one tape, read from a full-logs run (7 Nov, round 1): where a bigger PnL can come from.

From LOG_DIR (`exchange-simulator ... --log-dir LOG_DIR` without --no-logs): the market's own book (book_deltas.csv,
owner market) gives the touch and the mid at every change; trades.csv gives every trade. It prints
1. the market's aggressive (taker) lots per side, how many hit the touch, and how many met our orders;
2. our fills' edge a lot (maker / taker, by spread, by the aggressor's size, by the market lots still ahead of us in
   the queue at the fill), against the mid before the fill (e_m0) and 1 / 5 / 60 s later;
3. ceilings: a maker at the FRONT of every touch queue with Q lots a side, all its fills kept within +-100 (no
   foresight; marked at the last mid), the same with 1 s foresight (fill only when the mid 1 s later pays), a taker with
   1 s foresight (50 ms grid, up to the touch lots), and the edge of the first N lots of every aggressor;
4. every touch-hitting aggressor classed by our state just before it: filled, no room (the limit), not quoted (no
   lots at that price), quoted but behind (lots there, none filled), with what a front-of-queue 50-lot maker would have
   made in each (f50, 1 s markout).

    uv run python -m experiments.maker.ceilings LOG_DIR
"""

from __future__ import annotations

import argparse
import csv

import numpy as np
import pandas as pd

SIZE_BINS = [0, 20, 50, 100, 200, 400, 800, 10**9]


def market_book(log_dir: str) -> dict:
    """The market-only touch (prices and lots) after every book change, one row per timestamp."""
    lv = {'B': {}, 'A': {}}
    rows = []
    with open(log_dir + '/book_deltas.csv') as f:
        r = csv.reader(f)
        next(r)
        for ts, side, price, owner, q in r:
            if owner != 'market':
                continue
            d = lv[side]
            p = int(price)
            v = d.get(p, 0) + int(q)
            if v <= 0:
                d.pop(p, None)
            else:
                d[p] = v
            if lv['B'] and lv['A']:
                b = max(lv['B'])
                a = min(lv['A'])
                row = (int(ts), b, a, lv['B'][b], lv['A'][a])
                if rows and rows[-1][0] == row[0]:
                    rows[-1] = row
                else:
                    rows.append(row)
    arr = np.array(rows)
    return {'t': arr[:, 0], 'b': arr[:, 1], 'a': arr[:, 2], 'lb': arr[:, 3], 'la': arr[:, 4]}


def lot_summary(g: pd.DataFrame, cols=('e_m0', 'e_m1', 'e_m5', 'e_m60')) -> pd.Series:
    q = g.quantity
    out = {'lots': q.sum()}
    for c in cols:
        out[c] = (g[c] * q).sum() / q.sum()
    out['pnl_1s'] = (g.e_m1 * q).sum()
    return pd.Series(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('log_dir')
    args = parser.parse_args()
    pd.set_option('display.width', 250)
    bk = market_book(args.log_dir)
    t, b, a, lb, la = bk['t'], bk['b'], bk['a'], bk['lb'], bk['la']
    mid = (a + b) / 2

    def idx(ts, lag=0, before=True):
        i = np.searchsorted(t, ts + lag, side='left' if before else 'right') - 1
        return np.clip(i, 0, len(t) - 1)

    tr = pd.read_csv(args.log_dir + '/trades.csv')
    tr['i0'] = idx(tr.timestamp_us.values)
    for lag, name in ((0, 'm0'), (1_000_000, 'm1'), (5_000_000, 'm5'), (60_000_000, 'm60')):
        tr[name] = mid[idx(tr.timestamp_us.values, lag, before=lag == 0)]
    tr['spread'] = (a - b)[tr.i0]
    tr['bb'] = b[tr.i0]
    tr['ba'] = a[tr.i0]
    mkt = tr[tr.taker_owner == 'market'].copy()
    tr['aggsize'] = tr.taker_order_id.map(mkt.groupby('taker_order_id').quantity.sum()).fillna(0)
    mkt['aggsize'] = tr.loc[mkt.index, 'aggsize']
    mkt['mdir'] = np.where(mkt.taker_side == 'A', 1, -1)  # the maker's side: +1 buys
    mkt['attouch'] = np.where(mkt.taker_side == 'A', mkt.price == mkt.bb, mkt.price == mkt.ba)
    for name in ('m0', 'm1', 'm60'):
        mkt['e' + name[1:]] = mkt.mdir * (mkt[name] - mkt.price)

    print('1. market aggressive lots')
    for s in ('A', 'B'):
        m = mkt[mkt.taker_side == s]
        print(f"   taker {s}: {m.quantity.sum():,} lots, {m[m.attouch].quantity.sum():,} at the touch, {m[m.maker_owner != 'market'].quantity.sum():,} against us")
    print('   lots by spread:', mkt.groupby('spread').quantity.sum().head(4).to_dict())

    us = tr[(tr.maker_owner != 'market') | (tr.taker_owner != 'market')].copy()
    us['maker'] = us.maker_owner != 'market'
    us['ourdir'] = np.where(us.maker, np.where(us.taker_side == 'A', 1, -1), np.where(us.taker_side == 'B', 1, -1))
    for name in ('m0', 'm1', 'm5', 'm60'):
        us['e_' + name] = us.ourdir * (us[name] - us.price)
    print('\n2. our fills, ticks a lot (maker True / False)')
    print(us.groupby('maker').apply(lot_summary).round(3).to_string())
    mk = us[us.maker].copy()
    print('   maker fills by spread')
    print(mk.groupby(mk.spread.clip(upper=3)).apply(lot_summary).round(3).to_string())
    print('   maker fills by the aggressor\'s size')
    print(mk.groupby(pd.cut(mk.aggsize, SIZE_BINS)).apply(lot_summary).round(3).to_string())
    m2 = tr[tr.taker_owner == 'market'].copy()
    m2['mk'] = (m2.maker_owner == 'market') * m2.quantity
    m2['ahead'] = m2.groupby(['taker_order_id', 'price']).mk.cumsum() - m2.mk
    ours = m2[m2.maker_owner != 'market'][['timestamp_us', 'taker_order_id', 'price', 'ahead']].drop_duplicates(['taker_order_id', 'price'])
    mk = mk.merge(ours, on=['timestamp_us', 'taker_order_id', 'price'], how='left')
    print('   maker fills by the market lots ahead of us that the aggressor took first (0: we were at the front)')
    print(mk.groupby(pd.cut(mk.ahead, [-1, 0, 20, 100, 300, 1000, 10**9])).apply(lot_summary).round(3).to_string())

    tt = mkt[mkt.attouch]
    ev = tt.groupby('taker_order_id').agg(ts=('timestamp_us', 'first'), p=('price', 'first'), q=('quantity', 'sum'), d=('mdir', 'first'), m1=('m1', 'first'), size=('aggsize', 'first')).sort_values('ts').reset_index()
    ts, p, q, d, m1, size = (ev[c].values for c in ('ts', 'p', 'q', 'd', 'm1', 'size'))
    final = mid[-1]

    def front(Q, cap=100, foresight=False):
        pos = 0
        cash = 0.0
        lots = 0
        for i in range(len(ts)):
            if foresight and d[i] * (m1[i] - p[i]) <= 0:
                continue
            room = cap - pos if d[i] > 0 else cap + pos
            x = min(Q, q[i], room)
            if x > 0:
                pos += d[i] * x
                cash -= d[i] * x * p[i]
                lots += x
        return round(cash + pos * final), lots

    print(f'\n3. ceilings ({len(ev):,} aggressors hit the touch, {q.sum():,} lots)')
    for Q in (20, 50, 100, 200):
        print(f'   front of every touch queue, {Q} lots a side, +-100, no foresight: pnl, lots', front(Q))
    for Q in (50, 100, 200):
        print(f'   the same with 1 s foresight (fill only when it pays): pnl, lots', front(Q, foresight=True))
    print('   front, 200 lots, no limit:', front(200, cap=10**9))
    grid = np.arange(t[0], t[-1] - 1_000_000, 50_000)
    i0 = np.searchsorted(t, grid, side='right') - 1
    i1 = np.searchsorted(t, grid + 1_000_000, side='right') - 1
    pos = 0
    cash = 0.0
    lots = 0
    for k in range(len(grid)):
        j = i0[k]
        fut = mid[i1[k]]
        if fut > a[j] and pos < 100:
            x = min(100 - pos, la[j])
            pos += x
            cash -= x * a[j]
            lots += x
        elif fut < b[j] and pos > -100:
            x = min(100 + pos, lb[j])
            pos -= x
            cash += x * b[j]
            lots += x
    print('   taker with 1 s foresight (50 ms grid, +-100): pnl, lots', (round(cash + pos * final), lots))
    fr = tt.copy()
    fr['cum'] = fr.groupby('taker_order_id').quantity.cumsum()
    for N in (10, 50, 100, 200):
        g = fr[fr.cum - fr.quantity < N]
        qq = np.minimum(g.quantity, N - (g.cum - g.quantity))
        print(f'   the first {N} lots of every aggressor: {qq.sum():,.0f} lots, edge 1 s {(g.e1 * qq).sum() / qq.sum():.3f}, at the fill {(g.e0 * qq).sum() / qq.sum():.3f}')

    # 4. our state at each touch aggressor
    ev['ours'] = tt[tt.maker_owner != 'market'].groupby('taker_order_id').quantity.sum().reindex(ev.taker_order_id).fillna(0).values
    mine = {'B': {}, 'A': {}}
    have = np.zeros(len(ev))
    k = 0
    with open(args.log_dir + '/book_deltas.csv') as f:
        r = csv.reader(f)
        next(r)
        for tstr, side, price, owner, qd in r:
            tsv = int(tstr)
            while k < len(ts) and ts[k] <= tsv:
                have[k] = mine['B' if d[k] > 0 else 'A'].get(p[k], 0)
                k += 1
            if owner != 'market':
                dd = mine[side]
                pr = int(price)
                dd[pr] = dd.get(pr, 0) + int(qd)
    ev['have'] = have
    sgn = us.ourdir.values * us.quantity.values
    pos_t = us.timestamp_us.values
    pos_c = np.cumsum(sgn)
    i = np.searchsorted(pos_t, ts, side='left') - 1
    ev['pos'] = np.where(i >= 0, pos_c[np.clip(i, 0, None)], 0)
    ev['room'] = np.where(ev.d > 0, 100 - ev.pos, 100 + ev.pos)
    ev['f50'] = np.minimum(np.minimum(50, ev.q), ev.room.clip(lower=0))
    ev['e1'] = ev.d * (ev.m1 - ev.p)
    ev['state'] = np.select([ev.room <= 0, ev.have == 0, ev.ours == 0], ['no room', 'not quoted', 'quoted, behind'], 'filled')
    summ = lambda g: pd.Series({'events': len(g), 'agg_lots': g.q.sum(), 'f50_lots': g.f50.sum(), 'f50_pnl1s': (g.f50 * g.e1).sum(), 'our_lots': g.ours.sum(), 'our_pnl1s': (g.ours * g.e1).sum(), 'first_lot_e1': g.e1.mean(), 'our_lots_there': g.have.mean()})
    print('\n4. touch aggressors by our state just before them')
    print(ev.groupby('state').apply(summ).round(2).to_string())
    for st in ('quoted, behind', 'not quoted'):
        x = ev[ev.state == st]
        print(f'   {st}, by the aggressor\'s size')
        print(x.groupby(pd.cut(x['size'], SIZE_BINS)).apply(lambda g: pd.Series({'events': len(g), 'f50_pnl1s': (g.f50 * g.e1).sum(), 'first_lot_e1': g.e1.mean()})).round(2).to_string())


if __name__ == '__main__':
    main()
