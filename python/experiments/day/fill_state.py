"""Our maker fills' value by the book's state just before the fill (7 Nov, round 1).

Replays BOT on DATA through their simulator with OrderBook.insert and the strategy's on_order_book_change wrapped
(nothing else changed; fill_queue's method). For each of our maker fills (a market taker against our resting order) it
records the state at the last snapshot before the fill: the market lots at our price on our side and one tick behind
it, the opposite touch's lots, both touches' lots, the change of our side's touch lots over the last OFI_MS ms (0 once
the touch price has moved), the time since that touch price last changed, the aggressive order's total lots, our
position signed toward the fill's side (+: the fill adds to it), the spread, the market lots ahead of our order when it
landed and the order's age; then the edge against the mid before the fill and the mid's move our way 1 s and 5 s later
(fill_queue's convention: the market-only mid series). Prints the lot-weighted net (ticks a lot) by each feature (bins
by lot-weighted quantiles unless fixed), four two-way tables, and a lot-weighted linear fit of the 1-s net on the
standardised features: coefficients, R^2 and the net by decile of the fitted value.

    uv run python -m experiments.day.fill_state BOT DATA [--dump rows.csv]
    uv run python -m experiments.day.fill_state --load rows.csv      # the tables again, no replay
"""

from __future__ import annotations

import argparse
import bisect
import csv
from collections import defaultdict, deque
from pathlib import Path

OFI_MS = 300
AHEAD_BINS = [0, 1, 50, 200, 400, 800, 1600, 10**9]
TAKER_BINS = [0, 25, 100, 200, 400, 800, 10**9]
SPREAD_BINS = [1, 2, 3, 4, 5, 10**9]
PLACE_BINS = [-10, 0, 1, 2, 10**9]  # our price against the market touch on our side: inside, at, one behind, deeper
COLS = ['ts', 'sign', 'price', 'qty', 'taker', 'depth_at', 'depth_behind', 'opp', 'bid_lots', 'ask_lots', 'ofi',
        'since_ms', 'spread', 'pos', 'ahead', 'age_ms', 'place', 'edge', 'move1', 'move5']
C = {name: k for k, name in enumerate(COLS)}
FEATURES = [  # name, column, fixed bins or None (lot-weighted quintiles), forced bin edges
    ('market lots at our price (touch depth)', 'depth_at', None, (0, 1)),
    ('market lots one tick behind our price', 'depth_behind', None, (0, 1)),
    ('market lots at the opposite touch', 'opp', None, ()),
    (f'our touch lots now minus {OFI_MS} ms ago (OFI)', 'ofi', None, (0, 1)),
    ('ms since our touch price changed', 'since_ms', None, ()),
    ("the aggressive order's lots", 'taker', TAKER_BINS, ()),
    ('our position toward the fill side', 'pos', None, (0,)),
    ('spread (ticks)', 'spread', SPREAD_BINS, ()),
    ('market lots ahead at landing', 'ahead', AHEAD_BINS, ()),
    ('our order age (ms)', 'age_ms', None, ()),
    ('our price against the touch (ticks behind)', 'place', PLACE_BINS, ()),
]
MODEL = ['depth_at', 'depth_behind', 'opp', 'ofi', 'since_ms', 'spread', 'pos', 'ahead', 'age_ms']


