"""Reproducible local research using the unmodified official matching engine.

Run from repository root with .venv/Scripts/python.exe research/run_study.py.
No submissions, remote mutations, or future information enter strategy callbacks.
Harness imports/introspection below are LOCAL ONLY, not part of submission files.
"""

import argparse
import csv
import hashlib
import importlib.util
import json
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from simulator.main import load_strategy_from_file
from simulator.models import OrderStatus, Side
from simulator.simulator import ExchangeSimulator, SimulationConfig

OUT = ROOT / 'research' / 'results'
TEAM = ROOT.parents[1] / 'work' / 'jakub-arena'
REFS = ROOT / 'research' / 'reference_strategies'


def config(delay=5):
    return SimulationConfig(public_depth=20, max_position=100,
        max_potential_position=1000, position_breach_penalty_per_second=10000,
        order_accept_delay_ms=delay)


def load_bot(path, params):
    bot = load_strategy_from_file(path)
    module = sys.modules['user_strategy_module']
    for key, value in params.items():
        setattr(module, key, value)
    return bot


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, allow_nan=False), encoding='utf-8')


def profile_tape(path):
    count = 0
    operations, sides, lifespans = Counter(), Counter(), Counter()
    first = last = previous = None
    backward = 0
    min_price, max_price = 10**18, -1
    volume_sum = 0
    with path.open(newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            stamp = float(row['Time'])
            first = stamp if first is None else first
            backward += previous is not None and stamp < previous
            previous = last = stamp
            count += 1
            operations[row['Operation']] += 1
            if row['Operation'] == 'Insert':
                sides[row['Side']] += 1
                lifespans[row['Lifespan']] += 1
                price = int(row['Price'])
                min_price, max_price = min(min_price, price), max(max_price, price)
                volume_sum += int(row['Volume'])
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        bytes=path.stat().st_size, rows=count, first_s=first, last_s=last,
        duration_s=last-first, backward_timestamps=backward, operations=operations,
        insert_sides=sides, lifespans=lifespans, price_min=min_price, price_max=max_price,
        inserted_volume=volume_sum)


def run_case(case):
    name, path, data, params, delay = case
    path, data = Path(path), Path(data)
    bot = load_bot(path, params)
    simulator = ExchangeSimulator(bot, config(delay))
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    counts = Counter()
    active = {}
    inv = 0
    peak_inv = peak_reservation = 0
    market_rows, user_trades, flow_events = [], [], []
    last_sample = -1_000_000
    last_feature = -1
    features = []
    private_fill_rows = []
    send, cancel = bot.send_order, bot.cancel_order
    public, private = bot.on_order_book_change, bot.on_private_order_update

    def tracked_send(request):
        nonlocal peak_reservation
        oid = send(request)
        active[oid] = [1 if request.side == Side.BUY else -1, request.quantity]
        counts['sent'] += 1
        buys = sum(o[1] for o in active.values() if o[0] == 1)
        sells = sum(o[1] for o in active.values() if o[0] == -1)
        peak_reservation = max(peak_reservation, inv + buys, -inv + sells)
        return oid

    def tracked_cancel(oid):
        counts['cancel_requested'] += 1
        return cancel(oid)

    def tracked_private(event):
        nonlocal inv, peak_inv, peak_reservation
        counts[event.status.value] += 1
        order = active.get(event.order_id)
        if event.filled_quantity and order:
            inv += order[0] * event.filled_quantity
            private_fill_rows.append((event.timestamp_us, event.fill_price,
                                      order[0] * event.filled_quantity))
            peak_inv = max(peak_inv, abs(inv))
            order[1] = event.remaining_quantity
        if event.status in (OrderStatus.FILLED, OrderStatus.CANCELED):
            active.pop(event.order_id, None)
        if event.status == OrderStatus.REJECTED:
            counts['reject:' + (event.message or 'unknown')] += 1
            if not event.remaining_quantity:
                active.pop(event.order_id, None)
        if event.status == OrderStatus.MODIFIED and order:
            order[1] = event.remaining_quantity
        private(event)

    def tracked_public(snapshot, trades):
        nonlocal last_sample, last_feature
        for t in trades:
            if t.taker_owner == 'market' and t.maker_owner == 'market':
                if name == 'record':
                    flow_events.append((t.timestamp_us, (1 if t.book_side == 'ask' else -1), t.quantity))
            else:
                maker = t.maker_owner == 'user'
                sign = (1 if t.book_side == 'bid' else -1) if maker else (1 if t.book_side == 'ask' else -1)
                user_trades.append((t.timestamp_us, t.price, sign, t.quantity, int(maker)))
        public(snapshot, trades)
        if name == 'record' and bot.last_feature_time != last_feature:
            last_feature = bot.last_feature_time
            if last_feature >= 0:
                features.append([last_feature, bot.last_bid, bot.last_ask,
                                 *bot.last_depth, *bot.features])
        if snapshot.timestamp_us - last_sample >= 100_000:
            bid = next((o.price for o in snapshot.bids if o.owner == 'market'), None)
            ask = next((o.price for o in snapshot.asks if o.owner == 'market'), None)
            if bid is not None and ask is not None:
                market_rows.append((snapshot.timestamp_us, bid, ask))
                last_sample = snapshot.timestamp_us

    bot.send_order, bot.cancel_order = tracked_send, tracked_cancel
    bot.on_order_book_change, bot.on_private_order_update = tracked_public, tracked_private
    result = simulator.run(data)
    wall, cpu = time.perf_counter()-start_wall, time.process_time()-start_cpu
    curve = np.asarray(simulator.pnl_curve(result.pnl), dtype=float)
    cuts = [curve[0, 0] + f * (curve[-1, 0]-curve[0, 0]) for f in (0.25, 0.5, 0.75)]
    vals = [0.0] + [float(curve[np.searchsorted(curve[:, 0], c, side='right')-1, 1]) for c in cuts] + [result.pnl]
    quarters = np.diff(vals).tolist()
    drawdown = float(np.max(np.maximum.accumulate(np.r_[0.0, curve[:, 1]])-np.r_[0.0, curve[:, 1]]))
    record = dict(name=name, source=str(path), source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        data=data.name, params=params, delay_ms=delay, result=result.model_dump(mode='json'),
        wall_seconds=wall, cpu_seconds=cpu, max_abs_inventory=peak_inv,
        max_reserved_exposure=peak_reservation, final_tracked_inventory=inv,
        quarter_pnl=quarters, first_half_pnl=sum(quarters[:2]),
        third_quarter_pnl=quarters[2], last_quarter_pnl=quarters[3],
        max_drawdown=drawdown, event_counts=dict(counts))
    assert inv == result.inventory, (name, inv, result.inventory)
    dump(OUT / f'{name}.json', record)
    np.savez_compressed(OUT / f'{name}_trace.npz', curve=curve,
        market=np.asarray(market_rows, dtype=float), trades=np.asarray(user_trades, dtype=float).reshape(-1, 5),
        private_fills=np.asarray(private_fill_rows, dtype=float).reshape(-1, 3),
        features=np.asarray(features, dtype=float), flow_events=np.asarray(flow_events, dtype=float).reshape(-1, 3))
    print(f'{name}: pnl={result.pnl:,.0f} quarters={quarters} penalty={result.breach_penalty} CPU={cpu:.1f}s', flush=True)
    return record


