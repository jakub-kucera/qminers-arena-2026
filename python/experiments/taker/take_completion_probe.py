"""Audit submitted IOC completion and the next IOC from an existing full-log run.

    uv run python -m experiments.taker.take_completion_probe LOGDIR --out REPORT.json

This is descriptive: a missing lot is not recoverable profit. The next order is
future information used only to diagnose execution, never a proposed live input.
No replay or strategy modification; marketable LIMIT fills are kept separate.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics


def analyse(logdir):
    requests = {}
    digest = hashlib.sha256()
    with (logdir / 'run.jsonl').open('rb') as fh:
        for raw in fh:
            digest.update(raw)
            if b'strategy_order_submitted' not in raw:
                continue
            row = json.loads(raw)
            if row['kind'] != 'strategy_order_submitted':
                continue
            payload = row['payload']
            req = payload['request']
            if req['order_type'] != 'ioc':
                continue
            oid = payload['order_id']
            if oid in requests:
                raise ValueError(f'duplicate submitted IOC {oid}')
            requests[oid] = dict(t=row['timestamp_us'], side=req['side'], price=req['price'],
                                 requested=req['quantity'], filled=0)
    other_aggressive = 0
    with (logdir / 'trades.csv').open() as fh:
        for row in csv.DictReader(fh):
            if row['taker_owner'] != 'user':
                continue
            req = requests.get(row['taker_order_id'])
            if req is None:
                other_aggressive += int(row['quantity'])
            else:
                req['filled'] += int(row['quantity'])
    rows = sorted(requests.values(), key=lambda r: r['t'])
    groups = {k: dict(orders=0, requested=0, filled=0, unfilled=0) for k in ('zero', 'partial', 'full')}
    retries = {str(ms): dict(orders=0, missing_lots=0, reprices=[]) for ms in (75, 100, 250)}
    for i, row in enumerate(rows):
        q, fill = row['requested'], row['filled']
        if not 0 <= fill <= q:
            raise ValueError(f'IOC fills exceed its request: {row}')
        group = groups['zero' if fill == 0 else 'full' if fill == q else 'partial']
        group['orders'] += 1
        group['requested'] += q
        group['filled'] += fill
        group['unfilled'] += q - fill
        if fill < q and i + 1 < len(rows):
            nxt = rows[i + 1]
            if nxt['side'] != row['side']:
                continue
            for ms, r in retries.items():
                if nxt['t'] - row['t'] <= int(ms) * 1000:
                    r['orders'] += 1
                    r['missing_lots'] += q - fill
                    r['reprices'].append((nxt['price'] - row['price']) * (1 if row['side'] == 'B' else -1))
    for r in retries.values():
        prices = r.pop('reprices')
        r['median_signed_reprice'] = statistics.median(prices) if prices else None
        r['worse_price_share'] = sum(p > 0 for p in prices) / len(prices) if prices else None
    total = {k: sum(g[k] for g in groups.values()) for k in ('orders', 'requested', 'filled', 'unfilled')}
    return dict(source=str(logdir), run_sha256=digest.hexdigest(), totals=total, completion=groups,
                next_ioc_same_side_within_ms=retries, other_user_aggressor_lots=other_aggressive,
                qualification='Missing lots and later repricing are descriptive, not a PnL opportunity estimate. A different order changes the subsequent book and policy.')


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('logdir', type=Path)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args(argv)
    report = analyse(a.logdir)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
