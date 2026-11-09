"""Our maker fills' markout by where our order sat in the queue (7 Nov, round 1).

Replays BOT on DATA with their OrderBook's insert wrapped (nothing else changed) to record, for each of our limit
orders, the market and own lots ahead of it when it landed and its size; the strategy's callbacks are wrapped to record
the market mid (market-owned touches) and every trade. For each of our maker fills: the edge at the fill against the
mid before it, the mid's move our way HORIZON seconds later, and the net (ticks a lot, lot-weighted), split by the
market lots ahead at landing, by our order's landing size, by the aggressive order's total lots, and by the two crossed.

    uv run python -m experiments.maker.fill_queue BOT DATA [--horizon 1]
"""

from __future__ import annotations

import argparse
import bisect
from collections import defaultdict
from pathlib import Path

from simulator import simulator as sim
from simulator.main import (
    MAX_POSITION,
    MAX_POTENTIAL_POSITION,
    ORDER_ACCEPT_DELAY_MS,
    POSITION_BREACH_PENALTY_PER_SECOND,
    load_strategy_from_file,
)
from simulator.models import Side

AHEAD_BINS = [0, 1, 50, 200, 400, 800, 1600, 10**9]
SIZE_BINS = [1, 25, 50, 100, 150, 201]
TAKER_BINS = [0, 25, 100, 200, 400, 800, 10**9]


def run(bot: Path, data: Path):
    landed = {}  # our order id -> [market lots ahead, own lots ahead, size]
    orig_insert = sim.OrderBook.insert

    def insert(self, order):
        if order.owner == 'user' and order.order_type.value == 'limit':
            levels = self._bids if order.side == Side.BUY else self._asks
            level = levels.get(order.price)
            mkt = own = 0
            if level is not None:
                for o in level.queue:
                    if o.owner == 'market':
                        mkt += o.remaining_quantity
                    else:
                        own += o.remaining_quantity
            landed[order.order_id] = [mkt, own, order.initial_quantity]
        return orig_insert(self, order)

    sim.OrderBook.insert = insert
    strategy = load_strategy_from_file(bot)
    times, mids, trades = [], [], []
    inner = strategy.on_order_book_change

    def on_book(snapshot, new_trades):
        trades.extend(new_trades)
        bid = next((o.price for o in snapshot.bids if o.owner == 'market'), None)
        ask = next((o.price for o in snapshot.asks if o.owner == 'market'), None)
        if bid is not None and ask is not None:
            if times and times[-1] == snapshot.timestamp_us:
                mids[-1] = (bid + ask) / 2
            else:
                times.append(snapshot.timestamp_us)
                mids.append((bid + ask) / 2)
        inner(snapshot, new_trades)

    strategy.on_order_book_change = on_book
    config = sim.SimulationConfig(
        public_depth=20, max_position=MAX_POSITION, max_potential_position=MAX_POTENTIAL_POSITION,
        position_breach_penalty_per_second=POSITION_BREACH_PENALTY_PER_SECOND,
        order_accept_delay_ms=ORDER_ACCEPT_DELAY_MS, show_progress=False,
    )
    result = sim.ExchangeSimulator(strategy=strategy, config=config).run(data)
    sim.OrderBook.insert = orig_insert
    return result, landed, times, mids, trades


def bin_of(bins, x):
    return max(0, bisect.bisect_right(bins, x) - 1)


def label(bins, i):
    hi = bins[i + 1]
    return f'[{bins[i]},{hi if hi < 10**8 else "inf"})'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('bot', type=Path)
    parser.add_argument('data', type=Path)
    parser.add_argument('--horizon', type=float, default=1.0)
    args = parser.parse_args()
    result, landed, times, mids, trades = run(args.bot, args.data)
    print(f'pnl {result.pnl:,.0f}; our orders landed {len(landed):,}')
    taker_lots = defaultdict(int)
    for t in trades:
        taker_lots[t.taker_order_id] += t.quantity
    h = int(args.horizon * 1_000_000)
    rows = []  # [ahead, size, taker, lots, edge*lots, move*lots]
    for t in trades:
        if t.maker_owner != 'user' or t.taker_owner == 'user' or t.maker_order_id not in landed:
            continue
        i = bisect.bisect_left(times, t.timestamp_us) - 1  # the mid before the fill
        j = bisect.bisect_right(times, t.timestamp_us + h) - 1
        if i < 0 or j < 0:
            continue
        buy = t.book_side == 'bid'
        sign = 1 if buy else -1
        edge = sign * (mids[i] - t.price)
        move = sign * (mids[j] - mids[i])
        mkt, _, size = landed[t.maker_order_id]
        rows.append([mkt, size, taker_lots[t.taker_order_id], t.quantity, edge * t.quantity, move * t.quantity])
    total = sum(r[3] for r in rows)
    print(f'maker fills {len(rows):,}, lots {total:,}, net {sum(r[4] + r[5] for r in rows) / total:+.3f} ticks a lot')
    for name, col, bins in (('market lots ahead at landing', 0, AHEAD_BINS), ('our order size at landing', 1, SIZE_BINS),
                            ("the aggressive order's lots", 2, TAKER_BINS)):
        print(f'by {name}:')
        agg = defaultdict(lambda: [0, 0, 0.0, 0.0])
        for r in rows:
            a = agg[bin_of(bins, r[col])]
            a[0] += 1
            a[1] += r[3]
            a[2] += r[4]
            a[3] += r[5]
        for k in sorted(agg):
            n, lots, e, m = agg[k]
            print(f'  {label(bins, k):>14}: fills {n:8,}  lots {lots:10,} ({lots / total:5.1%})  edge {e / lots:+.3f}'
                  f'  move {m / lots:+.3f}  net {(e + m) / lots:+.3f}')
    print('net ticks a lot (lots share) by market lots ahead at landing x aggressive order lots:')
    cross = defaultdict(lambda: [0, 0.0])
    for r in rows:
        c = cross[(bin_of(AHEAD_BINS, r[0]), bin_of(TAKER_BINS, r[2]))]
        c[0] += r[3]
        c[1] += r[4] + r[5]
    print(' ' * 16 + ''.join(f'{label(TAKER_BINS, k):>18}' for k in range(len(TAKER_BINS) - 1)))
    for a in range(len(AHEAD_BINS) - 1):
        cells = []
        for k in range(len(TAKER_BINS) - 1):
            lots, net = cross.get((a, k), [0, 0.0])
            cells.append(f'{net / lots:+.2f} ({lots / total:4.1%})' if lots else '-')
        print(f'{label(AHEAD_BINS, a):>16}' + ''.join(f'{c:>18}' for c in cells))


if __name__ == '__main__':
    main()