def run(bot: Path, data: Path):
    from simulator import simulator as sim
    from simulator.main import (
        MAX_POSITION,
        MAX_POTENTIAL_POSITION,
        ORDER_ACCEPT_DELAY_MS,
        POSITION_BREACH_PENALTY_PER_SECOND,
        load_strategy_from_file,
    )
    from simulator.models import Side

    landed = {}  # our order id -> (market lots ahead at landing, landing time us)
    orig_insert = sim.OrderBook.insert

    def insert(self, order):
        if order.owner == 'user' and order.order_type.value == 'limit':
            level = (self._bids if order.side == Side.BUY else self._asks).get(order.price)
            mkt = 0
            if level is not None:
                for o in level.queue:
                    if o.owner == 'market':
                        mkt += o.remaining_quantity
            landed[order.order_id] = (mkt, order.created_at_us)
        return orig_insert(self, order)

    sim.OrderBook.insert = insert
    strategy = load_strategy_from_file(bot)
    inner = strategy.on_order_book_change
    times, mids = [], []  # the market-only mid at each change of a touch
    taker_lots = defaultdict(int)
    fills = []  # COLS up to 'place', with the taker's order id in 'taker'
    skipped = [0]
    touch = {'bid': [None, 0, 0, deque()], 'ask': [None, 0, 0, deque()]}  # price, lots, ts of the last price change, (ts, price, lots) at each change
    versions = {'bid': -1, 'ask': -1}
    holder = {'prev': None, 'pos': 0}
    ofi_us = OFI_MS * 1000

    def record(t, buy):
        prev = holder['prev']
        side, opp = ('bid', 'ask') if buy else ('ask', 'bid')
        price, lots, changed_ts, hist = touch[side]
        if prev is None or price is None or touch[opp][0] is None or t.maker_order_id not in landed:
            skipped[0] += 1
            return
        p = t.price
        behind = p - 1 if buy else p + 1
        at = beh = 0
        for o in prev.bids if buy else prev.asks:
            if o.owner != 'market':
                continue
            if o.price == p:
                at += o.quantity
            elif o.price == behind:
                beh += o.quantity
            elif (o.price < behind) if buy else (o.price > behind):
                break
        ts0 = prev.timestamp_us
        since = ts0 - changed_ts
        ofi = 0
        if since >= ofi_us:
            cutoff = ts0 - ofi_us
            while len(hist) >= 2 and hist[1][0] <= cutoff:
                hist.popleft()
            if hist[0][0] <= cutoff and hist[0][1] == price:
                ofi = lots - hist[0][2]
        sign = 1 if buy else -1
        ahead, landed_ts = landed[t.maker_order_id]
        fills.append([t.timestamp_us, sign, p, t.quantity, t.taker_order_id, at, beh, touch[opp][1], touch['bid'][1],
                      touch['ask'][1], ofi, since / 1000, touch['ask'][0] - touch['bid'][0], sign * holder['pos'], ahead,
                      (t.timestamp_us - landed_ts) / 1000, (price - p) * sign])

    def on_book(snapshot, new_trades):
        for t in new_trades:
            taker_lots[t.taker_order_id] += t.quantity
            if t.maker_owner == 'user':
                buy = t.book_side == 'bid'
                if t.taker_owner != 'user':
                    record(t, buy)
                holder['pos'] += t.quantity if buy else -t.quantity
            elif t.taker_owner == 'user':
                holder['pos'] += -t.quantity if t.book_side == 'bid' else t.quantity
        if snapshot is not holder['prev']:  # the bot re-enters with its last snapshot after a cancel lands
            ts = snapshot.timestamp_us
            book = simulator.book
            changed = False
            for side, version, orders in (('bid', book.bid_version, snapshot.bids), ('ask', book.ask_version, snapshot.asks)):
                if version == versions[side]:
                    continue
                versions[side] = version
                price = None
                lots = 0
                for o in orders:
                    if o.owner == 'market':
                        if price is None:
                            price = o.price
                        elif o.price != price:
                            break
                        lots += o.quantity
                state = touch[side]
                if price != state[0] or lots != state[1]:
                    if price != state[0]:
                        state[2] = ts
                    state[0], state[1] = price, lots
                    state[3].append((ts, price, lots))
                    changed = True
            if changed and touch['bid'][0] is not None and touch['ask'][0] is not None:
                mid = (touch['bid'][0] + touch['ask'][0]) / 2
                if times and times[-1] == ts:
                    mids[-1] = mid
                else:
                    times.append(ts)
                    mids.append(mid)
            holder['prev'] = snapshot
        inner(snapshot, new_trades)

    strategy.on_order_book_change = on_book
    config = sim.SimulationConfig(
        public_depth=20, max_position=MAX_POSITION, max_potential_position=MAX_POTENTIAL_POSITION,
        position_breach_penalty_per_second=POSITION_BREACH_PENALTY_PER_SECOND,
        order_accept_delay_ms=ORDER_ACCEPT_DELAY_MS, show_progress=False,
    )
    simulator = sim.ExchangeSimulator(strategy=strategy, config=config)
    result = simulator.run(data)
    sim.OrderBook.insert = orig_insert
    print(f'pnl {result.pnl:,.0f}; our orders landed {len(landed):,}; position counted from the trades {holder["pos"]:+d},'
          f' the simulator\'s {result.inventory:+d}; fills skipped {skipped[0]}')
    rows = []
    for f in fills:
        ts, sign, price = f[0], f[1], f[2]
        i = bisect.bisect_left(times, ts) - 1  # the mid before the fill
        j1 = bisect.bisect_right(times, ts + 1_000_000) - 1
        j5 = bisect.bisect_right(times, ts + 5_000_000) - 1
        if i < 0:
            continue
        f[C['taker']] = taker_lots[f[C['taker']]]
        rows.append(f + [sign * (mids[i] - price), sign * (mids[j1] - mids[i]), sign * (mids[j5] - mids[i])])
    return rows