def cases(data, duration):
    c = REFS if (REFS/'r0_F2_maker_v2.py').exists() else TEAM / 'python/bots/qminers/candidates'
    f = REFS if (REFS/'protected_maker.py').exists() else TEAM / 'python/bots/qminers/families'
    own = ROOT / 'strategies/research_candidate.py'
    fixed = ROOT / 'strategies/trend_follower_fixed.py'
    return [
        ('record', own, data, {'MODE':'record'}, 5),
        ('official_trend', ROOT/'strategies/trend_follower.py', data, {}, 5),
        ('fixed_trend', fixed, data, {}, 5),
        ('team_F2', c/'r0_F2_maker_v2.py', data, {}, 5),
        ('team_F2_cap80', c/'r0_F2_maker_v2.py', data, {'QUOTE':80,'LIMIT':80,'SKEW':60}, 5),
        ('team_M2', c/'r0_M2_runner_safe.py', data, {'SESSION_S':duration}, 5),
        ('protected_maker', f/'protected_maker.py', data, {'SESSION_S':duration}, 5),
        ('microprice_maker', own, data, {'MODE':'maker','SESSION_S':duration}, 5),
        ('mean_reversion', own, data, {'MODE':'revert','SESSION_S':duration}, 5),
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=['base','models','stress','followup'], default='base')
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    data = ROOT / 'data/sample_v2.csv'
    if args.phase == 'base':
        profile = profile_tape(data)
        dump(OUT/'dataset_profile.json', profile)
        originals = (ROOT/'strategies/trend_follower.py').read_text()
        fixed = originals.replace('            self._current_order_side = Side.BUY if self._current_order_side',
                                  '            self._order_in_flight = False\n            self._current_order_side = Side.BUY if self._current_order_side')
        assert fixed != originals
        (ROOT/'strategies/trend_follower_fixed.py').write_text(fixed, encoding='utf-8')
        tasks = cases(data, profile['duration_s'])
    else:
        tasks = json.loads((OUT/f'{args.phase}_plan.json').read_text())
    dump(OUT/f'{args.phase}_plan.json', [[n,str(p),str(d),v,l] for n,p,d,v,l in tasks])
    done = []
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(run_case, case):case[0] for case in tasks}
        for future in as_completed(futures):
            done.append(future.result())
            dump(OUT/f'{args.phase}_summary.json', done)
    print('All cases finished.', flush=True)


if __name__ == '__main__':
    main()
