"""Rebuild a round's tape (the starter's CSV format) from a portal results folder: the private tape, approximately.

usage (from the repo root):
  uv run python -m experiments.tape.tape_from_logs RESULTS_DIR PUBLIC_TAPE OUT_CSV [--seed 0]

RESULTS_DIR is a submission's results folder (events.csv, trades.csv), PUBLIC_TAPE the round's public CSV (its G
orders' lifetimes are the prior for the cancels the logs lose), OUT_CSV the rebuilt tape. What the logs give, and what
is guessed (each guess is counted on stderr):
- a market G order that rested has an `add` event with its original volume (the simulator logs `initial_quantity`,
  after the order's own taker fills, at the same timestamp) and, if it was cancelled while resting, a `cancel` event:
  both are copied exactly;
- a resting order filled to zero has no cancel (the tape's cancel found nothing to remove): it gets one at add time +
  a lifetime drawn from the public tape's G lifetimes longer than its last fill (guessed);
- a market taker that never rested (an F order, or a G order filled in full on arrival) is only in trades.csv: it is
  written as F with volume = its traded lots and price = its worst fill (its residual and true limit are unknown); an
  F order that traded nothing is invisible and missing;
- order within a microsecond follows the logs (takers before the next add with a higher id).
Standard library only.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import random
import sys
from pathlib import Path


def fmt_time(ts_us: int) -> str:
    return f"{ts_us // 1_000_000}.{ts_us % 1_000_000:06d}"


def public_lifetimes(path: Path) -> list[int]:
    """Lifetimes in µs of the public tape's G orders that have a cancel."""
    born, out = {}, []
    with path.open() as f:
        r = csv.reader(f)
        next(r)
        for row in r:
            ts = int(round(float(row[0]) * 1_000_000))
            if row[1] == "Insert":
                if row[6] == "G":
                    born[row[2]] = ts
            else:
                t0 = born.pop(row[2], None)
                if t0 is not None:
                    out.append(ts - t0)
    out.sort()
    return out


def rebuild(results: Path, public: Path, out: Path, seed: int) -> dict[str, int]:
    rng = random.Random(seed)
    life = public_lifetimes(public)

    taker = {}  # market taker id -> [first ts, side, worst price, lots]
    filled = {}  # market order id -> lots filled (as maker or taker)
    last_fill = {}  # market maker id -> last fill ts
    with (results / "trades.csv").open() as f:
        r = csv.DictReader(f)
        for t in r:
            ts, px, q = int(t["timestamp_us"]), int(t["price"]), int(t["quantity"])
            if t["taker_owner"] == "market":
                tid = t["taker_order_id"]
                e = taker.get(tid)
                if e is None:
                    taker[tid] = [ts, t["taker_side"], px, q]
                else:
                    e[2] = max(e[2], px) if t["taker_side"] == "B" else min(e[2], px)
                    e[3] += q
                filled[tid] = filled.get(tid, 0) + q
            if t["maker_owner"] == "market":
                mid = t["maker_order_id"]
                filled[mid] = filled.get(mid, 0) + q
                last_fill[mid] = ts

    rows = []  # (ts, pos, kind, id, side, qty, price, life)
    adds, cancelled = {}, set()
    add_pos, add_ids = [], []
    with (results / "events.csv").open() as f:
        r = csv.reader(f)
        next(r)
        for pos, (ts, src, op, oid, side, px, q) in enumerate(r):
            if src != "market":
                continue
            ts = int(ts)
            if op == "add":
                rows.append((ts, pos, 0, oid, side, int(q), int(px), "G"))
                adds[oid] = (ts, int(q))
                add_pos.append(pos)
                add_ids.append(int(oid))
            elif op == "cancel":
                rows.append((ts, pos, 1, oid, "", 0, 0, ""))
                cancelled.add(oid)
            else:
                raise ValueError(f"unexpected market event {op}")

    stats = {"g_inserts": len(adds), "logged_cancels": len(cancelled)}
    # takers that never rested: F, placed before the first add with a higher id
    n_f = 0
    order = sorted(add_ids) == add_ids
    for tid, (ts, side, px, q) in taker.items():
        if tid in adds:
            continue
        n_f += 1
        k = bisect.bisect_right(add_ids, int(tid)) if order else len(add_ids)
        pos = add_pos[k] - 0.5 if k < len(add_pos) else float("inf")
        rows.append((ts, pos, 0, tid, side, q, px, "F"))
    stats["f_inserts_from_trades"] = n_f
    # resting orders filled to zero: a guessed cancel
    n_syn = n_open = 0
    for oid, (t0, q) in adds.items():
        if oid in cancelled:
            continue
        if filled.get(oid, 0) >= q:
            need = last_fill.get(oid, t0) - t0
            k = bisect.bisect_right(life, need)
            lt = life[rng.randrange(k, len(life))] if k < len(life) else need + 1
            ts = t0 + max(lt, need + 1)
            rows.append((ts, float("inf"), 1, oid, "", 0, 0, ""))
            n_syn += 1
        else:
            n_open += 1
    stats["guessed_cancels_filled_orders"] = n_syn
    stats["resting_at_end_no_cancel"] = n_open

    rows.sort(key=lambda x: (x[0], x[1]))
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Time", "Operation", "OrderId", "Side", "Volume", "Price", "Lifespan"])
        for ts, _, kind, oid, side, q, px, ls in rows:
            if kind == 0:
                w.writerow([fmt_time(ts), "Insert", oid, side, q, px, ls])
            else:
                w.writerow([fmt_time(ts), "Cancel", oid, "", "", "", ""])
    stats["rows"] = len(rows)
    stats["add_ids_sorted"] = int(order)
    return stats


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("results", type=Path)
    ap.add_argument("public", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)
    for k, v in rebuild(a.results, a.public, a.out, a.seed).items():
        print(f"{k}: {v}", file=sys.stderr)


if __name__ == "__main__":
    main()