def bin_of(bins, x):
    return max(0, bisect.bisect_right(bins, x) - 1)


def fmt(x):
    return f'{int(x)}' if float(x).is_integer() else f'{x:.4g}'


def label(bins, i):
    hi = bins[i + 1]
    return f'[{fmt(bins[i])},{fmt(hi) if hi < 10**8 else "inf"})'


def quantile_bins(rows, col, qs=(0.2, 0.4, 0.6, 0.8), force=()):
    """Bin edges at the lot-weighted quantiles `qs` of column `col`, plus `force`, with a sentinel at the end."""
    pairs = sorted((r[col], r[C['qty']]) for r in rows)
    total = sum(q for _, q in pairs)
    edges = {pairs[0][0], *force}
    cum = 0
    k = 0
    for v, q in pairs:
        cum += q
        while k < len(qs) and cum >= qs[k] * total:
            edges.add(v)
            k += 1
    return sorted(edges) + [10**9]


def one_way(rows, total, name, col, bins):
    print(f'by {name}:')
    agg = defaultdict(lambda: [0, 0, 0.0, 0.0, 0.0])
    for r in rows:
        a = agg[bin_of(bins, r[col])]
        q = r[C['qty']]
        a[0] += 1
        a[1] += q
        a[2] += r[C['edge']] * q
        a[3] += r[C['move1']] * q
        a[4] += r[C['move5']] * q
    for k in sorted(agg):
        n, lots, e, m1, m5 = agg[k]
        print(f'  {label(bins, k):>18}: fills {n:8,}  lots {lots:10,} ({lots / total:5.1%})  edge {e / lots:+.3f}'
              f'  move1 {m1 / lots:+.3f}  net1 {(e + m1) / lots:+.3f}  net5 {(e + m5) / lots:+.3f}')


def two_way(rows, total, name_a, col_a, bins_a, name_b, col_b, bins_b):
    print(f'net1 ticks a lot (lots share) by {name_a} (rows) x {name_b} (columns):')
    cross = defaultdict(lambda: [0, 0.0])
    for r in rows:
        c = cross[(bin_of(bins_a, r[col_a]), bin_of(bins_b, r[col_b]))]
        c[0] += r[C['qty']]
        c[1] += (r[C['edge']] + r[C['move1']]) * r[C['qty']]
    cols = [k for k in range(len(bins_b) - 1) if any(key[1] == k for key in cross)]
    print(' ' * 18 + ''.join(f'{label(bins_b, k):>18}' for k in cols))
    for a in range(len(bins_a) - 1):
        if not any(key[0] == a for key in cross):
            continue
        cells = []
        for k in cols:
            lots, net = cross.get((a, k), [0, 0.0])
            cells.append(f'{net / lots:+.2f} ({lots / total:4.1%})' if lots else '-')
        print(f'{label(bins_a, a):>18}' + ''.join(f'{c:>18}' for c in cells))


