"""Queue placement of a bot's resting orders on the Arena's exchange simulator (7 Nov).

Replays BOT on DATA with an instrumented copy of their OrderBook (insert and remove wrapped, nothing else changed) and
reports, for each of our limit orders: the lots ahead of it when it lands (market and our own), how long it rests,
what share of its lots fill, the fill share against the lots ahead at landing, and how long after its price level
formed it landed (a level that formed in front of the old touch is a new touch: early joiners sit near the front).

    uv run python -m experiments.day.queue_place BOT DATA [--session-s 5750]
"""

from __future__ import annotations

import argparse
import statistics
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('bot', type=Path)
    parser.add_argument('data', type=Path)
    args = parser.parse_args()

    clock = {'sim': None}
    landed = {}  # our order id -> record
    level_born = {}  # (side, price) -> [ts, was a new touch]
    book_cls = sim.OrderBook
    orig_insert = book_cls.insert
    orig_remove = book_cls.remove

    def now() -> int:
        return clock['sim'].current_ts_us

    def insert(self, order):
        buy = order.side == Side.BUY
        levels = self._bids if buy else self._asks
        prices = self._bid_prices if buy else self._asks_prices_safe()
        level = levels.get(order.price)
        if level is None:
            best = (prices[-1] if buy else prices[0]) if prices else None
            new_touch = best is None or (order.price > best if buy else order.price < best)
            level_born[(order.side, order.price)] = [now(), new_touch, order.owner]
        if order.owner == 'user' and order.order_type.value == 'limit':
            ahead_mkt = ahead_user = 0
            if level is not None:
                for o in level.queue:
                    if o.owner == 'market':
                        ahead_mkt += o.remaining_quantity
                    else:
                        ahead_user += o.remaining_quantity
            best = (prices[-1] if buy else prices[0]) if prices else None
            born = level_born.get((order.side, order.price))
            landed[order.order_id] = {
                'ts': now(), 'qty': order.initial_quantity, 'mkt': ahead_mkt, 'user': ahead_user,
                'at_touch': best is None or order.price == best or (order.price > best if buy else order.price < best),
                'age_us': now() - born[0] if born else 0, 'new_touch': bool(born and born[1]),
                'born_by': born[2] if born else 'user', 'end': None, 'left': None,
            }
        return orig_insert(self, order)

    def remove(self, order_id):
        order = orig_remove(self, order_id)
        if order is not None and order.owner == 'user' and order_id in landed:
            landed[order_id]['end'] = now()
            landed[order_id]['left'] = order.remaining_quantity
        return order

    book_cls._asks_prices_safe = lambda self: self._ask_prices
    book_cls.insert = insert
    book_cls.remove = remove

    config = sim.SimulationConfig(
        public_depth=20, max_position=MAX_POSITION, max_potential_position=MAX_POTENTIAL_POSITION,
        position_breach_penalty_per_second=POSITION_BREACH_PENALTY_PER_SECOND,
        order_accept_delay_ms=ORDER_ACCEPT_DELAY_MS, show_progress=False,
    )
    simulator = sim.ExchangeSimulator(strategy=load_strategy_from_file(args.bot), config=config)
    clock['sim'] = simulator
    result = simulator.run(args.data)
    print(f'pnl {result.pnl:,.0f}')
    report(landed, level_born)


def q(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, int(p * len(values)))] if values else float('nan')


def report(landed, level_born) -> None:
    rows = list(landed.values())
    for row in rows:
        left = row['left'] if row['left'] is not None else row['qty']
        row['filled'] = row['qty'] - left
        row['wait_ms'] = ((row['end'] or row['ts']) - row['ts']) / 1000
    total = sum(r['qty'] for r in rows)
    filled = sum(r['filled'] for r in rows)
    print(f'orders landed {len(rows):,}, lots {total:,}, filled {filled:,} ({filled / total:.1%})')
    print(f"at the touch when landing: {sum(r['at_touch'] for r in rows) / len(rows):.1%}")
    for name in ('mkt', 'user'):
        vals = [r[name] for r in rows]
        print(f'lots ahead ({name}): median {q(vals, .5)}, p25 {q(vals, .25)}, p75 {q(vals, .75)}, p90 {q(vals, .9)}')
    waits = [r['wait_ms'] for r in rows]
    print(f'rest (ms): median {q(waits, .5):.0f}, p25 {q(waits, .25):.0f}, p75 {q(waits, .75):.0f}, p90 {q(waits, .9):.0f}')
    fw = [r['wait_ms'] for r in rows if r['filled']]
    print(f'orders with any fill {len(fw) / len(rows):.1%}; their rest median {q(fw, .5):.0f} ms')
    print('fill share by market lots ahead at landing:')
    bins = [0, 1, 10, 25, 50, 100, 200, 400, 10**9]
    for lo, hi in zip(bins, bins[1:]):
        sel = [r for r in rows if lo <= r['mkt'] < hi]
        if sel:
            lots = sum(r['qty'] for r in sel)
            print(f'  [{lo},{hi}): orders {len(sel):6,}  lots {lots:8,}  filled {sum(r["filled"] for r in sel) / lots:6.1%}'
                  f'  any-fill {sum(1 for r in sel if r["filled"]) / len(sel):6.1%}  rest med {q([r["wait_ms"] for r in sel], .5):7.0f} ms'
                  f'  filled lots {sum(r["filled"] for r in sel):8,}')
    print('joining a level by its age at our landing (levels born as a new touch):')
    nt = [r for r in rows if r['new_touch']]
    print(f'  orders on a new-touch level {len(nt):,} of {len(rows):,}; born by us {sum(1 for r in nt if r["born_by"] == "user"):,}')
    abins = [0, 5001, 6000, 10000, 50000, 200000, 1000000, 10**12]
    for lo, hi in zip(abins, abins[1:]):
        sel = [r for r in nt if lo <= r['age_us'] < hi]
        if sel:
            lots = sum(r['qty'] for r in sel)
            print(f'  age [{lo / 1000:g},{hi / 1000:g}) ms: orders {len(sel):6,}  mkt ahead med {q([r["mkt"] for r in sel], .5):4}'
                  f'  filled {sum(r["filled"] for r in sel) / lots:6.1%}  filled lots {sum(r["filled"] for r in sel):8,}')
    new_levels = sum(1 for v in level_born.values() if v[1])
    print(f'new-touch levels still on record at the end (last birth per price): {new_levels:,}')


if __name__ == '__main__':
    main()