def regress(rows, total):
    import numpy as np

    X = np.array([[r[C[n]] for n in MODEL] for r in rows], dtype=float)
    w = np.array([r[C['qty']] for r in rows], dtype=float)
    y = np.array([r[C['edge']] + r[C['move1']] for r in rows], dtype=float)
    y5 = np.array([r[C['edge']] + r[C['move5']] for r in rows], dtype=float)
    mean = (X * w[:, None]).sum(0) / total
    sd = np.sqrt((((X - mean) ** 2) * w[:, None]).sum(0) / total)
    Z = (X - mean) / sd
    A = np.hstack([np.ones((len(rows), 1)), Z]) * np.sqrt(w)[:, None]
    coef = np.linalg.lstsq(A, y * np.sqrt(w), rcond=None)[0]
    fitted = coef[0] + Z @ coef[1:]
    ybar = (y * w).sum() / total
    r2 = 1 - (((y - fitted) ** 2) * w).sum() / (((y - ybar) ** 2) * w).sum()
    print(f'linear fit of the 1-s net on standardised features (lot-weighted), {len(rows):,} fills: R^2 {r2:.4f},'
          f' intercept {coef[0]:+.4f}')
    print('  coefficient: ticks a lot per one sd of the feature (lot-weighted mean, sd)')
    for k, name in enumerate(MODEL):
        print(f'  {name:>13}: {coef[k + 1]:+.4f}   (mean {mean[k]:,.1f}, sd {sd[k]:,.1f})')
    order = np.argsort(fitted, kind='stable')
    cum = np.cumsum(w[order])
    dec = np.minimum(((cum - w[order] / 2) / total * 10).astype(int), 9)
    print('by decile of the fitted value (lots share, the fit, the realised net1 and net5):')
    for d in range(10):
        pick = order[dec == d]
        lots = w[pick].sum()
        if not lots:
            continue
        print(f'  decile {d + 1:2d}: lots {int(lots):10,} ({lots / total:5.1%})  fitted {(fitted[pick] * w[pick]).sum() / lots:+.3f}'
              f'  net1 {(y[pick] * w[pick]).sum() / lots:+.3f}  net5 {(y5[pick] * w[pick]).sum() / lots:+.3f}')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('bot', type=Path, nargs='?')
    parser.add_argument('data', type=Path, nargs='?')
    parser.add_argument('--dump', type=Path, help='write the per-fill rows here')
    parser.add_argument('--load', type=Path, help='table these per-fill rows instead of replaying')
    args = parser.parse_args()
    if args.load:
        with open(args.load, newline='') as f:
            reader = csv.reader(f)
            if next(reader) != COLS:
                parser.error(f'{args.load} does not hold {COLS}')
            rows = [[float(v) for v in r] for r in reader]
    else:
        if args.bot is None or args.data is None:
            parser.error('BOT and DATA are needed without --load')
        rows = run(args.bot, args.data)
        if args.dump:
            with open(args.dump, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(COLS)
                writer.writerows(rows)
    total = sum(r[C['qty']] for r in rows)
    e = sum(r[C['edge']] * r[C['qty']] for r in rows) / total
    m1 = sum(r[C['move1']] * r[C['qty']] for r in rows) / total
    m5 = sum(r[C['move5']] * r[C['qty']] for r in rows) / total
    print(f'maker fills {len(rows):,}, lots {int(total):,}: edge {e:+.3f}, move1 {m1:+.3f}, move5 {m5:+.3f},'
          f' net1 {e + m1:+.3f}, net5 {e + m5:+.3f} ticks a lot')
    bins = {}
    for name, col, fixed, force in FEATURES:
        bins[col] = fixed or quantile_bins(rows, C[col], force=force)
        one_way(rows, total, name, C[col], bins[col])
    two_way(rows, total, 'touch depth', C['depth_at'], bins['depth_at'], 'aggressor lots', C['taker'], bins['taker'])
    two_way(rows, total, 'depth behind', C['depth_behind'], bins['depth_behind'], 'aggressor lots', C['taker'], bins['taker'])
    two_way(rows, total, 'OFI', C['ofi'], bins['ofi'], 'touch depth', C['depth_at'], bins['depth_at'])
    two_way(rows, total, 'depth behind', C['depth_behind'], bins['depth_behind'], 'touch depth', C['depth_at'], bins['depth_at'])
    regress(rows, total)


if __name__ == '__main__':
    main()
